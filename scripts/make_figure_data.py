#!/usr/bin/env python3
"""Write the pgfplots data files used by manuscript_vldb/main.tex from the result files.

usage: make_figure_data.py RERUN_CHECK_DIR OUT_DIR
  RERUN_CHECK_DIR is experiments/rev_20261007/rerun_check (or the same folder on the server).

fig_scale.dat     oracle check time and correct-replay time (ms, mean of five serial repeats)
                  against transactions per run; from scale_study/*/timing_scale.json
fig_missing.dat   share of runs with a verdict (%) against the share of frontier fields that
                  are absent, one- and two-sided evidence; from v4_adapter_faults/summary.json
"""
import json, sys
from pathlib import Path

rc, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)

cols = [("rmw_w1", "rmw1"), ("rmw_w8", "rmw8"), ("ycsb_w1_theta0.99", "ycsb1"), ("ycsb_w8_theta0.99", "ycsb8")]
lines = ["txns " + " ".join(c for _, c in cols) + " " + " ".join("replay_" + c for _, c in cols)]
for n in (48, 500, 5000):
    row, rep = [], []
    for d, _ in cols:
        t = json.load(open(rc / "scale_study" / ("n%d_%s" % (n, d)) / "timing_scale.json"))
        row.append("%.4f" % t["oracle_mean_ms"]["mean"])
        rep.append("%.4f" % t["recovery_replay_mean_ms"]["mean"])
    lines.append("%d %s %s" % (n, " ".join(row), " ".join(rep)))
(out / "fig_scale.dat").write_text("\n".join(lines) + "\n")

s = json.load(open(rc / "v4_adapter_faults" / "summary.json"))
cfgs = [("rmw_w1", "rmw1"), ("rmw_w8", "rmw8"), ("ycsb_w1_theta0.99", "ycsb1"), ("ycsb_w8_theta0.99", "ycsb8")]
lines = ["absent " + " ".join("one_%s two_%s" % (c, c) for _, c in cfgs)]
for pct, key in ((0, None), (10, "missing0.10"), (25, "missing0.25"), (50, "missing0.50")):
    row = []
    for d, _ in cfgs:
        st = s[d]["settings"]
        one = st["L2" if key is None else "L2_" + key]["verdict_rate"]
        two = st["L3" if key is None else "L3_" + key]["verdict_rate"]
        row += ["%.2f" % (100 * one), "%.2f" % (100 * two)]
    lines.append("%d %s" % (pct, " ".join(row)))
(out / "fig_missing.dat").write_text("\n".join(lines) + "\n")
print(open(out / "fig_scale.dat").read())
print(open(out / "fig_missing.dat").read())
