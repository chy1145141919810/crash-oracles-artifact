# Mutation suite v2 (none crash cut): 4800 cells, 2885 non-equivalent, 1915 equivalent

| checker | coverage on non-equivalent % | uncertain on non-equivalent % | false report on equivalent % | uncertain on equivalent % |
| --- | ---: | ---: | ---: | ---: |
| oracle | 93.8 | 6.2 | 0.0 | 4.4 |
| single_log_flat_replay | 100.0 | 0.0 | 0.1 | 0.0 |
| checksum_flat_replay | 100.0 | 0.0 | 20.1 | 0.0 |
| history_acceptor | 93.2 | 0.0 | 0.0 | 0.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 83.2 | 0.0 | 10.0 | 0.0 |
| crash_no_crash_diff | 100.0 | 0.0 | 0.0 | 0.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | 0.0 |

## Coverage on non-equivalent cells by mutation (%; n in header)

| checker | M1 (n=5) | M2 (n=480) | M3 (n=480) | M4 (n=240) | M5 (n=480) | M6 (n=480) | M7 (n=480) | M8 (n=240) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 100.0 | 93.8 | 93.1 | 91.2 | 93.5 | 94.2 | 96.5 | 91.7 |
| single_log_flat_replay | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| checksum_flat_replay | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| history_acceptor | 20.0 | 100.0 | 100.0 | 20.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 0.0 | 100.0 | 80.0 | 80.0 | 100.0 | 100.0 | 80.0 | 0.0 |
| crash_no_crash_diff | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## False report on equivalent cells by mutation (%; n in header)

| checker | M1 (n=475) | M2 (n=0) | M3 (n=0) | M4 (n=240) | M5 (n=0) | M6 (n=0) | M7 (n=0) | M8 (n=240) | M0 (n=480) | M9 (n=480) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 0.0 | n/a | n/a | 0.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
| single_log_flat_replay | 0.4 | n/a | n/a | 0.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
| checksum_flat_replay | 20.4 | n/a | n/a | 20.0 | n/a | n/a | n/a | 20.0 | 20.0 | 20.0 |
| history_acceptor | 0.0 | n/a | n/a | 0.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
| log_sanity_artifacts | 0.0 | n/a | n/a | 0.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 0.0 | n/a | n/a | 80.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
| crash_no_crash_diff | 0.0 | n/a | n/a | 0.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
| writecheck_no_crash | 0.0 | n/a | n/a | 0.0 | n/a | n/a | n/a | 0.0 | 0.0 | 0.0 |
