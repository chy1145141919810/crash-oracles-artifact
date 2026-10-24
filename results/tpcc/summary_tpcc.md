# TPC-C-style workload: results

## 48 transactions per run

8640 runs (5166 buggy, 3474 clean); correct recovery differs from ground truth in 0 runs.
Mean committed per run 43.2; mean writes per committed transaction 24.4; OCC abort rate 0.192; committed by type {"delivery": 658, "new_order": 10364, "payment": 9696}; OCC aborts by type {"delivery": 138, "new_order": 820, "payment": 1242}; initial keys {"1": 1831, "4": 7324}.

| checker | recall | false-bug rate | missed | false bugs | abstain buggy | abstain clean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| history_acceptor | 0.726 | 0.000 | 1416 | 0 | 0.000 | 0.000 |
| oracle | 1.000 | 0.000 | 0 | 0 | 0.000 | 0.000 |
| single_log_replay | 0.734 | 0.946 | 1376 | 3287 | 0.000 | 0.000 |

By warehouses (recall / false-bug rate): W=1: history_acceptor 0.723/0.000, oracle 1.000/0.000, single_log_replay 0.734/0.937; W=4: history_acceptor 0.729/0.000, oracle 1.000/0.000, single_log_replay 0.734/0.956

| fault | buggy runs | oracle | single-log | history |
| --- | ---: | ---: | ---: | ---: |
| clean | 0 | 0 | 0 | 0 |
| flat_order | 1376 | 1376 | 0 | 0 |
| ignore_validation | 670 | 670 | 670 | 670 |
| stale_checkpoint_noreapply | 720 | 720 | 720 | 720 |
| torn_commit_include | 960 | 960 | 960 | 960 |
| truncate_suffix | 1440 | 1440 | 1440 | 1400 |

| adapter setting | runs with verdict % | wrong among verdicts % | missed bugs | false bugs |
| --- | ---: | ---: | ---: | ---: |
| L0 | 0.4 | 0.00 | 0 | 0 |
| L1 | 0.4 | 0.00 | 0 | 0 |
| L2 | 100.0 | 0.00 | 0 | 0 |
| L2_missing0.10 | 69.4 | 0.00 | 0 | 0 |
| L2_missing0.25 | 37.6 | 0.00 | 0 | 0 |
| L2_missing0.50 | 14.7 | 0.00 | 0 | 0 |
| L2_stale0.05 | 68.1 | 0.78 | 1 | 45 |
| L2_stale0.25 | 27.6 | 5.65 | 4 | 131 |
| L2_wrong0.05 | 57.0 | 0.65 | 0 | 32 |
| L2_wrong0.25 | 12.4 | 4.66 | 0 | 50 |
| L3 | 100.0 | 0.00 | 0 | 0 |
| L3_ckpt_extra | 100.0 | 16.16 | 0 | 1396 |
| L3_missing0.10 | 97.8 | 0.00 | 0 | 0 |
| L3_missing0.25 | 83.5 | 0.00 | 0 | 0 |
| L3_missing0.50 | 44.9 | 0.00 | 0 | 0 |
| L3_stale0.05 | 53.3 | 0.00 | 0 | 0 |
| L3_stale0.25 | 8.8 | 0.00 | 0 | 0 |
| L3_swapocc0.05 | 69.9 | 0.73 | 0 | 44 |
| L3_swapocc0.25 | 21.4 | 3.73 | 0 | 69 |
| L3_wrong0.05 | 51.9 | 0.00 | 0 | 0 |
| L3_wrong0.25 | 8.3 | 0.00 | 0 | 0 |

Serial timing, 216 checks x 5 repeats: oracle check 0.366 +- 0.005 ms (p95 0.564); correct replay 0.050 +- 0.000 ms.

## 500 transactions per run

8640 runs (5250 buggy, 3390 clean); correct recovery differs from ground truth in 0 runs.
Mean committed per run 451.4; mean writes per committed transaction 25.2; OCC abort rate 0.194; committed by type {"delivery": 8086, "new_order": 108510, "payment": 100098}; OCC aborts by type {"delivery": 1278, "new_order": 9144, "payment": 12750}; initial keys {"1": 1831, "4": 7324}.

| checker | recall | false-bug rate | missed | false bugs | abstain buggy | abstain clean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| history_acceptor | 0.593 | 0.000 | 2138 | 0 | 0.000 | 0.000 |
| oracle | 1.000 | 0.000 | 0 | 0 | 0.000 | 0.000 |
| single_log_replay | 0.726 | 1.000 | 1440 | 3390 | 0.000 | 0.000 |

By warehouses (recall / false-bug rate): W=1: history_acceptor 0.529/0.000, oracle 1.000/0.000, single_log_replay 0.723/1.000; W=4: history_acceptor 0.655/0.000, oracle 1.000/0.000, single_log_replay 0.728/1.000

| fault | buggy runs | oracle | single-log | history |
| --- | ---: | ---: | ---: | ---: |
| clean | 0 | 0 | 0 | 0 |
| flat_order | 1440 | 1440 | 0 | 0 |
| ignore_validation | 690 | 690 | 690 | 690 |
| stale_checkpoint_noreapply | 720 | 720 | 720 | 720 |
| torn_commit_include | 960 | 960 | 960 | 960 |
| truncate_suffix | 1440 | 1440 | 1440 | 742 |

| adapter setting | runs with verdict % | wrong among verdicts % | missed bugs | false bugs |
| --- | ---: | ---: | ---: | ---: |
| L0 | 0.0 | 0.00 | 0 | 0 |
| L1 | 0.0 | 0.00 | 0 | 0 |
| L2 | 100.0 | 0.00 | 0 | 0 |
| L2_missing0.10 | 5.4 | 0.00 | 0 | 0 |
| L2_missing0.25 | 0.1 | 0.00 | 0 | 0 |
| L2_missing0.50 | 0.0 | 0.00 | 0 | 0 |
| L2_stale0.05 | 10.3 | 1.58 | 0 | 14 |
| L2_stale0.25 | 0.1 | 0.00 | 0 | 0 |
| L2_wrong0.05 | 0.7 | 0.00 | 0 | 0 |
| L2_wrong0.25 | 0.0 | 0.00 | 0 | 0 |
| L3 | 100.0 | 0.00 | 0 | 0 |
| L3_ckpt_extra | 100.0 | 15.45 | 0 | 1335 |
| L3_missing0.10 | 76.5 | 0.00 | 0 | 0 |
| L3_missing0.25 | 22.8 | 0.00 | 0 | 0 |
| L3_missing0.50 | 0.4 | 0.00 | 0 | 0 |
| L3_stale0.05 | 1.3 | 0.00 | 0 | 0 |
| L3_stale0.25 | 0.0 | 0.00 | 0 | 0 |
| L3_swapocc0.05 | 3.3 | 0.35 | 0 | 1 |
| L3_swapocc0.25 | 0.0 | 0.00 | 0 | 0 |
| L3_wrong0.05 | 1.2 | 0.00 | 0 | 0 |
| L3_wrong0.25 | 0.0 | 0.00 | 0 | 0 |

Serial timing, 216 checks x 5 repeats: oracle check 5.933 +- 0.060 ms (p95 12.638); correct replay 0.486 +- 0.001 ms.

