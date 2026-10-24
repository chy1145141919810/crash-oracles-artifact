#!/usr/bin/env python3
"""Recovery prototype v4: an artifact-only oracle evaluated under imperfect adapter metadata.

Why: in v1-v3 the "cross-mode frontier" was a pointer to the true commit predecessor and the
oracle read engine internals, so with the full adapter its reference equalled ground truth by
construction and it could not be wrong. v4 makes the oracle falsifiable.

What is the same as v3 (imported, not copied): workload generation, the mixed engine, crash
cuts, the six recovery variants, ground truth, and the label (a run is buggy iff its recovered
state differs from the engine-side replay of the durable committed prefix).

What is new:
  1. emit_artifacts(): what survives the crash, as two logs. A det record carries its batch
     position and an OCC frontier (number of OCC commits durable before it). An OCC record
     carries its validation/commit sequence number, a validation marker and a det frontier
     (number of det commits it follows). No predecessor pointers, no commit-order list.
  2. oracle_v4(): reads ONLY those artifacts, the checkpoint and the recovered state. It never
     touches the engine object. It derives order edges from positions and frontiers, returns
     precfail on a cycle, uncertain when a pair writing different after-images to a shared key
     is unordered, and otherwise replays and compares.
  3. Adapter settings applied to the artifacts before the oracle sees them:
       L0 det order only | L1 + OCC stream order | L2 + det frontier on OCC records |
       L3 + OCC frontier on det records (redundant with L2)
       missing(p): each frontier field independently absent with probability p
       stale(q):   with probability q an OCC record's det frontier lags by 1-3 positions
                   (recorded before validation instead of at validation)
     Ground truth and labels never depend on the adapter setting.

Each oracle outcome is scored against ground truth as detected / missed / abstained (uncertain
or precfail) on buggy runs and correct / false_bug / abstained on clean runs.
"""
from __future__ import annotations
import argparse, copy, csv, hashlib, json, os, random, sys, time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_recovery_prototype_v3 as p3

SETTINGS = (
    [("L0", 0, None, 0.0), ("L1", 1, None, 0.0), ("L2", 2, None, 0.0), ("L3", 3, None, 0.0)]
    + [("L2_missing%.2f" % p, 2, "missing", p) for p in (0.10, 0.25, 0.50)]
    + [("L3_missing%.2f" % p, 3, "missing", p) for p in (0.10, 0.25, 0.50)]
    + [("L2_stale%.2f" % q, 2, "stale", q) for q in (0.05, 0.25)]
    + [("L3_stale%.2f" % q, 3, "stale", q) for q in (0.05, 0.25)]
    + [("L2_wrong%.2f" % q, 2, "wrong", q) for q in (0.05, 0.25)]
    + [("L3_wrong%.2f" % q, 3, "wrong", q) for q in (0.05, 0.25)]
    + [("L3_swapocc%.2f" % q, 3, "swapocc", q) for q in (0.05, 0.25)]
    + [("L3_ckpt_extra", 3, "ckpt_extra", 1.0)]
)


def emit_artifacts(eng, crash):
    det_log, occ_log = [], []
    dpos = oseq = 0
    for t in crash["durable"]:
        if eng["modes"][t] == "det":
            dpos += 1
            det_log.append({"tid": t, "mode": "det", "writes": list(eng["redo"][t]), "commit": True,
                            "det_pos": dpos, "occ_frontier": oseq})
        else:
            oseq += 1
            occ_log.append({"tid": t, "mode": "occ", "writes": list(eng["redo"][t]), "commit": True,
                            "validated": bool(eng["validation"].get(t)),
                            "occ_seq": oseq, "det_frontier": dpos})
    ck = eng["ckpt"]
    ckpt = {"included": list(ck["included"]), "state": dict(ck["state"])} if crash["ckpt_usable"] else None
    return {"det_log": det_log, "occ_log": occ_log, "checkpoint": ckpt, "initial": dict(eng["base"])}


def apply_adapter(art, level, fault, rate, rng):
    a = {"det_log": [dict(r) for r in art["det_log"]], "occ_log": [dict(r) for r in art["occ_log"]],
         "checkpoint": art["checkpoint"], "initial": art["initial"]}
    for r in a["occ_log"]:
        if level < 1:
            r.pop("occ_seq", None)
        if level < 2:
            r.pop("det_frontier", None)
    for r in a["det_log"]:
        if level < 3:
            r.pop("occ_frontier", None)
    if fault == "missing":
        for r in a["occ_log"]:
            if "det_frontier" in r and rng.random() < rate:
                del r["det_frontier"]
        for r in a["det_log"]:
            if "occ_frontier" in r and rng.random() < rate:
                del r["occ_frontier"]
    elif fault == "stale":
        for r in a["occ_log"]:
            if "det_frontier" in r and rng.random() < rate:
                r["det_frontier"] = max(0, r["det_frontier"] - rng.randint(1, 3))
    elif fault == "wrong":
        # the frontier field holds an unrelated value (0..number of durable det commits)
        ndet = len(a["det_log"])
        for r in a["occ_log"]:
            if "det_frontier" in r and rng.random() < rate:
                r["det_frontier"] = rng.randint(0, ndet)
    elif fault == "swapocc":
        # two adjacent OCC records carry each other's validation sequence number
        log = a["occ_log"]
        i = 0
        while i + 1 < len(log):
            if rng.random() < rate:
                log[i]["occ_seq"], log[i + 1]["occ_seq"] = log[i + 1]["occ_seq"], log[i]["occ_seq"]
                i += 2
            else:
                i += 1
    elif fault == "ckpt_extra":
        # the checkpoint certificate claims one more transaction than the snapshot contains
        ck = a["checkpoint"]
        if ck:
            inc = set(ck["included"])
            later = sorted((r for r in a["det_log"] + a["occ_log"] if r["tid"] not in inc),
                           key=lambda r: (r["mode"], r.get("det_pos", r.get("occ_seq", 0))))
            if later:
                a["checkpoint"] = {"included": list(ck["included"]) + [later[0]["tid"]], "state": ck["state"]}
    return a


def oracle_v4(art, d_rec):
    """Artifact-only durable-prefix oracle. Returns match / mismatch / uncertain / precfail."""
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
    import bisect
    for o in suffix:
        if o["mode"] != "occ" or "det_frontier" not in o:
            continue
        k = bisect.bisect_right(det_pos, o["det_frontier"])      # det[0:k] precede o
        if k > 0:
            succ[idx[det[k - 1]["tid"]]].add(idx[o["tid"]])
        if k < len(det):
            succ[idx[o["tid"]]].add(idx[det[k]["tid"]])
    for d in det:
        if "occ_frontier" not in d:
            continue
        k = bisect.bisect_right(occ_seq, d["occ_frontier"])      # occ[0:k] precede d
        if k > 0:
            succ[idx[occ[k - 1]["tid"]]].add(idx[d["tid"]])
        if k < len(occ):
            succ[idx[d["tid"]]].add(idx[occ[k]["tid"]])
    # stable topological order (tie-break by tid); a cycle means contradictory order evidence
    indeg = [0] * n
    for a in range(n):
        for b in succ[a]:
            indeg[b] += 1
    ready = sorted(i for i in range(n) if indeg[i] == 0)
    order = []
    while ready:
        a = ready.pop(0)
        order.append(a)
        for b in sorted(succ[a]):
            indeg[b] -= 1
            if indeg[b] == 0:
                ready.append(b)
        ready.sort()
    if len(order) != n:
        return "precfail"
    reach = [0] * n
    for a in reversed(order):
        m = 0
        for b in succ[a]:
            m |= (1 << b) | reach[b]
        reach[a] = m
    by_key = defaultdict(list)
    for i, r in enumerate(suffix):
        for wk, af in r["writes"]:
            by_key[wk].append((i, af))
    for wk, ws in by_key.items():
        if len({af for _, af in ws}) < 2:
            continue
        for x in range(len(ws)):
            for y in range(x + 1, len(ws)):
                a, b = ws[x][0], ws[y][0]
                if a == b:
                    continue
                if not ((reach[a] >> b) & 1 or (reach[b] >> a) & 1):
                    return "uncertain"
    ref = p3._apply(base, [suffix[i]["writes"] for i in order])
    return "match" if p3.canon(ref) == p3.canon(d_rec) else "mismatch"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--writes-per-txn", type=int, default=1, choices=[1, 3, 5, 8])
    ap.add_argument("--workload", default="rmw", choices=["rmw", "ycsb"])
    ap.add_argument("--theta", type=float, default=0.0)
    args = ap.parse_args(argv)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    paths = {"chinook_sqlite": os.environ.get("RESEARCHOS_DATASET_CHINOOK_SQLITE", ""),
             "northwind_sqlite": os.environ.get("RESEARCHOS_DATASET_NORTHWIND_SQLITE", "")}
    datasets = {}
    for name, p in paths.items():
        if p and Path(p).exists() and p3.is_sqlite(Path(p)):
            datasets[name] = p3.load_rows(Path(p), name)
    if len(datasets) < 2:
        print(json.dumps({"error": "datasets unavailable", "have": list(datasets)})); return 1

    rows = []
    timing = defaultdict(list)
    regress = Counter()
    for dom, records in datasets.items():
        for seed in range(args.seeds):
            for mix_det in (0.25, 0.5, 0.75):
                base, txns = p3.gen_workload(records, seed * 131 + 17, args.n, mix_det,
                                             args.writes_per_txn, args.workload, args.theta)
                for ckpt_after in (0, args.n // 3):
                    eng = p3.run_engine(base, txns, ckpt_after)
                    if len(eng["committed"]) < 12:
                        continue
                    for drop_last in (0, 2, 4):
                        crash = p3.apply_crash(eng, drop_last)
                        dropped = eng["committed"][len(crash["durable"]):]
                        torn_tid = dropped[0] if dropped else None
                        art = emit_artifacts(eng, crash)
                        views = {}
                        for name, level, fault, rate in SETTINGS:
                            h = hashlib.sha256(("%s|%d|%s|%d|%d|%s" % (dom, seed, mix_det, ckpt_after, drop_last, name)).encode()).hexdigest()
                            views[name] = apply_adapter(art, level, fault, rate, random.Random(int(h[:12], 16)))
                        for fault in p3.FAULTS:
                            d_rec = p3.recover(eng, crash, fault, drop_commit_tid=torn_tid)
                            buggy = p3.canon(d_rec) != p3.canon(crash["gt_state"])
                            row = {"domain": dom, "seed": seed, "mix_det": mix_det, "ckpt_after": ckpt_after,
                                   "drop_last": drop_last, "fault": fault, "buggy": int(buggy)}
                            for name, _, _, _ in SETTINGS:
                                t0 = time.perf_counter()
                                pred = oracle_v4(views[name], d_rec)
                                timing[name].append(time.perf_counter() - t0)
                                row[name + "_pred"] = pred
                                row[name] = p3.score(pred, buggy)
                            # regression against the v3 oracle (which reads engine internals)
                            v3_full = p3.score(p3.oracle_check(eng, crash, d_rec, hide_frontier=False), buggy)
                            v3_hidden = p3.score(p3.oracle_check(eng, crash, d_rec, hide_frontier=True), buggy)
                            regress["n"] += 1
                            regress["L3_equals_v3_full"] += int(row["L3"] == v3_full)
                            regress["L2_equals_v3_full"] += int(row["L2"] == v3_full)
                            regress["L0_equals_v3_hidden"] += int(row["L0"] == v3_hidden)
                            rows.append(row)

    buggy_rows = [r for r in rows if r["buggy"]]
    clean_rows = [r for r in rows if not r["buggy"]]
    metrics = {"config": {"workload": args.workload, "writes_per_txn": args.writes_per_txn,
                          "theta": args.theta if args.workload == "ycsb" else None, "seeds": args.seeds, "n": args.n},
               "n_runs": len(rows), "n_buggy": len(buggy_rows), "n_clean": len(clean_rows),
               "regression_vs_v3": dict(regress), "settings": {}}
    for name, level, fault, rate in SETTINGS:
        cb = Counter(r[name] for r in buggy_rows)
        cc = Counter(r[name] for r in clean_rows)
        preds = Counter(r[name + "_pred"] for r in rows)
        xs = sorted(timing[name])
        metrics["settings"][name] = {
            "level": level, "fault": fault, "rate": rate,
            "buggy": {"detected": cb["detected"], "missed": cb["missed"], "abstained": cb["abstained"]},
            "clean": {"correct": cc["correct_clean"], "false_bug": cc["false_bug"], "abstained": cc["abstained_clean"]},
            "raw_verdicts": dict(preds),
            "verdict_rate": (cb["detected"] + cb["missed"] + cc["correct_clean"] + cc["false_bug"]) / len(rows),
            "wrong_verdicts": cb["missed"] + cc["false_bug"],
            "wrong_among_verdicts": ((cb["missed"] + cc["false_bug"]) / max(1, cb["detected"] + cb["missed"] + cc["correct_clean"] + cc["false_bug"])),
            "oracle_mean_us": round(1e6 * sum(xs) / len(xs), 2), "oracle_p95_us": round(1e6 * xs[int(0.95 * (len(xs) - 1))], 2),
        }
    (out / "metrics_v4.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    with (out / "runs_v4.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow(r)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
