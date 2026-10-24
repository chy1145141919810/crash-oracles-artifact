#!/usr/bin/env python3
"""Witness minimization for oracle mismatches (delta debugging).

Input: a recovery run on which the artifact-only oracle (v4, full metadata) reports
`mismatch`. The run is determined by (transactions, checkpoint position, crash cut,
recovery variant). The minimizer shrinks it while the oracle still reports `mismatch`:

  1. ddmin over the transaction list (remaining transactions keep their ids, modes, read and
     write sets and timing; the engine is re-executed on every candidate, so OCC outcomes
     are recomputed, not assumed);
  2. the crash cut is reduced to the smallest number of excluded commits that still fails;
  3. the checkpoint is removed if possible, otherwise moved as early as possible;
  4. repeat 1-3 until nothing changes, then verify 1-minimality (removing any single
     remaining transaction makes the mismatch disappear).

The predicate uses only the oracle's verdict, as a user of the tool would. Ground truth is
consulted afterwards, only to report whether each minimized witness is still a real bug.

Engine, crash model and recovery variants are v3's in-memory ones; artifacts and oracle are
v4's.
"""
from __future__ import annotations
import argparse, json, os, statistics, sys, time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v4 as p4

FAULTS = [f for f in p3.FAULTS if f != "clean"]


class Case:
    def __init__(self, base, fault):
        self.base, self.fault, self.tests = base, fault, 0

    def run(self, txns, ckpt_after, drop_last):
        """Returns (oracle verdict, truly buggy, committed count, differing keys) or None."""
        self.tests += 1
        eng = p3.run_engine(self.base, txns, ckpt_after)
        n = len(eng["committed"])
        if drop_last > n:
            return None
        crash = p3.apply_crash(eng, drop_last)
        dropped = eng["committed"][len(crash["durable"]):]
        d_rec = p3.recover(eng, crash, self.fault, drop_commit_tid=dropped[0] if dropped else None)
        pred = p4.oracle_v4(p4.emit_artifacts(eng, crash), d_rec)
        gt = crash["gt_state"]
        diff = sum(1 for k in set(gt) | set(d_rec) if gt.get(k) != d_rec.get(k))
        return pred, p3.canon(d_rec) != p3.canon(gt), n, diff

    def fails(self, txns, ckpt_after, drop_last):
        r = self.run(txns, ckpt_after, drop_last)
        return r is not None and r[0] == "mismatch"


def ddmin(items, test):
    n = 2
    while len(items) >= 2:
        size = max(1, len(items) // n)
        chunks = [items[i:i + size] for i in range(0, len(items), size)]
        reduced = False
        for i in range(len(chunks)):
            cand = [x for j, c in enumerate(chunks) if j != i for x in c]
            if cand and test(cand):
                items, n, reduced = cand, max(n - 1, 2), True
                break
        if not reduced:
            if n >= len(items):
                break
            n = min(len(items), n * 2)
    return items


def minimize(case, txns, ckpt_after, drop_last):
    for _ in range(4):
        before = (len(txns), ckpt_after, drop_last)
        txns = ddmin(txns, lambda c: case.fails(c, ckpt_after, drop_last))
        # single-transaction witness is allowed: try removing each remaining transaction
        changed = True
        while changed and len(txns) > 1:
            changed = False
            for i in range(len(txns)):
                cand = txns[:i] + txns[i + 1:]
                if case.fails(cand, ckpt_after, drop_last):
                    txns, changed = cand, True
                    break
        for d in range(0, drop_last):
            if case.fails(txns, ckpt_after, d):
                drop_last = d
                break
        if ckpt_after:
            if case.fails(txns, 0, drop_last):
                ckpt_after = 0
            else:
                for k in range(1, ckpt_after):
                    if case.fails(txns, k, drop_last):
                        ckpt_after = k
                        break
        if (len(txns), ckpt_after, drop_last) == before:
            break
    one_minimal = all(not case.fails(txns[:i] + txns[i + 1:], ckpt_after, drop_last) for i in range(len(txns))) if len(txns) > 1 else True
    return txns, ckpt_after, drop_last, one_minimal


def q(xs):
    xs = sorted(xs)
    if not xs:
        return None
    if len(xs) == 1:
        return {"median": xs[0], "q1": xs[0], "q3": xs[0], "min": xs[0], "max": xs[0]}
    qs = statistics.quantiles(xs, n=4, method="inclusive")
    return {"median": statistics.median(xs), "q1": qs[0], "q3": qs[2], "min": xs[0], "max": xs[-1]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--writes-per-txn", type=int, default=1, choices=[1, 3, 5, 8])
    ap.add_argument("--workload", default="rmw", choices=["rmw", "ycsb"])
    ap.add_argument("--theta", type=float, default=0.0)
    ap.add_argument("--per-fault", type=int, default=200, help="mismatch runs to minimize per recovery fault")
    a = ap.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    datasets = {}
    for name, env in (("chinook_sqlite", "RESEARCHOS_DATASET_CHINOOK_SQLITE"), ("northwind_sqlite", "RESEARCHOS_DATASET_NORTHWIND_SQLITE")):
        datasets[name] = p3.load_rows(Path(os.environ[env]), name)

    # enumerate the same grid as the prototype and collect every oracle mismatch
    cands = defaultdict(list)
    for dom, records in datasets.items():
        for seed in range(a.seeds):
            for mix_det in (0.25, 0.5, 0.75):
                base, txns = p3.gen_workload(records, seed * 131 + 17, a.n, mix_det, a.writes_per_txn, a.workload, a.theta)
                for ckpt_after in (0, a.n // 3):
                    if len(p3.run_engine(base, txns, ckpt_after)["committed"]) < 12:
                        continue
                    for drop_last in (0, 2, 4):
                        for fault in FAULTS:
                            if Case(base, fault).fails(txns, ckpt_after, drop_last):
                                cands[fault].append((dom, seed, mix_det, ckpt_after, drop_last))
    rows = []
    for fault in FAULTS:
        pool = cands[fault]
        step = max(1, len(pool) // a.per_fault)
        for dom, seed, mix_det, ckpt_after, drop_last in pool[::step][: a.per_fault]:
            base, txns = p3.gen_workload(datasets[dom], seed * 131 + 17, a.n, mix_det, a.writes_per_txn, a.workload, a.theta)
            case = Case(base, fault)
            orig = case.run(txns, ckpt_after, drop_last)
            case.tests = 0
            t0 = time.perf_counter()
            mt, mck, mdrop, one_min = minimize(case, list(txns), ckpt_after, drop_last)
            secs = time.perf_counter() - t0
            tests = case.tests
            fin = case.run(mt, mck, mdrop)
            rows.append({"fault": fault, "domain": dom, "seed": seed, "mix_det": mix_det,
                         "orig_txns": len(txns), "orig_committed": orig[2], "orig_ckpt_after": ckpt_after, "orig_drop_last": drop_last,
                         "orig_diff_keys": orig[3],
                         "min_txns": len(mt), "min_committed": fin[2], "min_ckpt_after": mck, "min_drop_last": mdrop,
                         "min_diff_keys": fin[3], "min_modes": "".join(sorted(t.mode[0] for t in mt)),
                         "still_mismatch": int(fin[0] == "mismatch"), "still_truly_buggy": int(fin[1]),
                         "one_minimal": int(one_min), "tests": tests, "ms": round(1000 * secs, 2)})
    m = {"config": {"workload": a.workload, "writes_per_txn": a.writes_per_txn,
                    "theta": a.theta if a.workload == "ycsb" else None, "seeds": a.seeds, "n": a.n, "per_fault_cap": a.per_fault},
         "mismatch_runs_available": {f: len(cands[f]) for f in FAULTS}, "per_fault": {}}
    for fault in FAULTS + ["all"]:
        rs = [r for r in rows if fault == "all" or r["fault"] == fault]
        if not rs:
            continue
        shapes = defaultdict(int)
        for r in rs:
            shapes["%s|ckpt=%d|cut=%d" % (r["min_modes"], r["min_ckpt_after"], r["min_drop_last"])] += 1
        m["per_fault"][fault] = {
            "n_minimized": len(rs), "orig_txns": q([r["orig_txns"] for r in rs]),
            "min_txns": q([r["min_txns"] for r in rs]), "min_drop_last": q([r["min_drop_last"] for r in rs]),
            "min_with_checkpoint": sum(1 for r in rs if r["min_ckpt_after"] > 0),
            "min_diff_keys": q([r["min_diff_keys"] for r in rs]), "orig_diff_keys": q([r["orig_diff_keys"] for r in rs]),
            "tests": q([r["tests"] for r in rs]), "ms": q([r["ms"] for r in rs]),
            "still_mismatch": sum(r["still_mismatch"] for r in rs), "still_truly_buggy": sum(r["still_truly_buggy"] for r in rs),
            "one_minimal": sum(r["one_minimal"] for r in rs),
            "top_shapes": dict(sorted(shapes.items(), key=lambda kv: -kv[1])[:4]),
        }
    (out / "metrics_witness.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    import csv
    with (out / "witnesses.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow(r)
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
