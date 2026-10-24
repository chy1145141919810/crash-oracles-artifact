#!/usr/bin/env python3
"""Export recovery runs as client histories for Elle (rw-register model).

For each recovery run this writes one EDN history that a black-box client could have
recorded, plus one row in index.csv with the ground-truth label and our own checkers'
outcomes for the same run.

History of a run
  * Every transaction is one :txn operation on its own process. It is invoked at its start
    time and completes at its commit time, so optimistic transactions overlap in real time
    with the transactions that commit while they run, exactly as in the engine.
  * Micro-operations are the transaction's reads followed by its writes. A written value is
    the writer's id + 1, so every (key, value) is written at most once, as Elle requires. A
    read reports the id of the version it saw (nil for the initial state).
  * A transaction whose commit is in the durable prefix completes :ok. One that committed but
    was cut off by the crash completes :info (the client never learned the outcome). One
    aborted by OCC validation completes :fail.
  * After recovery, one final read-only transaction reads every key written by any
    transaction, from the recovered database. Each recovered value is mapped back to the
    version id of the transaction whose after-image it is (the latest such transaction in
    commit order if several wrote the same value; nil if it is the initial value; a value
    nobody wrote, 1000000000, if it matches nothing).

Deterministic batches: with --det-batch B > 1, the deterministic transactions whose arrival
index falls in the same block of B are shown to the client as one batch: all are invoked at
the batch start and complete at the batch end, as when a deterministic engine executes a
batch in parallel. The engine, its commit order and the recovered states are unchanged; only
the real-time intervals a client could observe become wider.

What Elle can and cannot see: it sees client-observable reads, writes, completion status and
real-time order. It does not see logs, markers, checkpoints or order metadata.

Workloads: tpcc (procedures of tpcc_study.py), rmw and ycsb (v3 generator; need the SQLite
datasets). In-memory crash model, full adapter for our own oracle.
"""
from __future__ import annotations
import argparse, csv, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tpcc_study as tp
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v5 as p5
import scale_study as ss

M = 100000
GARBAGE = 1000000000
FINAL_PROCESS = 1000000


def edn_ops(ops):
    return "[" + " ".join("[:%s %d %s]" % (f, k, "nil" if v is None else v) for f, k, v in ops) + "]"


def history(eng, meta, crash, d_rec, base, det_batch=1):
    """meta: tid -> (start, vpoint, read keys). Returns EDN text."""
    committed = eng["committed"]
    durable = set(crash["durable"])
    kid = {}

    def key_id(k):
        if k not in kid:
            kid[k] = len(kid)
        return kid[k]

    cur = {}                 # key -> version id of the last committed writer
    writers = {}             # key -> [(version id, after-image)] in commit order
    events = []
    for tid in committed:
        start, vpoint, reads = meta[tid]
        r_inv = [("r", key_id(k), None) for k in reads]
        r_ok = [("r", key_id(k), cur.get(k)) for k in reads]
        w = [("w", key_id(k), tid + 1) for k, _ in eng["redo"][tid]]
        for k, af in eng["redo"][tid]:
            cur[k] = tid + 1
            writers.setdefault(k, []).append((tid + 1, af))
        status = "ok" if tid in durable else "info"
        if eng["modes"][tid] == "det" and det_batch > 1:
            # client-visible interval of a deterministic transaction is its whole batch
            lo = (start // det_batch) * det_batch
            start, vpoint = lo, lo + det_batch - 1
        events.append((start * M + tid, tid, "invoke", r_inv + w))
        events.append((vpoint * M + M // 2 + tid, tid, status, (r_ok if status == "ok" else r_inv) + w))
    for tid in eng.get("aborted", []):
        start, vpoint, reads = meta[tid]
        ops = [("r", key_id(k), None) for k in reads]
        events.append((start * M + tid, tid, "invoke", ops))
        events.append((vpoint * M + M // 2 + tid, tid, "fail", ops))
    end = (max(t for t, _, _, _ in events) // M + 10) * M
    final_inv, final_ok = [], []
    for k in sorted(writers, key=lambda k: kid[k]):
        got = d_rec.get(k)
        vid = None
        match = [v for v, af in writers[k] if af == got]
        if match:
            vid = match[-1]
        elif got is None or got == base.get(k):
            vid = None
        else:
            vid = GARBAGE
        final_inv.append(("r", kid[k], None))
        final_ok.append(("r", kid[k], vid))
    events.append((end, FINAL_PROCESS, "invoke", final_inv))
    events.append((end + 1, FINAL_PROCESS, "ok", final_ok))
    events.sort(key=lambda e: e[0])
    lines = []
    for i, (t, proc, typ, ops) in enumerate(events):
        lines.append("{:type :%s, :f :txn, :value %s, :process %d, :time %d, :index %d}" % (typ, edn_ops(ops), proc, t, i))
    return "\n".join(lines) + "\n"


def engines(a):
    """Yields (scale label, seed, mix, ckpt_after, base, eng, meta)."""
    if a.workload == "tpcc":
        for w in (1, 4):
            for seed in range(a.seeds):
                for mix in (0.25, 0.5, 0.75):
                    for ck in (0, a.n // 3):
                        base = tp.initial_db(w)
                        txns = tp.gen_workload(seed * 131 + 17, a.n, mix, w)
                        eng = tp.run_engine_proc(base, txns, ck)
                        meta = {t.tid: (t.start, t.vpoint, eng["reads"].get(t.tid, [])) for t in txns}
                        yield "W%d" % w, seed, mix, ck, base, eng, meta
    else:
        env = {"chinook_sqlite": "RESEARCHOS_DATASET_CHINOOK_SQLITE", "northwind_sqlite": "RESEARCHOS_DATASET_NORTHWIND_SQLITE"}
        for dom, var in env.items():
            records = p3.load_rows(Path(os.environ[var]), dom)
            for seed in range(a.seeds):
                for mix in (0.25, 0.5, 0.75):
                    base, txns = p3.gen_workload(records, seed * 131 + 17, a.n, mix, a.writes_per_txn, a.workload, a.theta)
                    for ck in (0, a.n // 3):
                        eng = p3.run_engine(base, txns, ck)
                        eng["aborted"] = [t.tid for t in txns if t.mode == "occ" and t.tid not in eng["validation"]]
                        meta = {t.tid: (t.start, t.vpoint, list(t.reads)) for t in txns}
                        yield dom, seed, mix, ck, base, eng, meta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workload", required=True, choices=["tpcc", "rmw", "ycsb"])
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--writes-per-txn", type=int, default=1)
    ap.add_argument("--theta", type=float, default=0.0)
    ap.add_argument("--det-batch", type=int, default=1, help="deterministic transactions of one batch share one client-visible time interval")
    a = ap.parse_args(argv)
    out = Path(a.out); (out / "h").mkdir(parents=True, exist_ok=True)
    rows = []
    for scale, seed, mix, ck, base, eng, meta in engines(a):
        if len(eng["committed"]) < 12:
            continue
        for drop_last in (0, 2, 4):
            crash = p3.apply_crash(eng, drop_last)
            disk = ss.entries_from_engine(eng, crash)
            art = p5.to_artifacts(disk, base)
            for fault in p3.FAULTS:
                d_rec = p5.recover_from_disk(disk, base, fault)
                buggy = d_rec != crash["gt_state"]
                name = "%05d.edn" % len(rows)
                (out / "h" / name).write_text(history(eng, meta, crash, d_rec, base, a.det_batch))
                rows.append({"file": name, "scale": scale, "seed": seed, "mix_det": mix, "ckpt_after": ck,
                             "drop_last": drop_last, "fault": fault, "buggy": int(buggy),
                             "oracle": p3.score(ss.oracle_fast(art, d_rec), buggy),
                             "single_log_replay": p3.score(p5.single_log_check(disk, base, d_rec), buggy),
                             "history_acceptor": p3.score(p5.history_check(disk, base, d_rec), buggy)})
    with (out / "index.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow(r)
    print(len(rows), "histories written to", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
