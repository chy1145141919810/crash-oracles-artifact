# Durable-Prefix Write-Outcome Oracles: artifact

Scripts and result files for the paper *Durable-Prefix Write-Outcome Oracles for Hybrid Deterministic and Optimistic Transaction Engines*.

Everything here is a Python prototype written for the paper. It is not a storage engine and contains no third-party engine. See "Scope and limits" before drawing conclusions from it.

## Contents

| Path | What it is |
| --- | --- |
| `scripts/` | All programs: the recovery prototype (v2-v5), workloads, checkers, the experiments built on them, the Elle export and scoring, and the figure-data generator. |
| `results/` | The result files the paper's tables and figures are drawn from: metrics, summaries, and run-level CSV files where they are small. |
| `PAPER_MAP.md` | Map from each table, figure and section of the submitted paper to the result files it comes from. |
| `NUMBERS_SOURCE_paper.md` | Older, finer-grained map kept for reference; its table numbers refer to an earlier draft. |
| `ENGINE_ARTIFACT_INSPECTION.md` | Notes, with file and line references, on why the oracle could not be attached to the public HDCC and Aria artifacts. |

## Requirements

- Python 3.10 or later, standard library only. The reported runs used CPython 3.12.8 on Linux (Intel Xeon Gold 6442Y); the in-memory TPC-C-style grids were also run with CPython 3.10.9 on Windows and gave byte-identical run-level output.
- The on-disk experiments (`real_recovery_prototype_v5.py`, `tpcc_disk.py`) need a POSIX system, because the engine process kills itself with `SIGKILL`.
- Elle comparison only: Java 21 or later and elle-cli 0.1.11 (bundles Elle 0.2.7), built from https://github.com/ligurio/elle-cli at commit `9c2a18b` with `lein uberjar`.

## Datasets

The YCSB-A-style, read-modify-write and mutation-suite experiments draw row keys and initial values from three public sources. They are not redistributed here. Download them and point the environment variables at them:

| Variable | Source |
| --- | --- |
| `RESEARCHOS_DATASET_CHINOOK_SQLITE` | `Chinook_Sqlite.sqlite` from https://github.com/lerocha/chinook-database |
| `RESEARCHOS_DATASET_NORTHWIND_SQLITE` | `northwind.db` from https://github.com/jpwhite3/northwind-SQLite3 |
| `RESEARCHOS_DATASET_JOB_QUERIES` | directory with the `.sql` files of https://github.com/gregrahn/join-order-benchmark (mutation suite only) |

The TPC-C-style experiments generate their own data and need none of these.

## Reproducing the experiments

Run from the repository root. Each command writes a metrics JSON (and usually a run-level CSV) into the `--out` directory; compare with the matching folder under `results/`. All programs are deterministic, so counts and rates should match exactly; timings will not.

```bash
S=scripts

# In-memory prototype, 16 configurations (paper: detection with complete order evidence)
for w in 1 3 5 8; do
  python3 $S/real_recovery_prototype_v3.py --writes-per-txn $w --workload rmw --out out/v3_multikey/rmw_w$w
  for t in 0.0 0.6 0.99; do
    python3 $S/real_recovery_prototype_v3.py --writes-per-txn $w --workload ycsb --theta $t --out out/v3_multikey/ycsb_w${w}_theta$t
  done
done
python3 $S/summarize_v3_grid.py out/v3_multikey
python3 $S/analyze_v3_grid_extra.py out/v3_multikey

# Missing and wrong order evidence (v4), per configuration
python3 $S/real_recovery_prototype_v4.py --writes-per-txn 8 --workload ycsb --theta 0.99 --out out/v4_adapter_faults/ycsb_w8_theta0.99

# On-disk logs and process kills (v5), per configuration (POSIX)
python3 $S/real_recovery_prototype_v5.py run --jobs 8 --writes-per-txn 1 --workload rmw --out out/v5_disk_kill/rmw_w1

# TPC-C-style workload: in memory, on disk, serial timing
python3 $S/tpcc_study.py grid --n 48  --jobs 8 --out out/tpcc/tpcc_n48
python3 $S/tpcc_study.py grid --n 500 --jobs 8 --out out/tpcc/tpcc_n500
python3 $S/tpcc_disk.py  run  --n 48  --jobs 8 --out out/tpcc/disk_n48
python3 $S/tpcc_study.py timing --n 48 --out out/tpcc/tpcc_n48
python3 $S/summarize_tpcc.py out/tpcc

# Mechanically mutated recovery code
python3 $S/mutate_recovery.py --out out/mutation_recovery

# Scale study: correctness grid and serial timing for one cell
python3 $S/scale_study.py grid   --n 5000 --keys 40000 --seeds 40 --jobs 8 --writes-per-txn 8 --workload rmw --out out/scale_study/n5000_rmw_w8
python3 $S/scale_study.py timing --n 5000 --keys 40000 --writes-per-txn 8 --workload rmw --out out/scale_study/n5000_rmw_w8

# Witness minimization, per configuration
python3 $S/witness_minimize.py --writes-per-txn 3 --workload rmw --out out/witness_min/rmw_w3

# Constructed mutation suite, additive and overwrite writes
python3 $S/write_outcome_mutation_suite_v2.py --crash-cut stratum --out out/gate_v2/v2_cut_stratum
python3 $S/write_outcome_mutation_suite_v3.py --write-model overwrite --crash-cut stratum --out out/gate_v3_overwrite/overwrite_cut_stratum

# Elle comparison: export histories, run Elle, score; then both in-doubt contracts
python3 $S/elle_histories.py --workload tpcc --seeds 5 --out out/elle/tpcc_n48
#   run elle-cli and scripts/elle_check.clj over out/elle/*/h/*.edn (see scripts/run_elle.ps1 for the exact invocations)
python3 $S/score_elle.py out/elle
python3 $S/contract_modes.py --workload tpcc --elle-dir out/elle/tpcc_n48 --out out/contract_tpcc_n48.json

# Data files for the two plots
python3 $S/make_figure_data.py results out/figures
```

Full grids take seconds to a few minutes each on a 24-core machine; the 500-transaction TPC-C-style grid took about 19 minutes on an 8-core laptop.

## What is in `results/`, and where it appears in the paper

Numbering follows the submitted paper (PVLDB Vol. 20, submission 2342). `PAPER_MAP.md` lists the individual files.

| Folder | Experiment | In the paper |
| --- | --- | --- |
| `v3_multikey/`, `v3_serial_timing/` | in-memory prototype, 16 configurations | Table 2 (in-memory row), Table 3, Section 5.2 |
| `v2_nocrash_fix/` | crash/no-crash differential by crash cut; oracle cross-check | Section 5.2 |
| `v5_disk_kill/` | on-disk logs, engine process killed | Table 2 (on-disk row), Section 5.3 |
| `tpcc/` | TPC-C-style workload, in memory and on disk, with timing | Table 2 (TPC-C-style row), Section 5.4 |
| `mutation_recovery/` | mutated recovery code | Table 2 (mutated-code row), Section 5.5 |
| `v4_adapter_faults/` | missing, stale, unrelated and swapped order evidence; overstated checkpoint certificate | Table 2 (bottom), Table 4, Figure 2, Section 5.6 |
| `elle/b1`, `elle/b8`, `elle/b24`, `contract/` | Elle verdicts and scores; strict and lenient contracts; real-time overlap | Table 5, Section 5.7 |
| `scale_study/` | 48 / 500 / 5,000 transactions per run, with serial timing | Table 2 (5,000-transaction row), Figure 3, Section 5.8 |
| `witness_min_serial/` | witness minimization | Table 6, Section 5.9 |
| `gate_v2/`, `gate_v3_overwrite/` | constructed mutation suite, additive and overwrite writes | Tables 7 and 8, Section 5.10 |

Not included because of size: the per-run CSV files of the prototype configurations (about 110 MB) and the exported Elle histories (about 350 MB). Both are regenerated by the commands above.

Two edits were made for publication and do not affect any result: dataset locations inside `results/gate_*/**/metrics.json` are shown as `<DATASETS>/...`, and an unused fallback dataset path was removed from `real_recovery_prototype_v2.py` and `real_recovery_prototype_v3.py`.

## Scope and limits

- Both the engine and the checkers are Python models. The engine is single-threaded and logs commits in commit order. The in-memory crash model truncates a record list; the on-disk model kills a real process at eight fixed injection points and reads real files, but it is a process-kill model and does not lose unsynced data.
- Wherever the oracle scores recall 1.000 and false-bug rate 0.000 (100.0 and 0 in the paper, which prints rates as percentages), the order metadata was exact. Those results show that the reference construction and its implementation are right when the evidence is complete and correct. `results/v4_adapter_faults/` shows what happens when it is not.
- "YCSB-A-style" and "TPC-C-style" follow the operation mix and structure of those benchmarks at small scale. They are not YCSB or TPC-C results.
- The recovery faults are five hand-written variants and 41 syntactic mutants of a 25-line recovery procedure. No field bugs were found or sought.
- No third-party engine is evaluated; see `ENGINE_ARTIFACT_INSPECTION.md`.

## License

MIT; see `LICENSE`.
