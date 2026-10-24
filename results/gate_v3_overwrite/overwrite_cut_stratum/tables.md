# Mutation suite v3 (overwrite writes, stratum crash cut): 4800 cells, 2670 non-equivalent, 2130 equivalent

| checker | coverage on non-equivalent % | uncertain on non-equivalent % | false report on equivalent % | uncertain on equivalent % |
| --- | ---: | ---: | ---: | ---: |
| oracle | 91.7 | 8.3 | 0.0 | 12.8 |
| single_log_flat_replay | 100.0 | 0.0 | 46.7 | 0.0 |
| checksum_flat_replay | 100.0 | 0.0 | 84.4 | 0.0 |
| history_acceptor | 75.7 | 0.0 | 0.0 | 0.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 72.1 | 0.0 | 31.3 | 0.0 |
| crash_no_crash_diff | 100.0 | 0.0 | 100.0 | 0.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | 0.0 |

## Coverage on non-equivalent cells by mutation (%; n in header)

| checker | M1 (n=25) | M2 (n=192) | M3 (n=360) | M4 (n=480) | M5 (n=480) | M6 (n=294) | M7 (n=359) | M8 (n=480) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 84.0 | 89.1 | 81.4 | 91.0 | 88.8 | 97.3 | 100.0 | 94.8 |
| single_log_flat_replay | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| checksum_flat_replay | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| history_acceptor | 16.0 | 94.8 | 100.0 | 20.0 | 100.0 | 20.1 | 100.0 | 100.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| log_sanity_trace | 0.0 | 100.0 | 80.0 | 80.0 | 100.0 | 100.0 | 79.9 | 0.0 |
| crash_no_crash_diff | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## False report on equivalent cells by mutation (%; n in header)

| checker | M1 (n=455) | M2 (n=288) | M3 (n=120) | M4 (n=0) | M5 (n=0) | M6 (n=186) | M7 (n=121) | M8 (n=0) | M0 (n=480) | M9 (n=480) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| single_log_flat_replay | 65.1 | 45.8 | 17.5 | n/a | n/a | 11.8 | 14.9 | n/a | 52.7 | 52.7 |
| checksum_flat_replay | 92.1 | 74.3 | 66.7 | n/a | n/a | 73.1 | 65.3 | n/a | 90.6 | 90.6 |
| history_acceptor | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| log_sanity_artifacts | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
| log_sanity_trace | 0.0 | 100.0 | 80.0 | n/a | n/a | 100.0 | 80.2 | n/a | 0.0 | 0.0 |
| crash_no_crash_diff | 100.0 | 100.0 | 100.0 | n/a | n/a | 100.0 | 100.0 | n/a | 100.0 | 100.0 |
| writecheck_no_crash | 0.0 | 0.0 | 0.0 | n/a | n/a | 0.0 | 0.0 | n/a | 0.0 | 0.0 |
