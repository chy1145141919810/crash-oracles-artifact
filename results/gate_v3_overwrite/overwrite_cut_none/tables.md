# Mutation suite v3 (overwrite writes, none crash cut): 4800 cells, 2680 non-equivalent, 2120 equivalent

| checker | coverage on non-equivalent % | uncertain on non-equivalent % | false report on equivalent % | uncertain on equivalent % |
| --- | ---: | ---: | ---: | ---: |
| oracle | 90.9 | 9.1 | 0.0 | 13.5 |
| single_log_flat_replay | 100.0 | 0.0 | 51.4 | 0.0 |
| checksum_flat_replay | 100.0 | 0.0 | 60.3 | 0.0 |
| history_acceptor | 75.1 | 0.0 | 0.0 | 0.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 72.3 | 0.0 | 30.8 | 0.0 |
| crash_no_crash_diff | 100.0 | 0.0 | 0.0 | 0.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | 0.0 |

## Coverage on non-equivalent cells by mutation (%; n in header)

| checker | M1 (n=23) | M2 (n=192) | M3 (n=360) | M4 (n=480) | M5 (n=480) | M6 (n=310) | M7 (n=355) | M8 (n=480) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 82.6 | 87.5 | 79.4 | 90.0 | 88.1 | 96.5 | 100.0 | 94.8 |
| single_log_flat_replay | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| checksum_flat_replay | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| history_acceptor | 13.0 | 92.7 | 100.0 | 20.0 | 100.0 | 20.0 | 100.0 | 100.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 0.0 | 100.0 | 80.0 | 80.0 | 100.0 | 100.0 | 80.0 | 0.0 |
| crash_no_crash_diff | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## False report on equivalent cells by mutation (%; n in header)

| checker | M1 (n=457) | M2 (n=288) | M3 (n=120) | M4 (n=0) | M5 (n=0) | M6 (n=170) | M7 (n=125) | M8 (n=0) | M0 (n=480) | M9 (n=480) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| single_log_flat_replay | 67.6 | 49.3 | 20.8 | n/a | n/a | 12.9 | 19.2 | n/a | 59.2 | 59.2 |
| checksum_flat_replay | 74.6 | 49.3 | 36.7 | n/a | n/a | 30.6 | 34.4 | n/a | 68.3 | 68.3 |
| history_acceptor | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| log_sanity_trace | 0.0 | 100.0 | 80.0 | n/a | n/a | 100.0 | 80.0 | n/a | 0.0 | 0.0 |
| crash_no_crash_diff | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
