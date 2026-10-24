#!/usr/bin/env python3
"""Collect rerun_check/v3_multikey/*/metrics_real_recovery.json into one table (JSON + Markdown)."""
import json, sys
from pathlib import Path

root = Path(sys.argv[1])
rows = []
for d in sorted(p for p in root.iterdir() if (p / "metrics_real_recovery.json").exists()):
    m = json.loads((d / "metrics_real_recovery.json").read_text())
    c = m["config"]; ch = m["checkers"]
    rows.append({
        "config": d.name, "workload": c["workload"], "writes_per_txn": c["writes_per_txn"], "theta": c["theta"],
        "n_full": m["n_full_adapter"], "n_buggy": ch["oracle"]["n_buggy"], "n_clean": ch["oracle"]["n_clean"],
        "skipped_engines": m["contention"]["skipped_fewer_than_12_committed"],
        "occ_abort_rate": m["contention"]["occ_abort_rate"],
        "cross_mode_order_bugs": m["cross_mode_order_bug_slice"]["n"],
        **{k + "_recall": ch[k]["recall_on_buggy_recoveries"] for k in ch},
        **{k + "_false_bug": ch[k]["false_bug_rate_on_clean"] for k in ch},
        "xmo_single_log_recall": m["cross_mode_order_bug_slice"]["single_log_replay_recall"],
        "xmo_history_recall": m["cross_mode_order_bug_slice"]["history_acceptor_recall"],
        "xmo_oracle_recall": m["cross_mode_order_bug_slice"]["oracle_recall"],
        "full_oracle_abstain_buggy": m["full_adapter_oracle_abstain"]["on_buggy"],
        "full_oracle_abstain_clean": m["full_adapter_oracle_abstain"]["on_clean"],
        "degraded_abstain_buggy": m["degraded_adapter_missing_frontier"]["oracle_abstain_rate"],
        "degraded_missed_buggy": m["degraded_adapter_missing_frontier"]["oracle_false_or_missed"],
        "degraded_abstain_clean": m["degraded_adapter_clean"]["oracle_abstain_rate"],
        "degraded_false_bug_clean": m["degraded_adapter_clean"]["oracle_false_bug_rate"],
        "oracle_mean_us": m["operational_cost"]["oracle_check_time"]["mean_us"],
        "oracle_p95_us": m["operational_cost"]["oracle_check_time"]["p95_us"],
        "recovery_mean_us": m["operational_cost"]["recovery_time"]["mean_us"],
        "gain_vs_single_log": m["oracle_minus_single_log_recall_gain"],
    })
(root / "grid_summary.json").write_text(json.dumps(rows, indent=2) + "\n")

def f(x, p=3):
    return "n/a" if x is None else ("%.*f" % (p, x))
L = ["# v3 grid summary (full adapter unless noted)", "",
     "| config | buggy | clean | occ abort | x-mode order bugs | oracle R/F | single-log R/F | history R/F | no-crash R/F | x-mode: single/history | degraded abstain buggy/clean | degraded missed/false | oracle us mean/p95 |",
     "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |"]
for r in rows:
    L.append("| %s | %d | %d | %s | %d | %s/%s | %s/%s | %s/%s | %s/%s | %s/%s | %s/%s | %s/%s | %s/%s |" % (
        r["config"], r["n_buggy"], r["n_clean"], f(r["occ_abort_rate"]), r["cross_mode_order_bugs"],
        f(r["oracle_recall"]), f(r["oracle_false_bug"]),
        f(r["single_log_replay_recall"]), f(r["single_log_replay_false_bug"]),
        f(r["history_acceptor_recall"]), f(r["history_acceptor_false_bug"]),
        f(r["crash_no_crash_diff_recall"]), f(r["crash_no_crash_diff_false_bug"]),
        f(r["xmo_single_log_recall"]), f(r["xmo_history_recall"]),
        f(r["degraded_abstain_buggy"]), f(r["degraded_abstain_clean"]),
        f(r["degraded_missed_buggy"]), f(r["degraded_false_bug_clean"]),
        f(r["oracle_mean_us"], 1), f(r["oracle_p95_us"], 1)))
(root / "grid_summary.md").write_text("\n".join(L) + "\n")
print("\n".join(L))
