# Can the oracle be attached to HDCC or Aria? Source inspection, 2026-10-10

Goal: attach the durable-prefix oracle to a real mixed or deterministic engine before the 2026-11-01 deadline. Outcome: not possible with the public artifacts, because neither implements crash recovery. Nothing was built or run; this is a reading of the source at the commits below (shallow clones, kept outside the repository).

## Aria

Repository: https://github.com/luyi0619/aria, commit `d0508c393ec084582c12e6f3abadab63501eaedd` (2020-08-23).

- No file in the tree writes a transaction log. A search of all `.cpp` and `.h` files for `fsync`, `WAL`, `recover`, `replay`, `checkpoint`, `persist` finds nothing related to durability.
- Durability is modelled as a delay: `core/Macros.h:43` defines the flag `durable_write_cost` ("the cost of durable write in microseconds"), and `core/Executor.h:259-261` (`simulate_2pc_durable_cost`) sleeps for twice that value.

Consequence: there is no durable state and no recovery to check.

## HDCC

Repository: https://github.com/dbiir/HDCC (based on the Deneva testbed), branch `mixed` at commit `82514f938eeca26d24f00f273d7df5eba7795758` (2025-01-07) and branch `checkpoint` at `93d9c70df0531074db7ab40bc72eab79501b97ec` (2024-12-01).

Logging (`mixed` branch):

- `config.h:237`: `#define LOGGING false`. Logging is compiled out by default; `LOG_COMMAND` and `LOG_REDO` are also false.
- `system/logger.h:46-82`: the "ARIES-style" record has checksum, lsn, type, iud, txn_id, table_id, key and, for HDCC, `max_calvin_tid`. The before/after image fields are commented out (`// TODO: column list`).
- `system/logger.cpp:132-168` (`writeToBuffer`; the non-command branch is lines 151-158): writes checksum, lsn, type, iud, txn_id, table_id and key to the log file. It does not write `max_calvin_tid` and writes no row image.
- `system/txn.cpp:1420-1433`: on the optimistic path, each written row enqueues an `L_UPDATE` record with transaction id, table id and primary key. Deterministic (Calvin-path) transactions are excluded (`if (algo != CALVIN)`).
- `system/txn.cpp:601-604`: an optimistic commit creates an `L_COMMIT` record with `max_calvin_tid`, the largest deterministic transaction id the transaction depends on (maintained in `storage/row.cpp:515-520` and `concurrency_control/hdcc.cpp:236-241`). In this paper's terms that is a one-sided cross-mode frontier on OCC records.
- `system/sequencer.cpp:408-411`: for each transaction the sequencer allocates ten bytes and writes `sizeof(data)` bytes of that uninitialized buffer to `txnfile.log`. The deterministic input log is a placeholder, not the transaction's input.

Checkpoint (`checkpoint` branch):

- `system/checkpoint_thread.cpp:11-43`: one checkpoint thread writes `row->stable_data` for the rows to a file `./checkpoint` once, when the run is half done (`system/sim_manager.cpp:99`).

Recovery:

- In both branches, a search of all `.cpp` and `.h` files (excluding the bundled jemalloc) for `recover`, `replay`, `ifstream`, `fread(`, `logfile`, `txnfile` finds no code that opens a log or checkpoint file for reading. The only `ifstream` uses read the schema file, the address file and a benchmark input file.

Consequence: the artifact can produce log files but cannot restart from them, the log has no values to replay, deterministic transactions are not identifiable in it, and the one field that orders modes is not serialized. No recovered state exists to compare with a reference, for this oracle or any other checker.

## What this supports and what it does not

- Supports: a mixed engine computes a one-sided cross-mode frontier at commit (HDCC's `max_calvin_tid`), so persisting it is a small step. This matches the "one-sided" evidence level in the evaluation.
- Does not support: any claim that the oracle works on HDCC or Aria. All evaluation remains on the authors' prototype.
- Not checked: whether the engines' authors have unpublished recovery code; other engines (for example ones with a single write-ahead log) were not inspected.
