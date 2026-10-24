#!/usr/bin/env python3
"""TPC-C-style workload on the on-disk crash model (real log files, engine process killed).

Same on-disk format, injection points, parser, recovery variants and checkers as
real_recovery_prototype_v5.py; only the engine process differs: it executes the TPC-C-style
procedures of tpcc_study.py instead of the v3 workload. Ground truth is computed by the driver
from the schedule and the injection point and never reads the files. POSIX only (SIGKILL).

Subcommands: run (driver), engine (child process that is killed).
"""
from __future__ import annotations
import argparse, csv, hashlib, json, os, random, shutil, signal, subprocess, sys, tempfile, time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tpcc_study as tp          # also puts the rev_20261007 scripts on sys.path
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v4 as p4
import real_recovery_prototype_v5 as p5

FAULTS = p3.FAULTS


def schedule(n, warehouses, seed, mix_det, ckpt_after):
    base = tp.initial_db(warehouses)
    return base, tp.run_engine_proc(base, tp.gen_workload(seed * 131 + 17, n, mix_det, warehouses), ckpt_after)


def engine_main(a):
    base, eng = schedule(a.n, a.warehouses, a.seed, a.mix_det, a.ckpt_after)
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
            dpos += 1; fd = fds["det"]
            redo = {"t": "redo", "tid": tid, "pos": dpos, "of": oseq, "w": eng["redo"][tid]}
        else:
            oseq += 1; fd = fds["occ"]
            redo = {"t": "redo", "tid": tid, "seq": oseq, "df": dpos, "w": eng["redo"][tid]}
        b = p5.frame(redo)
        if here and a.crash_step == 1:
            os.write(fd, b[: max(1, len(b) // 2)]); die()
        os.write(fd, b)
        if here and a.crash_step == 2:
            die()
        if mode == "occ":
            os.write(fd, p5.frame({"t": "valid", "tid": tid}))
        if here and a.crash_step == 3:
            die()
        os.write(fd, p5.frame({"t": "commit", "tid": tid}))
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
            os.write(cfd, body); os.fsync(cfd); os.close(cfd)
            if here and a.crash_step == 7:
                die()
            os.rename(tmp, str(d / "ckpt.json"))
            if here and a.crash_step == 8:
                die()
    return 0


def run_cell(task):
    cfg, warehouses, seed, mix_det, ckpt_after = task
    base, eng = schedule(cfg["n"], warehouses, seed, mix_det, ckpt_after)
    committed = eng["committed"]
    n = len(committed)
    if n < 12:
        return []
    h = hashlib.sha256(("%d|%d|%s|%d" % (warehouses, seed, mix_det, ckpt_after)).encode()).hexdigest()
    rng = random.Random(int(h[:12], 16))
    points = [(n, 0), (n - 2, rng.randint(1, 5)), (n - 4, rng.randint(1, 5))]
    if eng["ckpt"] and rng.random() < 0.5:
        points.append((ckpt_after - 1, rng.choice([6, 7, 8])))
    else:
        points.append((rng.randint(8, n - 1), rng.randint(1, 5)))
    rows = []
    for crash_i, step in points:
        d = Path(tempfile.mkdtemp(prefix="tpcc_", dir=cfg["work"]))
        cmd = [sys.executable, str(Path(__file__).resolve()), "engine", "--dir", str(d), "--n", str(cfg["n"]),
               "--warehouses", str(warehouses), "--seed", str(seed), "--mix-det", str(mix_det),
               "--ckpt-after", str(ckpt_after), "--crash-i", str(crash_i), "--crash-step", str(step)]
        rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE).returncode
        durable_n = n if step == 0 else crash_i + (1 if step >= 4 else 0)
        truth = p3._apply(base, [eng["redo"][t] for t in committed[:durable_n]])
        disk = p5.parse_dir(d)
        art = p5.to_artifacts(disk, base)
        art0 = p4.apply_adapter(art, 0, None, 0.0, None)
        for fault in FAULTS:
            d_rec = p5.recover_from_disk(disk, base, fault)
            buggy = d_rec != truth
            row = {"warehouses": warehouses, "seed": seed, "mix_det": mix_det, "ckpt_after": ckpt_after,
                   "crash_i": crash_i, "crash_step": step, "exit_code": rc,
                   "kill_as_expected": int((rc == -signal.SIGKILL) == (step != 0)),
                   "torn": int(disk["torn"]["det"] or disk["torn"]["occ"]), "fault": fault, "buggy": int(buggy)}
            for name, pred in (("oracle", p4.oracle_v4(art, d_rec)), ("oracle_detorder_only", p4.oracle_v4(art0, d_rec)),
                               ("single_log_replay", p5.single_log_check(disk, base, d_rec)),
                               ("history_acceptor", p5.history_check(disk, base, d_rec))):
                row[name] = p3.score(pred, buggy)
            rows.append(row)
        shutil.rmtree(d, ignore_errors=True)
    return rows


def driver_main(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="crashoracle_tpcc_", dir=a.work))
    cfg = {"n": a.n, "work": str(work)}
    tasks = [(cfg, w, seed, mix, ck) for w in (1, 4) for seed in range(a.seeds) for mix in (0.25, 0.5, 0.75) for ck in (0, a.n // 3)]
    t0 = time.time()
    with Pool(a.jobs) as pool:
        rows = [r for part in pool.imap(run_cell, tasks, chunksize=2) for r in part]
    shutil.rmtree(work, ignore_errors=True)
    crashes = {(r["warehouses"], r["seed"], r["mix_det"], r["ckpt_after"], r["crash_i"], r["crash_step"]): r for r in rows}
    m = {"config": {"n": a.n, "warehouses": [1, 4], "seeds": a.seeds}, "wall_s": round(time.time() - t0, 1), "jobs": a.jobs,
         "n_recovery_runs": len(rows), "n_buggy": sum(r["buggy"] for r in rows), "n_clean": sum(1 - r["buggy"] for r in rows),
         "n_distinct_crash_points": len(crashes),
         "engine_exit_codes": dict(Counter(str(r["exit_code"]) for r in crashes.values())),
         "kill_not_as_expected": sum(1 - r["kill_as_expected"] for r in crashes.values()),
         "crash_steps": dict(Counter(str(r["crash_step"]) for r in crashes.values())),
         "dirs_with_torn_tail": sum(r["torn"] for r in crashes.values()),
         "clean_recovery_differs_from_truth": sum(1 for r in rows if r["fault"] == "clean" and r["buggy"]),
         "checkers": {ch: tp.block(rows, ch) for ch in ("oracle", "oracle_detorder_only", "single_log_replay", "history_acceptor")},
         "per_fault": {}}
    for f in FAULTS:
        fb = [r for r in rows if r["fault"] == f and r["buggy"]]
        m["per_fault"][f] = {"n_buggy": len(fb), **{ch: sum(r[ch] == "detected" for r in fb) for ch in ("oracle", "single_log_replay", "history_acceptor")}}
    (out / "metrics_tpcc_disk.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    with (out / "runs_tpcc_disk.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow(r)
    print(json.dumps(m, indent=1, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("engine")
    for name, typ in (("--dir", str), ("--n", int), ("--warehouses", int), ("--seed", int), ("--mix-det", float),
                      ("--ckpt-after", int), ("--crash-i", int), ("--crash-step", int)):
        e.add_argument(name, type=typ, required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", required=True); r.add_argument("--n", type=int, default=48); r.add_argument("--seeds", type=int, default=40)
    r.add_argument("--jobs", type=int, default=8); r.add_argument("--work", default=tempfile.gettempdir())
    a = ap.parse_args(argv)
    return engine_main(a) if a.cmd == "engine" else driver_main(a)


if __name__ == "__main__":
    raise SystemExit(main())
