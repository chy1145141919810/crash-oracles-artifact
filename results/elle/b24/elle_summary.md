# Elle (rw-register) on exported client histories, next to our checkers on the same runs

## rmw_w3: 1080 runs (599 buggy, 481 clean)

| checker | recall | false-bug rate | detected | missed | false bugs | no verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 1.000 | 0.000 | 599 | 0 | 0 | 0 |
| single_log_replay | 0.781 | 0.661 | 468 | 131 | 318 | 0 |
| history_acceptor | 0.776 | 0.000 | 465 | 134 | 0 | 0 |
| elle-cli default (strict-serializable) | 0.444 | 0.000 | 266 | 333 | 0 | 0 |
| Elle, wfr-keys | 0.669 | 0.000 | 401 | 198 | 0 | 0 |
| Elle, linearizable-keys | 0.669 | 0.000 | 401 | 198 | 0 | 0 |
| Elle, wfr-keys + linearizable-keys | 0.669 | 0.000 | 401 | 198 | 0 | 0 |

| fault | buggy | oracle | single_log_replay | history_acceptor | elle-cli default (strict-serializable) | Elle, wfr-keys | Elle, linearizable-keys | Elle, wfr-keys + linearizable-keys |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat_order | 131 | 131 | 0 | 0 | 0 | 131 | 131 | 131 |
| ignore_validation | 78 | 78 | 78 | 78 | 0 | 0 | 0 | 0 |
| torn_commit_include | 120 | 120 | 120 | 120 | 0 | 0 | 0 | 0 |
| stale_checkpoint_noreapply | 90 | 90 | 90 | 90 | 90 | 90 | 90 | 90 |
| truncate_suffix | 180 | 180 | 180 | 177 | 176 | 180 | 180 | 180 |

Anomaly types on Elle's reports: {"elle_cli_default": {"": 266, "_histories_without_result": 0}, "elle_wfr": {"[:G-single-item-realtime]": 270, "[:G-single-item]": 131, "_histories_without_result": 0}, "elle_lin": {"[:G-single-item-realtime :cyclic-versions]": 266, "[:G1c]": 86, "[:G0-realtime :G1c]": 22, "[:cyclic-versions]": 11, "[:G1c :strong-PL-1-cycle-exists]": 10, "[:G-single-item :G1c :G1c-realtime :strong-PL-1-cycle-exists]": 6, "_histories_without_result": 0}, "elle_wfr_lin": {"[:G-single-item-realtime :cyclic-versions]": 270, "[:G-single-item :cyclic-versions]": 131, "_histories_without_result": 0}}

## tpcc_n48: 1080 runs (658 buggy, 422 clean)

| checker | recall | false-bug rate | detected | missed | false bugs | no verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 1.000 | 0.000 | 658 | 0 | 0 | 0 |
| single_log_replay | 0.739 | 0.941 | 486 | 172 | 397 | 0 |
| history_acceptor | 0.729 | 0.000 | 480 | 178 | 0 | 0 |
| elle-cli default (strict-serializable) | 0.410 | 0.000 | 270 | 388 | 0 | 0 |
| Elle, wfr-keys | 0.672 | 0.000 | 442 | 216 | 0 | 0 |
| Elle, linearizable-keys | 0.675 | 0.000 | 444 | 214 | 0 | 0 |
| Elle, wfr-keys + linearizable-keys | 0.675 | 0.000 | 444 | 214 | 0 | 0 |

| fault | buggy | oracle | single_log_replay | history_acceptor | elle-cli default (strict-serializable) | Elle, wfr-keys | Elle, linearizable-keys | Elle, wfr-keys + linearizable-keys |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat_order | 172 | 172 | 0 | 0 | 0 | 172 | 172 | 172 |
| ignore_validation | 96 | 96 | 96 | 96 | 0 | 0 | 0 | 0 |
| torn_commit_include | 120 | 120 | 120 | 120 | 0 | 0 | 2 | 2 |
| stale_checkpoint_noreapply | 90 | 90 | 90 | 90 | 90 | 90 | 90 | 90 |
| truncate_suffix | 180 | 180 | 180 | 174 | 180 | 180 | 180 | 180 |

Anomaly types on Elle's reports: {"elle_cli_default": {"": 270, "_histories_without_result": 0}, "elle_wfr": {"[:G-single-item-realtime]": 270, "[:G-single-item]": 172, "_histories_without_result": 0}, "elle_lin": {"[:G-single-item-realtime :cyclic-versions]": 270, "[:G1c]": 49, "[:G1c :PL-1-cycle-exists]": 35, "[:cyclic-versions]": 31, "[:G0-realtime :G1c]": 12, "[:G1c :strong-PL-1-cycle-exists]": 9, "_histories_without_result": 0}, "elle_wfr_lin": {"[:G-single-item-realtime :cyclic-versions]": 269, "[:G-single-item :cyclic-versions]": 172, "[:cyclic-versions]": 2, "[:G1c :cyclic-versions]": 1, "_histories_without_result": 0}}

## ycsb_w3_theta0.99: 1080 runs (627 buggy, 453 clean)

| checker | recall | false-bug rate | detected | missed | false bugs | no verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 1.000 | 0.000 | 627 | 0 | 0 | 0 |
| single_log_replay | 0.766 | 0.753 | 480 | 147 | 341 | 0 |
| history_acceptor | 0.703 | 0.000 | 441 | 186 | 0 | 0 |
| elle-cli default (strict-serializable) | 0.360 | 0.000 | 226 | 401 | 0 | 0 |
| Elle, wfr-keys | 0.466 | 0.000 | 292 | 335 | 0 | 0 |
| Elle, linearizable-keys | 0.632 | 0.000 | 396 | 231 | 0 | 0 |
| Elle, wfr-keys + linearizable-keys | 0.632 | 0.000 | 396 | 231 | 0 | 0 |

| fault | buggy | oracle | single_log_replay | history_acceptor | elle-cli default (strict-serializable) | Elle, wfr-keys | Elle, linearizable-keys | Elle, wfr-keys + linearizable-keys |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| flat_order | 147 | 147 | 0 | 0 | 0 | 60 | 130 | 130 |
| ignore_validation | 90 | 90 | 90 | 90 | 0 | 0 | 0 | 0 |
| torn_commit_include | 120 | 120 | 120 | 120 | 0 | 0 | 0 | 0 |
| stale_checkpoint_noreapply | 90 | 90 | 90 | 90 | 90 | 90 | 90 | 90 |
| truncate_suffix | 180 | 180 | 180 | 141 | 136 | 142 | 176 | 176 |

Anomaly types on Elle's reports: {"elle_cli_default": {"": 226, "_histories_without_result": 0}, "elle_wfr": {"[:G-single-item-realtime]": 236, "[:G-single-item]": 52, "[:G-single-item-realtime :G2-item]": 4, "_histories_without_result": 0}, "elle_lin": {"[:G-single-item-realtime :cyclic-versions]": 226, "[:cyclic-versions]": 138, "[:G-single-item :G1c]": 15, "[:G-single-item]": 8, "[:G-nonadjacent-item-realtime :G1c :G2-item]": 3, "[:G1c]": 3, "_histories_without_result": 0}, "elle_wfr_lin": {"[:G-single-item-realtime :cyclic-versions]": 236, "[:cyclic-versions]": 88, "[:G-single-item :cyclic-versions]": 52, "[:G-single-item]": 8, "[:G-single-item-realtime :G2-item :cyclic-versions]": 4, "[:G-single-item :G1c]": 3, "_histories_without_result": 0}}

