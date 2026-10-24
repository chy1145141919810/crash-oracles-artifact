#!/usr/bin/env python3
"""Scale study: the recovery prototype at 48, 500 and 5,000 transactions per run.

Same pipeline as v4 (v3 workload generator and engine, numeric-frontier artifacts,
artifact-only oracle, flat-replay and history baselines), with three changes needed to run
at scale:

  * rows are drawn from the whole SQLite database (up to --keys rows) instead of the first
    400, so the keyspace grows with the run;
  * recovery and the baselines use the linear-time implementations from v5 (v3's
    flat-order code rebuilds a set inside a loop and is quadratic);
  * the oracle's uniqueness check walks each key's writers in topological order and tests
    consecutive pairs, instead of testing all pairs. In a partial order the two are
    equivalent. `grid` verifies on every run that this oracle returns the same verdict as
    v4's all-pairs oracle when --verify-v4 is set (used at 48 transactions).

Subcommands
  grid    correctness: recall / false-bug / abstention per checker for one configuration
  timing  serial timing of the oracle check on a fixed sample, repeated --repeats times
"""
from __future__ import annotations
import argparse, bisect, heapq, json, math, os, random, sqlite3, statistics, sys, time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v4 as p4
import real_recovery_prototype_v5 as p5

FAULTS = p3.FAULTS
ENV = {"chinook_sqlite": "RESEARCHOS_DATASET_CHINOOK_SQLITE", "northwind_sqlite": "RESEARCHOS_DATASET_NORTHWIND_SQLITE"}
_ROWS = {}


def load_rows_big(dom, cap):
    key = (dom, cap)
    if key in _ROWS:
        return _ROWS[key]
    con = sqlite3.connect(os.environ[ENV[dom]])
    recs = []
    try:
        tabs = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
        # round-robin over tables so the keyspace is not dominated by the first table
        cursors = []
        for t in tabs:
            try:
                cursors.append((t, con.execute('select * from "%s"' % t.replace('"', '""'))))
            except Exception:
                pass
        idx = defaultdict(int)
        while cursors and len(recs) < cap:
            alive = []
            for t, cur in cursors:
                rows = cur.fetchmany(64)
                if not rows:
                    continue
                alive.append((t, cur))
                for row in rows:
                    tot, seen = 0.0, False
                    for v in row:
                        if isinstance(v, bool):
                            continue
                        if isinstance(v, (int, float)) and math.isfinite(float(v)):
                            tot += abs(float(v)); seen = True
                        elif isinstance(v, bytes):
                            tot += len(v)
                        elif isinstance(v, str):
                            tot += len(v.strip())
                    i = idx[t]; idx[t] += 1
                    if not seen and tot <= 0:
                        continue
                    recs.append({"key": "%s:%s:%06d" % (dom, t, i), "value": max(1, int(tot * 100) % 100000)})
                    if len(recs) >= cap:
                        break
                if len(recs) >= cap:
                    break
            cursors = alive
    finally:
        con.close()
    _ROWS[key] = recs
    return recs


def entries_from_engine(eng, crash):
    """What v5's disk parser would return for this crash cut, built in memory. The first
    excluded commit is left as redo+validation without a commit marker; the first excluded
    OCC commit after it (if any) as redo without validation."""
    ents, dpos, oseq, ordn = [], 0, 0, {"det": 0, "occ": 0}

    def add(t, commit, validated):
        nonlocal dpos, oseq
        mode = eng["modes"][t]
        ordn[mode] += 1
        e = {"tid": t, "mode": mode, "log": mode, "ord": ordn[mode], "writes": list(eng["redo"][t]),
             "commit": commit, "validated": validated}
        if mode == "det":
            dpos += 1; e["det_pos"] = dpos; e["occ_frontier"] = oseq
        else:
            oseq += 1; e["occ_seq"] = oseq; e["det_frontier"] = dpos
        ents.append(e)

    for t in crash["durable"]:
        add(t, True, True)
    dropped = eng["committed"][len(crash["durable"]):]
    if dropped:
        add(dropped[0], False, True)
        later_occ = [t for t in dropped[1:] if eng["modes"][t] == "occ"]
        if later_occ:
            add(later_occ[0], False, False)
    ck = eng["ckpt"]
    ckpt = {"included": list(ck["included"]), "state": ck["state"]} if crash["ckpt_usable"] else None
    return {"entries": ents, "checkpoint": ckpt}


def oracle_fast(art, d_rec):
    """v4 oracle with a chain-based uniqueness check (same verdicts, near-linear)."""
    recs = sorted(art["det_log"] + art["occ_log"], key=lambda r: r["tid"])
    members = [r for r in recs if r.get("commit") and (r["mode"] == "det" or r.get("validated"))]
    ck = art["checkpoint"]
    inc = set(ck["included"]) if ck else set()
    base = ck["state"] if ck else art["initial"]
    suffix = [r for r in members if r["tid"] not in inc]
    n = len(suffix)
    idx = {r["tid"]: i for i, r in enumerate(suffix)}
    succ = [set() for _ in range(n)]
    det = sorted([r for r in suffix if r["mode"] == "det"], key=lambda r: r["det_pos"])
    occ = sorted([r for r in suffix if r["mode"] == "occ" and "occ_seq" in r], key=lambda r: r["occ_seq"])
    for chain in (det, occ):
        for x, y in zip(chain, chain[1:]):
            succ[idx[x["tid"]]].add(idx[y["tid"]])
    det_pos = [r["det_pos"] for r in det]
    occ_seq = [r["occ_seq"] for r in occ]
    for o in suffix:
        if o["mode"] == "occ" and "det_frontier" in o:
            k = bisect.bisect_right(det_pos, o["det_frontier"])
            if k > 0:
                succ[idx[det[k - 1]["tid"]]].add(idx[o["tid"]])
            if k < len(det):
                succ[idx[o["tid"]]].add(idx[det[k]["tid"]])
    for d in det:
        if "occ_frontier" in d:
            k = bisect.bisect_right(occ_seq, d["occ_frontier"])
            if k > 0:
                succ[idx[occ[k - 1]["tid"]]].add(idx[d["tid"]])
            if k < len(occ):
                succ[idx[d["tid"]]].add(idx[occ[k]["tid"]])
    indeg = [0] * n
    for a in range(n):
        for b in succ[a]:
            indeg[b] += 1
    heap = [i for i in range(n) if indeg[i] == 0]
    heapq.heapify(heap)
    order = []
    while heap:
        a = heapq.heappop(heap)
        order.append(a)
        for b in succ[a]:
            indeg[b] -= 1
            if indeg[b] == 0:
                heapq.heappush(heap, b)
    if len(order) != n:
        return "precfail"
    pos = [0] * n
    for p, a in enumerate(order):
        pos[a] = p
    reach = [0] * n
    for a in reversed(order):
        m = 0
        for b in succ[a]:
            m |= (1 << b) | reach[b]
        reach[a] = m
    by_key = defaultdict(list)
    for i, r in enumerate(suffix):
        seen = set()
        for wk, af in r["writes"]:
            by_key[wk].append((i, af))
    for wk, ws in by_key.items():
        if len({af for _, af in ws}) < 2:
            continue
        chain = sorted({i for i, _ in ws}, key=lambda i: pos[i])
        for a, b in zip(chain, chain[1:]):
            if not (reach[a] >> b) & 1:
                return "uncertain"
    ref = p3._apply(base, [suffix[i]["writes"] for i in order])
    return "match" if ref == d_rec else "mismatch"


def build(cfg, dom, seed, mix_det, ckpt_after):
    records = load_rows_big(dom, cfg["keys"])
    base, txns = p3.gen_workload(records, seed * 131 + 17, cfg["n"], mix_det, cfg["wpt"], cfg["workload"], cfg["theta"])
    return base, p3.run_engine(base, txns, ckpt_after)


def cases(cfg, dom, seed, mix_det, ckpt_after):
    """Yields (descriptor, initial, disk, artifacts, recovered state, truth) for one engine run."""
    base, eng = build(cfg, dom, seed, mix_det, ckpt_after)
    if len(eng["committed"]) < 12:
        return
    for drop_last in (0, 2, 4):
        crash = p3.apply_crash(eng, drop_last)
        disk = entries_from_engine(eng, crash)
        art = p5.to_artifacts(disk, base)
        for fault in FAULTS:
            d_rec = p5.recover_from_disk(disk, base, fault)
            yield (dom, seed, mix_det, ckpt_after, drop_last, fault), base, disk, art, d_rec, crash["gt_state"], eng


def grid_cell(task):
    cfg, dom, seed, mix_det, ckpt_after = task
    rows = []
    stats = Counter()
    for desc, base, disk, art, d_rec, truth, eng in cases(cfg, dom, seed, mix_det, ckpt_after):
        buggy = d_rec != truth
        art0 = p4.apply_adapter(art, 0, None, 0.0, None)
        preds = {"oracle": oracle_fast(art, d_rec), "oracle_detorder_only": oracle_fast(art0, d_rec),
                 "single_log_replay": p5.single_log_check(disk, base, d_rec),
                 "history_acceptor": p5.history_check(disk, base, d_rec)}
        if cfg["verify_v4"]:
            stats["v4_checked"] += 2
            stats["v4_equal"] += int(p4.oracle_v4(art, d_rec) == preds["oracle"]) + int(p4.oracle_v4(art0, d_rec) == preds["oracle_detorder_only"])
        row = {"fault": desc[5], "drop_last": desc[4], "buggy": int(buggy)}
        for k, v in preds.items():
            row[k] = p3.score(v, buggy)
        rows.append(row)
        if desc[4] == 0 and desc[5] == "clean":
            stats["engines"] += 1
            stats["occ"] += eng["n_occ"]; stats["occ_committed"] += eng["n_occ_committed"]
            stats["committed"] += len(eng["committed"]); stats["keys"] += len(base)
    return rows, stats


def summarize(rows):
    buggy = [r for r in rows if r["buggy"]]
    clean = [r for r in rows if not r["buggy"]]
    out = {"n_runs": len(rows), "n_buggy": len(buggy), "n_clean": len(clean), "checkers": {}, "per_fault": {}}
    for ch in ("oracle", "oracle_detorder_only", "single_log_replay", "history_acceptor"):
        cb, cc = Counter(r[ch] for r in buggy), Counter(r[ch] for r in clean)
        out["checkers"][ch] = {"recall": cb["detected"] / len(buggy) if buggy else None,
                               "false_bug_rate": cc["false_bug"] / len(clean) if clean else None,
                               "missed": cb["missed"], "false_bug": cc["false_bug"],
                               "abstain_buggy": cb["abstained"] / len(buggy) if buggy else None,
                               "abstain_clean": cc["abstained_clean"] / len(clean) if clean else None}
    for f in FAULTS:
        fb = [r for r in buggy if r["fault"] == f]
        out["per_fault"][f] = {"n_buggy": len(fb), **{ch: sum(r[ch] == "detected" for r in fb) for ch in ("oracle", "single_log_replay", "history_acceptor")}}
    return out


def grid_main(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = {"n": a.n, "keys": a.keys, "wpt": a.writes_per_txn, "workload": a.workload, "theta": a.theta, "verify_v4": a.verify_v4}
    tasks = [(cfg, dom, seed, mix, ck) for dom in ENV for seed in range(a.seeds) for mix in (0.25, 0.5, 0.75) for ck in (0, a.n // 3)]
    t0 = time.time()
    rows, stats = [], Counter()
    with Pool(a.jobs) as pool:
        for part, st in pool.imap(grid_cell, tasks, chunksize=1):
            rows += part; stats += st
    m = summarize(rows)
    m["config"] = {"n": a.n, "keys_requested": a.keys, "writes_per_txn": a.writes_per_txn, "workload": a.workload,
                   "theta": a.theta if a.workload == "ycsb" else None, "seeds": a.seeds}
    m["wall_s"] = round(time.time() - t0, 1); m["jobs"] = a.jobs
    e = max(1, stats["engines"])
    m["workload_stats"] = {"engine_executions": stats["engines"], "mean_committed": stats["committed"] / e,
                           "mean_keys": stats["keys"] / e,
                           "occ_abort_rate": 1 - stats["occ_committed"] / stats["occ"] if stats["occ"] else None}
    if a.verify_v4:
        m["v4_equivalence"] = {"checked": stats["v4_checked"], "equal": stats["v4_equal"]}
    (out / "metrics_scale.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


def timing_main(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = {"n": a.n, "keys": a.keys, "wpt": a.writes_per_txn, "workload": a.workload, "theta": a.theta, "verify_v4": False}
    sample = []
    for dom in ENV:
        for seed in range(a.sample_seeds):
            for mix in (0.25, 0.5, 0.75):
                for ck in (0, a.n // 3):
                    for desc, base, disk, art, d_rec, truth, eng in cases(cfg, dom, seed, mix, ck):
                        sample.append((base, disk, art, d_rec))
    reps = []
    for _ in range(a.repeats):
        o, r = [], []
        for base, disk, art, d_rec in sample:
            t0 = time.perf_counter(); oracle_fast(art, d_rec); o.append(time.perf_counter() - t0)
            t0 = time.perf_counter(); p5.recover_from_disk(disk, base, "clean"); r.append(time.perf_counter() - t0)
        o.sort(); r.sort()
        reps.append({"oracle_mean_ms": 1e3 * sum(o) / len(o), "oracle_p95_ms": 1e3 * o[int(0.95 * (len(o) - 1))],
                     "recovery_mean_ms": 1e3 * sum(r) / len(r)})
    def ms(key):
        xs = [x[key] for x in reps]
        return {"mean": statistics.mean(xs), "sd": statistics.stdev(xs) if len(xs) > 1 else 0.0, "values": xs}
    m = {"config": {"n": a.n, "keys_requested": a.keys, "writes_per_txn": a.writes_per_txn, "workload": a.workload,
                    "theta": a.theta if a.workload == "ycsb" else None},
         "checks_per_repeat": len(sample), "repeats": a.repeats,
         "oracle_mean_ms": ms("oracle_mean_ms"), "oracle_p95_ms": ms("oracle_p95_ms"), "recovery_replay_mean_ms": ms("recovery_mean_ms")}
    (out / "timing_scale.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("grid", "timing"):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--n", type=int, required=True)
        s.add_argument("--keys", type=int, required=True)
        s.add_argument("--writes-per-txn", type=int, default=1, choices=[1, 3, 5, 8])
        s.add_argument("--workload", default="rmw", choices=["rmw", "ycsb"])
        s.add_argument("--theta", type=float, default=0.0)
        if name == "grid":
            s.add_argument("--seeds", type=int, required=True); s.add_argument("--jobs", type=int, default=8)
            s.add_argument("--verify-v4", action="store_true")
        else:
            s.add_argument("--sample-seeds", type=int, default=1); s.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args(argv)
    return grid_main(a) if a.cmd == "grid" else timing_main(a)


if __name__ == "__main__":
    raise SystemExit(main())
