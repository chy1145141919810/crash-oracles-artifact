# Where each result in the paper comes from

Numbering follows the submitted version of the paper (PVLDB Vol. 20 submission 2342). All paths are relative to `results/`.

| Paper | What it shows | Result files |
| --- | --- | --- |
| Table 2, top, "In memory" row; Table 3; Sections 5.2 text | in-memory prototype, 16 configurations, complete order evidence | `v3_multikey/grid_summary.json`, `v3_multikey/grid_extra.json`, `v3_multikey/*/metrics_real_recovery.json`; cross-check of the two oracle implementations in `v2_nocrash_fix/` |
| Section 5.2, no-crash differential | crash/no-crash differential by crash cut | `v2_nocrash_fix/breakdown.json` |
| Table 2, "On disk" row; Section 5.3 | on-disk logs, engine killed by SIGKILL | `v5_disk_kill/summary.md`, `v5_disk_kill/*/metrics_v5.json` |
| Table 2, "TPC-C-style" row; Section 5.4 | TPC-C-style workload, in memory (48, 500 txns) and on disk (48 txns, 40 seeds; 500 txns, 10 seeds) | `tpcc/summary_tpcc.md`, `tpcc/*/metrics_tpcc*.json`, `tpcc/*/timing_tpcc.json` |
| Table 2, "Mutated recovery code" row; Section 5.5 | 41 mutants x 2,160 scenarios; 41,234 wrong-state, 31,126 correct and 16,200 raising pairs | `mutation_recovery/metrics_mutation.json`, `mutation_recovery/mutants.json` |
| Table 2, bottom; Table 4; Figure 2; Section 5.6 | the oracle under missing, stale, unrelated or swapped order evidence and an overstated checkpoint certificate | `v4_adapter_faults/summary.json`, `v4_adapter_faults/summary.md` |
| Table 5; Section 5.7 | Elle versus the oracle, strict and lenient contracts, real-time overlap | `elle/b1`, `elle/b8`, `elle/b24`, `contract/*.json` |
| Table 2, "5,000 transactions" row; Figure 3; Section 5.8 | scale study at 48, 500 and 5,000 transactions; timing | `scale_study/summary.md`, `scale_study/*/metrics_scale.json`, `scale_study/*/timing_scale.json` |
| Table 6; Section 5.9 | minimized witnesses | `witness_min_serial/summary.json`, `witness_min_serial/*/metrics_witness.json` |
| Tables 7 and 8; Section 5.10 | constructed mutation suite, additive and overwrite write models | `gate_v2/*/metrics.json`, `gate_v3_overwrite/*/metrics.json` and the `tables.md` next to them |

Figure data files are produced by `scripts/make_figure_data.py results OUT_DIR` (`fig_missing.dat` and `fig_stale.dat` for Figure 2, `fig_scale.dat` for Figure 3).

Table 2 aggregates per-configuration results: its Runs, Buggy and "Replay-order bugs" columns are sums over the rows of the files above. "Replay-order bugs" (called "Oracle only" in earlier drafts) counts the buggy runs of the cross-mode replay-order fault: `cross_mode_order_bugs` in `v3_multikey/grid_summary.json` (sum 17,449), and the flat-order / order-bug columns of `v5_disk_kill/summary.md`, `tpcc/summary_tpcc.md` and `scale_study/summary.md`. The oracle detects all of these runs and neither baseline any (`xmo_*_recall`). The fields `oracle_only_vs_single_log` and `oracle_only_vs_history` in `v3_multikey/grid_extra.json` are different counts: buggy runs of any fault detected by the oracle and missed by one given baseline (Section 5.2 text, 321 and 403), and its recall and false-bug ranges are minima and maxima over the same rows.

The result files store rates as proportions (for example `0.732`); Tables 2, 3 and 5 of the paper print the same values as percentages (`73.2`).
