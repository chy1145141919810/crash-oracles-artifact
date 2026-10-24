# v5: on-disk logs, engine process killed by SIGKILL at injection points

| config | engine procs | killed | torn-tail dirs | recovery runs | buggy | clean | correct recovery != truth | oracle R/F | history R/F | single-log R/F | det-order-only oracle: abstain buggy/clean %, wrong | flat-order bugs: oracle/single/history of n |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| rmw_w1 | 1914 | 1434 | 271 | 11520 | 3640 | 7880 | 0 | 1.000/0.000 | 0.841/0.000 | 0.883/0.192 | 71.6/75.9, 0 | 420/0/0 of 420 |
| rmw_w3 | 1918 | 1438 | 272 | 11520 | 4493 | 7027 | 0 | 1.000/0.000 | 0.708/0.000 | 0.716/0.606 | 97.9/94.7, 0 | 1276/0/0 of 1276 |
| rmw_w5 | 1916 | 1436 | 269 | 11520 | 4821 | 6699 | 0 | 1.000/0.000 | 0.665/0.000 | 0.667/0.787 | 99.1/95.8, 0 | 1604/0/0 of 1604 |
| rmw_w8 | 1918 | 1438 | 268 | 11520 | 4980 | 6540 | 0 | 1.000/0.000 | 0.644/0.000 | 0.646/0.888 | 99.3/95.8, 0 | 1764/0/0 of 1764 |
| ycsb_w1_theta0.99 | 1916 | 1436 | 269 | 11520 | 4146 | 7374 | 0 | 1.000/0.000 | 0.603/0.000 | 0.761/0.417 | 96.3/91.9, 0 | 925/0/0 of 925 |
| ycsb_w3_theta0.99 | 1917 | 1437 | 272 | 11520 | 4761 | 6759 | 0 | 1.000/0.000 | 0.610/0.000 | 0.674/0.758 | 98.9/95.3, 0 | 1549/0/0 of 1549 |
| ycsb_w5_theta0.99 | 1916 | 1436 | 264 | 11520 | 4941 | 6579 | 0 | 1.000/0.000 | 0.627/0.000 | 0.653/0.859 | 99.0/95.2, 0 | 1712/0/0 of 1712 |
| ycsb_w8_theta0.99 | 1917 | 1437 | 272 | 11520 | 4957 | 6563 | 0 | 1.000/0.000 | 0.636/0.000 | 0.649/0.877 | 99.0/95.0, 0 | 1742/0/0 of 1742 |

Per-fault buggy counts and detections (oracle/single-log/history):
- rmw_w1: flat_order 420 (420/0/0); ignore_validation 127 (127/127/127); stale_checkpoint_noreapply 809 (809/809/809); torn_commit_include 399 (399/399/399); truncate_suffix 1885 (1885/1878/1726)
- rmw_w3: flat_order 1276 (1276/0/0); ignore_validation 132 (132/132/132); stale_checkpoint_noreapply 809 (809/809/809); torn_commit_include 391 (391/391/391); truncate_suffix 1885 (1885/1884/1849)
- rmw_w5: flat_order 1604 (1604/0/0); ignore_validation 111 (111/111/111); stale_checkpoint_noreapply 809 (809/809/809); torn_commit_include 412 (412/412/412); truncate_suffix 1885 (1885/1885/1874)
- rmw_w8: flat_order 1764 (1764/0/0); ignore_validation 112 (112/112/112); stale_checkpoint_noreapply 809 (809/809/809); torn_commit_include 410 (410/410/410); truncate_suffix 1885 (1885/1885/1877)
- ycsb_w1_theta0.99: flat_order 925 (925/0/0); ignore_validation 125 (125/125/125); stale_checkpoint_noreapply 809 (809/809/809); torn_commit_include 402 (402/402/402); truncate_suffix 1885 (1885/1820/1166)
- ycsb_w3_theta0.99: flat_order 1549 (1549/0/0); ignore_validation 103 (103/103/103); stale_checkpoint_noreapply 808 (808/808/808); torn_commit_include 416 (416/416/416); truncate_suffix 1885 (1885/1880/1578)
- ycsb_w5_theta0.99: flat_order 1712 (1712/0/0); ignore_validation 107 (107/107/107); stale_checkpoint_noreapply 803 (803/803/803); torn_commit_include 435 (435/435/435); truncate_suffix 1884 (1884/1883/1754)
- ycsb_w8_theta0.99: flat_order 1742 (1742/0/0); ignore_validation 91 (91/91/91); stale_checkpoint_noreapply 802 (802/802/802); torn_commit_include 437 (437/437/437); truncate_suffix 1885 (1885/1885/1822)

Crash steps: {"rmw_w1": {"0": 480, "1": 271, "2": 242, "3": 282, "4": 233, "5": 284, "6": 52, "7": 37, "8": 33}} (same schedule of injection points per config family)
Unexpected exits: {"rmw_w1": 0, "rmw_w3": 0, "rmw_w5": 0, "rmw_w8": 0, "ycsb_w1_theta0.99": 0, "ycsb_w3_theta0.99": 0, "ycsb_w5_theta0.99": 0, "ycsb_w8_theta0.99": 0}
Oracle raw verdicts: {"rmw_w1": {"match": 7880, "mismatch": 3640}, "rmw_w3": {"match": 7027, "mismatch": 4493}, "rmw_w5": {"match": 6699, "mismatch": 4821}, "rmw_w8": {"match": 6540, "mismatch": 4980}, "ycsb_w1_theta0.99": {"match": 7374, "mismatch": 4146}, "ycsb_w3_theta0.99": {"match": 6759, "mismatch": 4761}, "ycsb_w5_theta0.99": {"match": 6579, "mismatch": 4941}, "ycsb_w8_theta0.99": {"match": 6563, "mismatch": 4957}}
Wall seconds (22 jobs): {"rmw_w1": 29.3, "rmw_w3": 26.5, "rmw_w5": 28.7, "rmw_w8": 32.0, "ycsb_w1_theta0.99": 28.5, "ycsb_w3_theta0.99": 27.3, "ycsb_w5_theta0.99": 33.5, "ycsb_w8_theta0.99": 31.9}
