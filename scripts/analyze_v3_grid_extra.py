#!/usr/bin/env python3
"""Per-config breakdowns from v3 runs.csv that the manuscript quotes: no-crash differential by
crash cut, per-fault recall, and full/degraded-adapter oracle outcome counts.
usage: analyze_v3_grid_extra.py GRID_DIR  -> writes GRID_DIR/grid_extra.json"""
import csv, json, sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
FAULTS = ["flat_order", "ignore_validation", "torn_commit_include", "stale_checkpoint_noreapply", "truncate_suffix"]
out = {}
for d in sorted(p for p in root.iterdir() if (p / "runs.csv").exists()):
    rows = list(csv.DictReader(open(d / "runs.csv", newline="")))
    full = [r for r in rows if r["hide_frontier"] == "0"]
    deg = [r for r in rows if r["hide_frontier"] == "1"]
    def rec(rs, ch):
        b = [r for r in rs if r["buggy"] == "1"]
        return [sum(r[ch + "_outcome"] == "detected" for r in b), len(b)]
    def fb(rs, ch):
        c = [r for r in rs if r["buggy"] == "0"]
        return [sum(r[ch + "_outcome"] == "false_bug" for r in c), len(c)]
    cfg = {"n_full": len(full), "n_degraded": len(deg)}
    cfg["no_crash_diff_by_drop_last"] = {
        dl: {"recall": rec([r for r in full if r["drop_last"] == dl], "crash_no_crash_diff"),
             "false_bug": fb([r for r in full if r["drop_last"] == dl], "crash_no_crash_diff")}
        for dl in ("0", "2", "4")}
    cfg["per_fault_detected_of_buggy"] = {
        f: {ch: rec([r for r in full if r["fault"] == f], ch) for ch in ("oracle", "single_log_replay", "history_acceptor")}
        for f in FAULTS}
    cfg["overall"] = {ch: {"recall": rec(full, ch), "false_bug": fb(full, ch)}
                      for ch in ("oracle", "single_log_replay", "history_acceptor", "crash_no_crash_diff")}
    cfg["full_adapter_oracle_outcomes"] = dict(Counter(r["oracle_outcome"] for r in full))
    cfg["degraded_oracle_outcomes_buggy"] = dict(Counter(r["oracle_outcome"] for r in deg if r["buggy"] == "1"))
    cfg["degraded_oracle_outcomes_clean"] = dict(Counter(r["oracle_outcome"] for r in deg if r["buggy"] == "0"))
    cfg["oracle_only_vs_single_log"] = sum(r["oracle_outcome"] == "detected" and r["single_log_replay_outcome"] != "detected" for r in full if r["buggy"] == "1")
    cfg["single_log_only_vs_oracle"] = sum(r["oracle_outcome"] != "detected" and r["single_log_replay_outcome"] == "detected" for r in full if r["buggy"] == "1")
    cfg["oracle_only_vs_history"] = sum(r["oracle_outcome"] == "detected" and r["history_acceptor_outcome"] != "detected" for r in full if r["buggy"] == "1")
    cfg["history_only_vs_oracle"] = sum(r["oracle_outcome"] != "detected" and r["history_acceptor_outcome"] == "detected" for r in full if r["buggy"] == "1")
    out[d.name] = cfg
(root / "grid_extra.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
print(json.dumps(out, sort_keys=True))
