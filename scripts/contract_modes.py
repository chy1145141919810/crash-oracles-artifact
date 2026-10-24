#!/usr/bin/env python3
"""Score every checker under two durability contracts for in-doubt transactions.

An in-doubt transaction has complete durable redo and, if optimistic, a durable validation
marker, but no durable commit marker.

  strict   the commit marker decides: an in-doubt transaction must be excluded. This is the
           contract used everywhere else in the evaluation.
  lenient  recovery may include or exclude an in-doubt transaction. A recovered state is
           correct if it equals the durable prefix with any subset of the in-doubt
           transactions applied at their recorded positions.

A transaction with redo but without a validation marker is not in doubt under either
contract: nothing durable says it passed validation.

Oracle modes
  oracle_strict   the oracle as used elsewhere (chain-check implementation).
  oracle_lenient  the same oracle run once per subset of in-doubt transactions treated as
                  committed; `match` if any run matches, otherwise the first non-match
                  verdict in the order uncertain, precfail, mismatch.

The runs are exactly those exported for Elle (same enumeration as elle_histories.py), so the
Elle verdict files line up by file name.

usage: contract_modes.py --workload {tpcc,rmw,ycsb} [...] --elle-dir DIR --out FILE.json
"""
from __future__ import annotations
import argparse, csv, itertools, json, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import elle_histories as eh
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v5 as p5
import scale_study as ss

ELLE = ["elle_cli_default", "elle_wfr", "elle_lin", "elle_wfr_lin"]
FAULTS = [f for f in p3.FAULTS if f != "clean"]


def in_doubt(disk):
    return [e for e in disk["entries"] if not e["commit"] and (e["mode"] == "det" or e["validated"])]


def with_committed(disk, tids):
    ents = [dict(e, commit=True) if e["tid"] in tids else e for e in disk["entries"]]
    return {"entries": ents, "checkpoint": disk["checkpoint"]}


def lenient_truths(disk, base):
    cands = [e["tid"] for e in in_doubt(disk)]
    out = []
    for r in range(len(cands) + 1):
        for sub in itertools.combinations(cands, r):
            out.append(p5.recover_from_disk(with_committed(disk, set(sub)), base, "clean"))
    return out, len(cands)


def oracle_lenient(disk, base, d_rec):
    cands = [e["tid"] for e in in_doubt(disk)]
    verdicts = []
    for r in range(len(cands) + 1):
        for sub in itertools.combinations(cands, r):
            v = ss.oracle_fast(p5.to_artifacts(with_committed(disk, set(sub)), base), d_rec)
            if v == "match":
                return "match"
            verdicts.append(v)
    for v in ("uncertain", "precfail"):
        if v in verdicts:
            return v
    return "mismatch"


def load_elle(path):
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            parts = [p.strip() for p in line.split("\t")]
            if len(parts) >= 2 and parts[0].endswith(".edn"):
                out[parts[0]] = {"false": "mismatch", "true": "match"}.get(parts[1], "uncertain")
    return out


def block(rows, col, label):
    b = [r for r in rows if r[label]]; c = [r for r in rows if not r[label]]
    cb = Counter(p3.score(r[col], True) for r in b); cc = Counter(p3.score(r[col], False) for r in c)
    return {"n_buggy": len(b), "n_clean": len(c), "detected": cb["detected"], "missed": cb["missed"],
            "false_bug": cc["false_bug"], "no_verdict": cb["abstained"] + cc["abstained_clean"],
            "recall": cb["detected"] / len(b) if b else None, "false_bug_rate": cc["false_bug"] / len(c) if c else None}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", required=True, choices=["tpcc", "rmw", "ycsb"])
    ap.add_argument("--n", type=int, default=48); ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--writes-per-txn", type=int, default=1); ap.add_argument("--theta", type=float, default=0.0)
    ap.add_argument("--elle-dir", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    edir = Path(a.elle_dir)
    index = list(csv.DictReader(open(edir / "index.csv", newline="")))
    elle = {k: load_elle(edir / (k + ".txt")) for k in ELLE}
    rows = []
    for scale, seed, mix, ck, base, eng, meta in eh.engines(a):
        if len(eng["committed"]) < 12:
            continue
        for drop_last in (0, 2, 4):
            crash = p3.apply_crash(eng, drop_last)
            disk = ss.entries_from_engine(eng, crash)
            art = p5.to_artifacts(disk, base)
            truths, n_doubt = lenient_truths(disk, base)
            for fault in p3.FAULTS:
                d_rec = p5.recover_from_disk(disk, base, fault)
                name = "%05d.edn" % len(rows)
                idx = index[len(rows)]
                assert idx["file"] == name and idx["fault"] == fault and int(idx["drop_last"]) == drop_last
                strict = d_rec != crash["gt_state"]
                assert int(idx["buggy"]) == int(strict)
                row = {"file": name, "fault": fault, "in_doubt": n_doubt,
                       "buggy_strict": strict, "buggy_lenient": all(d_rec != t for t in truths),
                       "oracle_strict": ss.oracle_fast(art, d_rec), "oracle_lenient": oracle_lenient(disk, base, d_rec),
                       "single_log_replay": p5.single_log_check(disk, base, d_rec),
                       "history_acceptor": p5.history_check(disk, base, d_rec)}
                for k in ELLE:
                    row[k] = elle[k].get(name, "uncertain")
                rows.append(row)
    cols = ["oracle_strict", "oracle_lenient", "single_log_replay", "history_acceptor"] + [k for k in ELLE if elle[k]]
    res = {"n_runs": len(rows), "runs_with_in_doubt_txn": sum(1 for r in rows if r["in_doubt"]),
           "label_changes_strict_to_lenient": sum(1 for r in rows if r["buggy_strict"] and not r["buggy_lenient"]),
           "label_changes_by_fault": dict(Counter(r["fault"] for r in rows if r["buggy_strict"] and not r["buggy_lenient"])),
           "strict": {c: block(rows, c, "buggy_strict") for c in cols},
           "lenient": {c: block(rows, c, "buggy_lenient") for c in cols},
           "per_fault": {}}
    for f in FAULTS:
        fr = [r for r in rows if r["fault"] == f]
        res["per_fault"][f] = {"buggy_strict": sum(r["buggy_strict"] for r in fr), "buggy_lenient": sum(r["buggy_lenient"] for r in fr),
                               **{c: {"reported": sum(r[c] == "mismatch" for r in fr),
                                      "reported_and_buggy_lenient": sum(r[c] == "mismatch" and r["buggy_lenient"] for r in fr)} for c in cols}}
    Path(a.out).write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    f3 = lambda x: "n/a" if x is None else "%.3f" % x
    print(a.workload, "runs", res["n_runs"], "with in-doubt txn", res["runs_with_in_doubt_txn"], "labels flipped", res["label_changes_strict_to_lenient"], res["label_changes_by_fault"])
    for conv in ("strict", "lenient"):
        print(" ", conv, {c: "%s/%s" % (f3(v["recall"]), f3(v["false_bug_rate"])) for c, v in res[conv].items()}, "buggy", res[conv]["oracle_strict"]["n_buggy"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
