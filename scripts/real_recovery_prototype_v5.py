#!/usr/bin/env python3
"""Recovery prototype v5: real log files and real process crashes.

v1-v4 modelled a crash by truncating an in-memory list. Here the engine is a separate OS
process that writes CRC-framed records to two append-only log files and a checkpoint file,
and dies by SIGKILL at an injection point. Recovery, the oracle and the baselines then read
the bytes that are actually on disk, including torn tails.

  engine process  : loads the dataset, generates the v3 workload, executes the mixed
                    det/OCC schedule (v3 engine logic), then logs each commit in order:
                    redo record -> (OCC) validation marker -> commit marker -> fsync.
                    After `ckpt_after` commits it writes a checkpoint to a temp file, fsyncs
                    and renames it. At the injection point (commit index, step) it sends
                    itself SIGKILL. Steps: 1 half of the redo bytes written, 2 redo complete,
                    3 validation marker written, 4 commit marker written, 5 after fsync,
                    6 half of the checkpoint temp file, 7 temp file complete, 8 after rename.
  ground truth    : computed by the driver from the schedule and the injection point alone
                    (commit i is durable iff the kill is at step >= 4). It never reads the
                    files, so it is independent of the parser, the adapter and the oracle.
  recovery        : reads the files; one correct variant and five faulty ones.
  checkers        : v4 artifact-only oracle (full metadata, and det-order-only), single-log
                    flat replay, order-blind history acceptor. All read parsed disk content.

Crash model: process kill. Bytes handed to the kernel survive; this is not a power-loss
model and loses no unsynced data.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, random, shutil, signal, struct, subprocess, sys, tempfile, time, zlib
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v4 as p4

FAULTS = p3.FAULTS
DATASET_ENV = {"chinook_sqlite": "RESEARCHOS_DATASET_CHINOOK_SQLITE", "northwind_sqlite": "RESEARCHOS_DATASET_NORTHWIND_SQLITE"}


def frame(obj):
    b = json.dumps(obj, separators=(",", ":")).encode()
    return struct.pack("<II", len(b), zlib.crc32(b)) + b


def build_schedule(dom, seed, mix_det, ckpt_after, n, wpt, workload, theta):
    records = p3.load_rows(Path(os.environ[DATASET_ENV[dom]]), dom)
    base, txns = p3.gen_workload(records, seed * 131 + 17, n, mix_det, wpt, workload, theta)
    return base, p3.run_engine(base, txns, ckpt_after)


# ------------------------------ engine process ------------------------------

def engine_main(a):
    base, eng = build_schedule(a.dom, a.seed, a.mix_det, a.ckpt_after, a.n, a.writes_per_txn, a.workload, a.theta)
    d = Path(a.dir)
    fds = {"det": os.open(str(d / "det.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600),
           "occ": os.open(str(d / "occ.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)}

    def die():
        os.kill(os.getpid(), signal.SIGKILL)
        time.sleep(60)

    dpos = oseq = 0
    for i, tid in enumerate(eng["committed"]):
        here = (i == a.crash_i)
        mode = eng["modes"][tid]
        if mode == "det":
            dpos += 1
            fd = fds["det"]
            redo = {"t": "redo", "tid": tid, "pos": dpos, "of": oseq, "w": eng["redo"][tid]}
        else:
            oseq += 1
            fd = fds["occ"]
            redo = {"t": "redo", "tid": tid, "seq": oseq, "df": dpos, "w": eng["redo"][tid]}
        b = frame(redo)
        if here and a.crash_step == 1:
            os.write(fd, b[: max(1, len(b) // 2)]); die()
        os.write(fd, b)
        if here and a.crash_step == 2:
            die()
        if mode == "occ":
            os.write(fd, frame({"t": "valid", "tid": tid}))
        if here and a.crash_step == 3:
            die()
        os.write(fd, frame({"t": "commit", "tid": tid}))
        if here and a.crash_step == 4:
            die()
        os.fsync(fd)
        if here and a.crash_step == 5:
            die()
        ck = eng["ckpt"]
        if ck and i + 1 == a.ckpt_after:
            body = json.dumps({"included": ck["included"], "state": ck["state"], "digest": p3._digest(ck["state"])},
                              separators=(",", ":")).encode()
            tmp = str(d / "ckpt.tmp")
            cfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            if here and a.crash_step == 6:
                os.write(cfd, body[: len(body) // 2]); die()
            os.write(cfd, body)
            os.fsync(cfd)
            os.close(cfd)
            if here and a.crash_step == 7:
                die()
            os.rename(tmp, str(d / "ckpt.json"))
            if here and a.crash_step == 8:
                die()
    return 0


# ------------------------------ reading the disk ------------------------------

def parse_log(path):
    if not path.exists():
        return [], False
    data = path.read_bytes()
    off, out = 0, []
    while off + 8 <= len(data):
        ln, crc = struct.unpack_from("<II", data, off)
        body = data[off + 8: off + 8 + ln]
        if len(body) < ln or zlib.crc32(body) != crc:
            break
        out.append(json.loads(body))
        off += 8 + ln
    return out, off < len(data)


def parse_dir(d):
    ents, torn = [], {}
    for log, mode in (("det", "det"), ("occ", "occ")):
        recs, torn[log] = parse_log(d / (log + ".log"))
        cur = {}
        ordinal = 0
        for r in recs:
            if r["t"] == "redo":
                ordinal += 1
                e = {"tid": r["tid"], "mode": mode, "log": log, "ord": ordinal,
                     "writes": [(k, v) for k, v in r["w"]], "commit": False, "validated": False}
                if mode == "det":
                    e["det_pos"] = r["pos"]; e["occ_frontier"] = r["of"]
                else:
                    e["occ_seq"] = r["seq"]; e["det_frontier"] = r["df"]
                cur[r["tid"]] = e
                ents.append(e)
            elif r["t"] == "valid" and r["tid"] in cur:
                cur[r["tid"]]["validated"] = True
            elif r["t"] == "commit" and r["tid"] in cur:
                cur[r["tid"]]["commit"] = True
    ckpt = None
    p = d / "ckpt.json"
    if p.exists():
        try:
            c = json.loads(p.read_text())
            if p3._digest(c["state"]) == c["digest"]:
                ckpt = {"included": c["included"], "state": c["state"]}
        except Exception:
            ckpt = None
    return {"entries": ents, "torn": torn, "checkpoint": ckpt, "ckpt_tmp_left": (d / "ckpt.tmp").exists()}


def is_member(e):
    return e["commit"] and (e["mode"] == "det" or e["validated"])


def durable_order(members):
    det = sorted([e for e in members if e["mode"] == "det"], key=lambda e: e["det_pos"])
    occ = sorted([e for e in members if e["mode"] == "occ"], key=lambda e: e["occ_seq"])
    out, i = [], 0
    for o in occ:
        while i < len(det) and det[i]["det_pos"] <= o["det_frontier"]:
            out.append(det[i]); i += 1
        out.append(o)
    return out + det[i:]


def flat_order(members):
    return sorted(members, key=lambda e: (e["ord"], e["log"]))


def recover_from_disk(disk, initial, fault):
    """Recovery under test. `fault` selects an injected recovery bug."""
    ents, ck = disk["entries"], disk["checkpoint"]
    members = [e for e in ents if is_member(e)]
    extra = []
    if fault == "ignore_validation":
        extra = [e for e in ents if e["mode"] == "occ" and not e["validated"]]
    if fault == "torn_commit_include":
        extra = [e for e in ents if not e["commit"] and (e["mode"] == "det" or e["validated"])]
    order = flat_order(members) if fault == "flat_order" else durable_order(members)
    if ck:
        if fault == "stale_checkpoint_noreapply":
            return dict(ck["state"])
        inc = set(ck["included"])
        base = ck["state"]
        order = [e for e in order if e["tid"] not in inc]
    else:
        base = initial
    if fault == "truncate_suffix" and order:
        order = order[:-1]
    return p3._apply(base, [e["writes"] for e in order + extra])


def to_artifacts(disk, initial):
    """Adapter: parsed disk content -> the v4 artifact interface."""
    det_log, occ_log = [], []
    for e in disk["entries"]:
        r = {"tid": e["tid"], "mode": e["mode"], "writes": e["writes"], "commit": e["commit"]}
        if e["mode"] == "det":
            r["det_pos"] = e["det_pos"]; r["occ_frontier"] = e["occ_frontier"]; det_log.append(r)
        else:
            r["validated"] = e["validated"]; r["occ_seq"] = e["occ_seq"]; r["det_frontier"] = e["det_frontier"]; occ_log.append(r)
    return {"det_log": det_log, "occ_log": occ_log, "checkpoint": disk["checkpoint"], "initial": initial}


def single_log_check(disk, initial, d_rec):
    ck = disk["checkpoint"]
    order = flat_order([e for e in disk["entries"] if is_member(e)])
    base = initial
    if ck:
        inc = set(ck["included"]); base = ck["state"]; order = [e for e in order if e["tid"] not in inc]
    ref = p3._apply(base, [e["writes"] for e in order])
    return "match" if p3.canon(ref) == p3.canon(d_rec) else "mismatch"


def history_check(disk, initial, d_rec):
    ck = disk["checkpoint"]
    members = [e for e in disk["entries"] if is_member(e)]
    base = initial
    if ck:
        inc = set(ck["included"]); base = ck["state"]; members = [e for e in members if e["tid"] not in inc]
    poss = defaultdict(set)
    for e in members:
        for wk, af in e["writes"]:
            poss[wk].add(af)
    for k, v in d_rec.items():
        if k in poss:
            if v not in poss[k]:
                return "mismatch"
        elif v != base.get(k, 0):
            return "mismatch"
    return "match"


# ------------------------------ driver ------------------------------

def run_cell(task):
    cfg, dom, seed, mix_det, ckpt_after = task
    base, eng = build_schedule(dom, seed, mix_det, ckpt_after, cfg["n"], cfg["wpt"], cfg["workload"], cfg["theta"])
    committed = eng["committed"]
    n = len(committed)
    if n < 12:
        return []
    h = hashlib.sha256(("%s|%d|%s|%d" % (dom, seed, mix_det, ckpt_after)).encode()).hexdigest()
    rng = random.Random(int(h[:12], 16))
    points = [(n, 0), (n - 2, rng.randint(1, 5)), (n - 4, rng.randint(1, 5))]
    if eng["ckpt"] and rng.random() < 0.5:
        points.append((ckpt_after - 1, rng.choice([6, 7, 8])))
    else:
        points.append((rng.randint(8, n - 1), rng.randint(1, 5)))
    rows = []
    for crash_i, step in points:
        d = Path(tempfile.mkdtemp(prefix="v5_", dir=cfg["work"]))
        cmd = [sys.executable, str(Path(__file__).resolve()), "engine", "--dir", str(d), "--dom", dom, "--seed", str(seed),
               "--mix-det", str(mix_det), "--ckpt-after", str(ckpt_after), "--n", str(cfg["n"]),
               "--writes-per-txn", str(cfg["wpt"]), "--workload", cfg["workload"], "--theta", str(cfg["theta"]),
               "--crash-i", str(crash_i), "--crash-step", str(step)]
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).returncode
        killed = (rc == -signal.SIGKILL)
        expected_kill = step != 0
        durable_n = n if step == 0 else crash_i + (1 if step >= 4 else 0)
        truth = p3._apply(base, [eng["redo"][t] for t in committed[:durable_n]])
        disk = parse_dir(d)
        art = to_artifacts(disk, base)
        art0 = p4.apply_adapter(art, 0, None, 0.0, rng)
        for fault in FAULTS:
            d_rec = recover_from_disk(disk, base, fault)
            buggy = p3.canon(d_rec) != p3.canon(truth)
            row = {"domain": dom, "seed": seed, "mix_det": mix_det, "ckpt_after": ckpt_after,
                   "crash_i": crash_i, "crash_step": step, "n_committed": n, "durable_n": durable_n,
                   "exit_code": rc, "kill_as_expected": int(killed == expected_kill),
                   "torn_det": int(disk["torn"]["det"]), "torn_occ": int(disk["torn"]["occ"]),
                   "ckpt_on_disk": int(disk["checkpoint"] is not None), "ckpt_tmp_left": int(disk["ckpt_tmp_left"]),
                   "fault": fault, "buggy": int(buggy)}
            t0 = time.perf_counter()
            o = p4.oracle_v4(art, d_rec)
            row["oracle_us"] = round(1e6 * (time.perf_counter() - t0), 2)
            for name, pred in (("oracle", o), ("oracle_detorder_only", p4.oracle_v4(art0, d_rec)),
                               ("single_log_replay", single_log_check(disk, base, d_rec)),
                               ("history_acceptor", history_check(disk, base, d_rec))):
                row[name + "_pred"] = pred
                row[name] = p3.score(pred, buggy)
            rows.append(row)
        shutil.rmtree(d, ignore_errors=True)
    return rows


def driver_main(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="crashoracle_v5_", dir=a.work))
    cfg = {"n": a.n, "wpt": a.writes_per_txn, "workload": a.workload, "theta": a.theta, "work": str(work)}
    tasks = [(cfg, dom, seed, mix, ck) for dom in DATASET_ENV for seed in range(a.seeds)
             for mix in (0.25, 0.5, 0.75) for ck in (0, a.n // 3)]
    t0 = time.time()
    with Pool(a.jobs) as pool:
        rows = [r for part in pool.imap(run_cell, tasks, chunksize=4) for r in part]
    wall = time.time() - t0
    shutil.rmtree(work, ignore_errors=True)

    buggy = [r for r in rows if r["buggy"]]
    clean = [r for r in rows if not r["buggy"]]
    crashes = {(r["domain"], r["seed"], r["mix_det"], r["ckpt_after"], r["crash_i"], r["crash_step"]): r for r in rows}
    m = {"config": {"workload": a.workload, "writes_per_txn": a.writes_per_txn,
                    "theta": a.theta if a.workload == "ycsb" else None, "seeds": a.seeds, "n": a.n},
         "n_engine_processes": len(crashes), "n_recovery_runs": len(rows), "n_buggy": len(buggy), "n_clean": len(clean),
         "wall_s": round(wall, 1), "jobs": a.jobs,
         "engine_exit_codes": dict(Counter(str(r["exit_code"]) for r in crashes.values())),
         "kill_not_as_expected": sum(1 - r["kill_as_expected"] for r in crashes.values()),
         "crash_steps": dict(Counter(str(r["crash_step"]) for r in crashes.values())),
         "dirs_with_torn_tail": sum(1 for r in crashes.values() if r["torn_det"] or r["torn_occ"]),
         "dirs_with_checkpoint": sum(r["ckpt_on_disk"] for r in crashes.values()),
         "dirs_with_leftover_ckpt_tmp": sum(r["ckpt_tmp_left"] for r in crashes.values()),
         "clean_recovery_differs_from_truth": sum(1 for r in rows if r["fault"] == "clean" and r["buggy"]),
         "checkers": {}, "per_fault": {}}
    for ch in ("oracle", "oracle_detorder_only", "single_log_replay", "history_acceptor"):
        cb, cc = Counter(r[ch] for r in buggy), Counter(r[ch] for r in clean)
        m["checkers"][ch] = {"buggy": {"detected": cb["detected"], "missed": cb["missed"], "abstained": cb["abstained"]},
                             "clean": {"correct": cc["correct_clean"], "false_bug": cc["false_bug"], "abstained": cc["abstained_clean"]},
                             "recall": cb["detected"] / len(buggy) if buggy else None,
                             "false_bug_rate": cc["false_bug"] / len(clean) if clean else None,
                             "raw_verdicts": dict(Counter(r[ch + "_pred"] for r in rows))}
    for f in FAULTS:
        fb = [r for r in rows if r["fault"] == f and r["buggy"]]
        m["per_fault"][f] = {"n": sum(1 for r in rows if r["fault"] == f), "n_buggy": len(fb),
                             **{ch: sum(r[ch] == "detected" for r in fb) for ch in ("oracle", "single_log_replay", "history_acceptor")}}
    us = sorted(r["oracle_us"] for r in rows)
    m["oracle_us_under_parallel_load"] = {"mean": round(sum(us) / len(us), 2), "p95": us[int(0.95 * (len(us) - 1))]}
    (out / "metrics_v5.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    with (out / "runs_v5.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow(r)
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("engine", "run"):
        s = sub.add_parser(name)
        s.add_argument("--n", type=int, default=48)
        s.add_argument("--writes-per-txn", type=int, default=1, choices=[1, 3, 5, 8])
        s.add_argument("--workload", default="rmw", choices=["rmw", "ycsb"])
        s.add_argument("--theta", type=float, default=0.0)
        if name == "engine":
            s.add_argument("--dir", required=True); s.add_argument("--dom", required=True)
            s.add_argument("--seed", type=int, required=True); s.add_argument("--mix-det", type=float, required=True)
            s.add_argument("--ckpt-after", type=int, required=True)
            s.add_argument("--crash-i", type=int, required=True); s.add_argument("--crash-step", type=int, required=True)
        else:
            s.add_argument("--out", required=True); s.add_argument("--seeds", type=int, default=40)
            s.add_argument("--jobs", type=int, default=8); s.add_argument("--work", default=tempfile.gettempdir())
    a = ap.parse_args(argv)
    return engine_main(a) if a.cmd == "engine" else driver_main(a)


if __name__ == "__main__":
    raise SystemExit(main())
