# Where each number in `manuscript_vldb/main.tex` comes from

Same evidence as the CIDR-class revision; the mapping below is that revision's, and its table numbers refer to `manuscript/main.tex`. In this folder the tables are identified by label:

| Label in `main.tex` | Content | Source (relative to `experiments/rev_20261007/`) |
| --- | --- | --- |
| `tab:example` | running example | illustrative, no measured numbers |
| `tab:prototype` | in-memory model, all 16 configurations, with replay-order bug counts | `rerun_check/v3_multikey/grid_summary.json` (`cross_mode_order_bugs`, recall and false-bug columns) |
| `tab:disk` | on-disk model | `rerun_check/v5_disk_kill/summary.md` |
| `tab:mutants` | mutated recovery, per checker | `rerun_check/mutation_recovery/metrics_mutation.json` |
| `tab:operators` | mutants by operator | same file, `by_operator` (condition forced and filter dropped are both operator `if`; integer and mode-string constants are both `const`) |
| `tab:metadata` | imperfect order evidence, ranges | `rerun_check/v4_adapter_faults/summary.md` |
| `tab:metadata-config` | the same per configuration | `rerun_check/v4_adapter_faults/summary.md`, rows L2_missing0.10, L3_missing0.10, L2_stale0.25, L3_stale0.25, L3_swapocc0.25, L3_ckpt_extra |
| `fig:missing` | verdict share against absent frontiers | `manuscript_vldb/figures/fig_missing.dat`, written by `figures/make_figure_data.py` from `rerun_check/v4_adapter_faults/summary.json` |
| `tab:scale` | scale and timing | `rerun_check/scale_study/summary.md` |
| `fig:scale` | check and replay time against run size | `manuscript_vldb/figures/fig_scale.dat`, written by the same script from `rerun_check/scale_study/*/timing_scale.json` |
| `tab:witness` | minimized witnesses | `rerun_check/witness_min_serial/summary.json` |
| `tab:mutations`, `tab:constructed` | constructed suite | `rerun_check/gate_v2/v2_cut_stratum/`, `rerun_check/gate_v3_overwrite/overwrite_cut_stratum/` |

The figure data were generated on the server copy of `rerun_check/` (identical files; hashes in the `rerun_check*_SHA256SUMS.txt` lists).

---
# Where each number in `main.tex` comes from (revision of 2026-10-08)

All paths are relative to `experiments/rev_20261007/`. Machine, commands and hashes are in that folder's `MANIFEST.md`. No number comes from the imported `experiments/metrics*.json`, `cell_results.csv` or `write_outcome_paper_level.py`.

| Manuscript item | Source file(s) | Notes |
| --- | --- | --- |
| Abstract: "up to 8.7% wrong verdicts" | `rerun_check/v4_adapter_faults/summary.md` | L2_stale0.25, ycsb_w8_theta0.99: 8.72% |
| Abstract and Sec. 4.7: "median of one to three transactions" | `rerun_check/witness_min_serial/summary.json` | per-fault medians 1, 1, 1, 2, 2-3 |
| Sec. 3 prototype: 48 / 500 / 5,000 transactions, row counts | `scripts/real_recovery_prototype_v3.py`, `scripts/scale_study.py` | |
| Sec. 3 crash models: eight injection points | `scripts/real_recovery_prototype_v5.py` | steps 1-8 in the module docstring |
| Table 2 (in-memory, complete evidence) | `rerun_check/v3_multikey/grid_summary.json` | rows rmw_w{1,3,5,8}, ycsb_w{1,3,5,8}_theta0.99 |
| Sec. 4.2: 69,120 verdicts equal | `rerun_check/v4_adapter_faults/*/metrics_v4.json` → `regression_vs_v3` | 8 x 8,640, `L3_equals_v3_full` and `L2_equals_v3_full` |
| Sec. 4.2: order bugs 228-1,437; truncation 1,398-1,440 and 880-1,433; 321 / 403; flat replay 12.9%-45.3% and 67.4%-99.8%; history 0.920-0.705 | `rerun_check/v3_multikey/grid_extra.json`, `grid_summary.json` | ranges over all 16 configurations |
| Sec. 4.2: bootstrap 0.076 [0.063, 0.088] | `rerun_check/v3_multikey/rmw_w1/metrics_real_recovery.json` | identical to `rerun_check/full_seeds40` |
| Sec. 4.2 no-crash differential: 0/2,052; 1,199/1,199; 1,157/1,157 | `rerun_check/v3_multikey/grid_extra.json` (rmw_w1), `rerun_check/v2_nocrash_fix/breakdown.json` | |
| Table 3 and Sec. 4.3 (on-disk) | `rerun_check/v5_disk_kill/summary.md`, `*/metrics_v5.json` | 1,920 processes, 264-272 torn tails, 420-1,764 order bugs, 15,360 directories |
| Table 4 and Sec. 4.4 (mutants) | `rerun_check/mutation_recovery/metrics_mutation.json`, `mutants.json` | 41 mutants; 24 / 9 / 8; 41,234 and 31,126 pairs |
| Table 5 and Sec. 4.5 (metadata) | `rerun_check/v4_adapter_faults/summary.md`, `summary.json` | ranges over eight configurations; "7 missed and 332 false" is L2_stale0.25, ycsb_w8_theta0.99 |
| Sec. 4.5: 69.9% / 75.6%; at least 99.1% | `rerun_check/v3_multikey/grid_extra.json` | equal to v4 level L0 (`L0_equals_v3_hidden` = 8,640 in every configuration) |
| Table 6 and Sec. 4.6 (scale, timing) | `rerun_check/scale_study/summary.md`, `*/metrics_scale.json`, `*/timing_scale.json` | 138,240 = 8 x 17,280 (`v4_equivalence`); keyspace 27,804; ratios computed from the table |
| Table 7 and Sec. 4.7 (witnesses) | `rerun_check/witness_min_serial/summary.json`, `*/metrics_witness.json`, `*/witnesses.csv` | serial run; witness rows identical to the parallel run in `rerun_check/witness_min/` except time |
| Table 8 (mutation counts) | `rerun_check/gate_v2/v2_cut_stratum/metrics.json` (additive), `rerun_check/gate_v3_overwrite/overwrite_cut_stratum/metrics.json` (overwrite) | `by_mutation.*.n_non_equivalent` |
| Table 9 and Sec. 4.8 (constructed suite) | same two files, plus their `tables.md` and `cell_results.csv` | 597, 222 and the per-encoding abstention rates are computed from `cell_results.csv` (see CHANGELOG entry of 2026-10-07 for the commands' output) |
| Discussion: "median of one to three transactions in tens of milliseconds" | `rerun_check/witness_min_serial/summary.json` | per-fault median times 5.6-78 ms |
| Limitations: 41 mutants of a 25-line procedure | `scripts/mutate_recovery.py` (`RECOVERY_SRC`) | |

Not in the manuscript although measured: the eight v3 configurations at theta 0 and 0.6 as table rows; the v4 timing fields; the v5 det-order-only oracle; the `--crash-cut none` mutation-suite runs; per-configuration witness shapes.

## Added 2026-10-10 (paths relative to `experiments/rev_20261010/`)

| Label or passage in `main.tex` | Source |
| --- | --- |
| `tab:tpcc`, Sec. 5.4 text (mix, 24-25 writes, 19% aborts, timing) | `rerun_check/tpcc/summary_tpcc.md`, `tpcc_n48/` and `tpcc_n500/` `metrics_tpcc.json` and `timing_tpcc.json`, `disk_n48/` and `disk_n500/` `metrics_tpcc_disk.json` |
| "High-conflict workloads" paragraph (metadata faults on TPC-C-style) | `rerun_check/tpcc/tpcc_n48/metrics_tpcc.json` and `tpcc_n500/metrics_tpcc.json`, key `metadata` |
| `tab:elle`, strict rows | `rerun_check/elle/b1/elle_summary.json`; same values in `rerun_check/contract/*.json` under `strict` |
| `tab:elle`, lenient rows; 120 label changes; 96 / 78 / 90 runs without validation marker | `rerun_check/contract/{tpcc_n48,rmw_w3,ycsb_w3_theta0.99}.json` (`lenient`, `label_changes_by_fault`, `per_fault.ignore_validation`) |
| Replay-order counts for Elle (172 / 131 / 147; 60 of 147 with wfr-keys only) | `rerun_check/elle/b1/elle_summary.json`, `per_fault_detected.flat_order` |
| Real-time overlap (134 and 130 of 147; 24 of 453) | `rerun_check/elle/b8/elle_summary.json`, `rerun_check/elle/b24/elle_summary.json` |
| "What public engine artifacts persist" | `ENGINE_ARTIFACT_INSPECTION.md` (file and line references into the two repositories) |
| Tool versions (Elle 0.2.7, elle-cli 0.1.11) | `MANIFEST.md`, Elle addendum |
