#!/usr/bin/env python3
"""Print and save a Markdown summary of results/tpcc_n*/metrics_tpcc.json (and timing, if present).
usage: summarize_tpcc.py RESULTS_DIR"""
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
f = lambda x, p=3: "n/a" if x is None else "%.*f" % (p, x)
L = ["# TPC-C-style workload: results", ""]
for d in sorted(root.glob("tpcc_n*"), key=lambda p: int(p.name.split("n")[-1])):
    if not (d / "metrics_tpcc.json").exists():
        continue
    m = json.loads((d / "metrics_tpcc.json").read_text())
    w = m["workload"]
    L += ["## %d transactions per run" % m["config"]["n"], "",
          "%d runs (%d buggy, %d clean); correct recovery differs from ground truth in %d runs." % (
              m["n_runs"], m["n_buggy"], m["n_clean"], m["clean_recovery_differs_from_truth"]),
          "Mean committed per run %.1f; mean writes per committed transaction %.1f; OCC abort rate %s; committed by type %s; OCC aborts by type %s; initial keys %s." % (
              w["mean_committed"], w["mean_writes_per_committed_txn"], f(w["occ_abort_rate"]), json.dumps(w["committed_by_type"]),
              json.dumps(w["occ_aborts_by_type"]), json.dumps(w["initial_keys"])), "",
          "| checker | recall | false-bug rate | missed | false bugs | abstain buggy | abstain clean |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for ch, v in m["checkers"].items():
        L.append("| %s | %s | %s | %d | %d | %s | %s |" % (ch, f(v["recall"]), f(v["false_bug_rate"]), v["missed"], v["false_bug"], f(v["abstain_buggy"]), f(v["abstain_clean"])))
    L += ["", "By warehouses (recall / false-bug rate): " + "; ".join(
        "W=%s: " % k + ", ".join("%s %s/%s" % (ch, f(v["recall"]), f(v["false_bug_rate"])) for ch, v in b.items()) for k, b in m["by_warehouses"].items()), "",
        "| fault | buggy runs | oracle | single-log | history |", "| --- | ---: | ---: | ---: | ---: |"]
    for k, v in m["per_fault"].items():
        L.append("| %s | %d | %d | %d | %d |" % (k, v["n_buggy"], v["oracle"], v["single_log_replay"], v["history_acceptor"]))
    if m["metadata"]:
        L += ["", "| adapter setting | runs with verdict % | wrong among verdicts % | missed bugs | false bugs |", "| --- | ---: | ---: | ---: | ---: |"]
        for k, v in m["metadata"].items():
            L.append("| %s | %s | %s | %d | %d |" % (k, f(100 * v["verdict_rate"], 1), f(100 * (v["wrong_among_verdicts"] or 0), 2), v["missed"], v["false_bug"]))
    t = d / "timing_tpcc.json"
    if t.exists():
        tm = json.loads(t.read_text())
        L += ["", "Serial timing, %d checks x %d repeats: oracle check %.3f +- %.3f ms (p95 %.3f); correct replay %.3f +- %.3f ms." % (
            tm["checks_per_repeat"], tm["repeats"], tm["oracle_mean_ms"]["mean"], tm["oracle_mean_ms"]["sd"], tm["oracle_p95_ms"]["mean"],
            tm["recovery_replay_mean_ms"]["mean"], tm["recovery_replay_mean_ms"]["sd"])]
    L.append("")
(root / "summary_tpcc.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))
