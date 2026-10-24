#!/usr/bin/env python3
"""TPC-C-style multi-statement workload for the recovery prototype.

Why: every earlier workload fixed each transaction's write set and after-images when the
workload was generated. Here transactions are procedures. NewOrder, Payment and Delivery read
the current database state and compute their writes from what they read, so a transaction's
write set and after-images depend on the transactions that committed before it (order ids,
stock levels, year-to-date totals, balances).

What is reused unchanged from experiments/rev_20261007/scripts: crash cuts and ground truth
(v3 `apply_crash`), the numeric-frontier artifacts and adapter fault settings (v4), the
linear-time recovery variants and the flat-replay and history baselines (v5), and the
chain-check oracle (scale_study).

What is new: the schema and transaction procedures below, and `run_engine_proc`, which
executes procedures instead of replaying precomputed writes. Deterministic transactions
commit in arrival order. An OCC transaction aborts if any key it read was written by a
transaction that committed after it started (same rule as v3); otherwise it commits. Aborted
transactions are not retried.

This is TPC-C-style, not TPC-C: three of the five transaction types (the two read-only ones
write nothing and cannot affect recovered state), small scale (1 or 4 warehouses, 10
districts, 30 customers per district, 200 items), simplified skew, no think times, and
throughput is not measured.

Subcommands: grid (correctness), timing (serial oracle timing).
"""
from __future__ import annotations
import argparse, csv, hashlib, json, random, statistics, sys, time
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

# the earlier scripts live in ../../rev_20261007/scripts in the repository and in
# ../../scripts on the server copy
for _p in (Path(__file__).resolve().parents[2] / "rev_20261007" / "scripts", Path(__file__).resolve().parents[2] / "scripts"):
    if (_p / "real_recovery_prototype_v3.py").exists():
        sys.path.insert(0, str(_p))
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v4 as p4
import real_recovery_prototype_v5 as p5
import scale_study as ss

FAULTS = p3.FAULTS
DISTRICTS, CUSTOMERS, ITEMS = 10, 30, 200


def price(i):
    return 100 + (i * 37) % 9900


def initial_db(warehouses):
    db = {}
    for w in range(1, warehouses + 1):
        db["W:%d:ytd" % w] = 300000
        for d in range(1, DISTRICTS + 1):
            db["D:%d:%d:ytd" % (w, d)] = 30000
            db["D:%d:%d:next_o_id" % (w, d)] = 1
            db["D:%d:%d:next_deliv" % (w, d)] = 1
            for c in range(1, CUSTOMERS + 1):
                db["C:%d:%d:%d:balance" % (w, d, c)] = -1000
                db["C:%d:%d:%d:ytd_payment" % (w, d, c)] = 1000
                db["C:%d:%d:%d:payment_cnt" % (w, d, c)] = 1
                db["C:%d:%d:%d:delivery_cnt" % (w, d, c)] = 0
        for i in range(1, ITEMS + 1):
            db["S:%d:%d:quantity" % (w, i)] = 10 + (w * 7919 + i * 104729) % 91
            db["S:%d:%d:ytd" % (w, i)] = 0
            db["S:%d:%d:order_cnt" % (w, i)] = 0
    return db


# ------------------------------ transaction procedures ------------------------------
# Each takes get(key) -> current value and returns an ordered list of (key, after-image).

def new_order(get, a, tid):
    w, d, c, lines = a
    o = get("D:%d:%d:next_o_id" % (w, d))
    out = [("D:%d:%d:next_o_id" % (w, d), o + 1),
           ("O:%d:%d:%d:customer" % (w, d, o), c),
           ("O:%d:%d:%d:ol_cnt" % (w, d, o), len(lines)),
           ("NO:%d:%d:%d" % (w, d, o), 1)]
    for n, (i, sw, q) in enumerate(lines, 1):
        s = get("S:%d:%d:quantity" % (sw, i))
        out.append(("S:%d:%d:quantity" % (sw, i), s - q if s - q >= 10 else s - q + 91))
        out.append(("S:%d:%d:ytd" % (sw, i), get("S:%d:%d:ytd" % (sw, i)) + q))
        out.append(("S:%d:%d:order_cnt" % (sw, i), get("S:%d:%d:order_cnt" % (sw, i)) + 1))
        out.append(("OL:%d:%d:%d:%d:amount" % (w, d, o, n), q * price(i)))
    return out


def payment(get, a, tid):
    w, d, c, amt = a
    return [("W:%d:ytd" % w, get("W:%d:ytd" % w) + amt),
            ("D:%d:%d:ytd" % (w, d), get("D:%d:%d:ytd" % (w, d)) + amt),
            ("C:%d:%d:%d:balance" % (w, d, c), get("C:%d:%d:%d:balance" % (w, d, c)) - amt),
            ("C:%d:%d:%d:ytd_payment" % (w, d, c), get("C:%d:%d:%d:ytd_payment" % (w, d, c)) + amt),
            ("C:%d:%d:%d:payment_cnt" % (w, d, c), get("C:%d:%d:%d:payment_cnt" % (w, d, c)) + 1),
            ("H:%d:%d:%d:%d" % (w, d, c, tid), amt)]


def delivery(get, a, tid):
    w, carrier = a
    out = []
    for d in range(1, DISTRICTS + 1):
        o = get("D:%d:%d:next_deliv" % (w, d))
        if o >= get("D:%d:%d:next_o_id" % (w, d)):
            continue
        c = get("O:%d:%d:%d:customer" % (w, d, o))
        total = sum(get("OL:%d:%d:%d:%d:amount" % (w, d, o, n)) for n in range(1, get("O:%d:%d:%d:ol_cnt" % (w, d, o)) + 1))
        out += [("NO:%d:%d:%d" % (w, d, o), 0),
                ("O:%d:%d:%d:carrier" % (w, d, o), carrier),
                ("C:%d:%d:%d:balance" % (w, d, c), get("C:%d:%d:%d:balance" % (w, d, c)) + total),
                ("C:%d:%d:%d:delivery_cnt" % (w, d, c), get("C:%d:%d:%d:delivery_cnt" % (w, d, c)) + 1),
                ("D:%d:%d:next_deliv" % (w, d), o + 1)]
    return out


PROCS = {"new_order": new_order, "payment": payment, "delivery": delivery}


class PTxn:
    __slots__ = ("tid", "mode", "start", "vpoint", "kind", "args")

    def __init__(self, tid, mode, start, vpoint, kind, args):
        self.tid, self.mode, self.start, self.vpoint, self.kind, self.args = tid, mode, start, vpoint, kind, args


def gen_workload(seed, n, mix_det, warehouses):
    rng = random.Random(seed)
    skew = lambda m: 1 + int(m * rng.random() ** 2)          # low ids are hotter
    txns = []
    for i in range(n):
        mode = "det" if rng.random() < mix_det else "occ"
        r = rng.random()
        w = rng.randint(1, warehouses)
        if r < 0.49:
            lines, seen = [], set()
            for _ in range(rng.randint(5, 15)):
                item = min(ITEMS, skew(ITEMS))
                sw = w if (warehouses == 1 or rng.random() >= 0.01) else rng.choice([x for x in range(1, warehouses + 1) if x != w])
                if (sw, item) in seen:
                    continue
                seen.add((sw, item))
                lines.append((item, sw, rng.randint(1, 10)))
            kind, args = "new_order", (w, rng.randint(1, DISTRICTS), min(CUSTOMERS, skew(CUSTOMERS)), lines)
        elif r < 0.96:
            kind, args = "payment", (w, rng.randint(1, DISTRICTS), min(CUSTOMERS, skew(CUSTOMERS)), rng.randint(100, 500000))
        else:
            kind, args = "delivery", (w, rng.randint(1, 10))
        vpoint = i + (0 if mode == "det" else rng.randint(1, 3))
        txns.append(PTxn(i, mode, i, vpoint, kind, args))
    return txns


def run_engine_proc(base, txns, ckpt_after):
    state = dict(base)
    last_write = {}
    committed, redo, validation = [], {}, {}
    reads_of, aborted = {}, []      # recorded for history export only; not used by the engine
    stats = Counter()
    for t in sorted(txns, key=lambda t: (t.vpoint, t.tid)):
        reads = set()

        def get(k):
            reads.add(k)
            return state.get(k, 0)

        writes = PROCS[t.kind](get, t.args, t.tid)
        stats["attempt_" + t.kind] += 1
        if not writes:
            stats["empty_" + t.kind] += 1
            continue
        reads_of[t.tid] = sorted(reads)
        if t.mode == "occ":
            stats["occ"] += 1
            if any(last_write.get(k, -1) > t.start for k in reads):
                stats["abort_" + t.kind] += 1
                aborted.append(t.tid)
                continue
            validation[t.tid] = True
        for k, v in writes:
            state[k] = v
            last_write[k] = t.vpoint
        redo[t.tid] = writes
        committed.append(t.tid)
        stats["commit_" + t.kind] += 1
        stats["writes"] += len(writes)
    ckpt = None
    if 0 < ckpt_after < len(committed):
        ck = dict(base)
        for tid in committed[:ckpt_after]:
            for k, v in redo[tid]:
                ck[k] = v
        ckpt = {"included": committed[:ckpt_after], "state": ck}
    return {"base": base, "committed": committed, "redo": redo, "validation": validation,
            "modes": {t.tid: t.mode for t in txns}, "ckpt": ckpt,
            "n_occ": stats["occ"], "n_occ_committed": len(validation), "stats": stats,
            "reads": reads_of, "aborted": aborted}


def cases(n, warehouses, seed, mix_det, ckpt_after):
    base = initial_db(warehouses)
    eng = run_engine_proc(base, gen_workload(seed * 131 + 17, n, mix_det, warehouses), ckpt_after)
    if len(eng["committed"]) < 12:
        return
    for drop_last in (0, 2, 4):
        crash = p3.apply_crash(eng, drop_last)
        disk = ss.entries_from_engine(eng, crash)
        art = p5.to_artifacts(disk, base)
        for fault in FAULTS:
            yield (drop_last, fault), base, disk, art, p5.recover_from_disk(disk, base, fault), crash["gt_state"], eng


def grid_cell(task):
    n, warehouses, seed, mix_det, ckpt_after, with_metadata = task
    rows, stats = [], Counter()
    views = {}
    for (drop_last, fault), base, disk, art, d_rec, truth, eng in cases(n, warehouses, seed, mix_det, ckpt_after):
        buggy = d_rec != truth
        if fault == "clean":
            views = {}
            if with_metadata:
                for name, level, f, rate in p4.SETTINGS:
                    h = hashlib.sha256(("%d|%d|%s|%d|%d|%s" % (warehouses, seed, mix_det, ckpt_after, drop_last, name)).encode()).hexdigest()
                    views[name] = p4.apply_adapter(art, level, f, rate, random.Random(int(h[:12], 16)))
            if drop_last == 0:
                stats.update(eng["stats"]); stats["engines"] += 1; stats["committed"] += len(eng["committed"])
            stats["clean_differs_from_truth"] += int(buggy)
        row = {"warehouses": warehouses, "fault": fault, "drop_last": drop_last, "buggy": int(buggy),
               "oracle": p3.score(ss.oracle_fast(art, d_rec), buggy),
               "single_log_replay": p3.score(p5.single_log_check(disk, base, d_rec), buggy),
               "history_acceptor": p3.score(p5.history_check(disk, base, d_rec), buggy)}
        for name, v in views.items():
            row["md_" + name] = p3.score(ss.oracle_fast(v, d_rec), buggy)
        rows.append(row)
    return rows, stats


def block(rows, col):
    b = [r for r in rows if r["buggy"]]; c = [r for r in rows if not r["buggy"]]
    cb, cc = Counter(r[col] for r in b), Counter(r[col] for r in c)
    verdicts = cb["detected"] + cb["missed"] + cc["correct_clean"] + cc["false_bug"]
    return {"recall": cb["detected"] / len(b) if b else None, "false_bug_rate": cc["false_bug"] / len(c) if c else None,
            "missed": cb["missed"], "false_bug": cc["false_bug"],
            "abstain_buggy": cb["abstained"] / len(b) if b else None, "abstain_clean": cc["abstained_clean"] / len(c) if c else None,
            "verdict_rate": verdicts / len(rows) if rows else None,
            "wrong_among_verdicts": (cb["missed"] + cc["false_bug"]) / verdicts if verdicts else None}


def grid_main(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tasks = [(a.n, w, seed, mix, ck, not a.no_metadata) for w in (1, 4) for seed in range(a.seeds)
             for mix in (0.25, 0.5, 0.75) for ck in (0, a.n // 3)]
    t0 = time.time()
    rows, stats = [], Counter()
    with Pool(a.jobs) as pool:
        for part, st in pool.imap(grid_cell, tasks, chunksize=2):
            rows += part; stats += st
    e = max(1, stats["engines"])
    m = {"config": {"n": a.n, "warehouses": [1, 4], "districts": DISTRICTS, "customers_per_district": CUSTOMERS, "items": ITEMS, "seeds": a.seeds},
         "n_runs": len(rows), "n_buggy": sum(r["buggy"] for r in rows), "n_clean": sum(1 - r["buggy"] for r in rows),
         "wall_s": round(time.time() - t0, 1), "jobs": a.jobs,
         "clean_recovery_differs_from_truth": stats["clean_differs_from_truth"],
         "workload": {"engine_executions": stats["engines"], "mean_committed": stats["committed"] / e,
                      "mean_writes_per_committed_txn": stats["writes"] / max(1, stats["committed"]),
                      "initial_keys": {w: len(initial_db(w)) for w in (1, 4)},
                      "committed_by_type": {k: stats["commit_" + k] for k in PROCS},
                      "occ_abort_rate": (sum(stats["abort_" + k] for k in PROCS) / stats["occ"]) if stats["occ"] else None,
                      "occ_aborts_by_type": {k: stats["abort_" + k] for k in PROCS},
                      "deliveries_with_nothing_to_deliver": stats["empty_delivery"]},
         "checkers": {ch: block(rows, ch) for ch in ("oracle", "single_log_replay", "history_acceptor")},
         "by_warehouses": {str(w): {ch: block([r for r in rows if r["warehouses"] == w], ch) for ch in ("oracle", "single_log_replay", "history_acceptor")} for w in (1, 4)},
         "per_fault": {}, "metadata": {}}
    for f in FAULTS:
        fb = [r for r in rows if r["fault"] == f and r["buggy"]]
        m["per_fault"][f] = {"n_buggy": len(fb), **{ch: sum(r[ch] == "detected" for r in fb) for ch in ("oracle", "single_log_replay", "history_acceptor")}}
    if not a.no_metadata:
        for name, _, _, _ in p4.SETTINGS:
            m["metadata"][name] = block(rows, "md_" + name)
    (out / "metrics_tpcc.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    with (out / "runs_tpcc.csv").open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); wr.writeheader()
        for r in rows:
            wr.writerow(r)
    print(json.dumps({k: m[k] for k in ("config", "n_runs", "n_buggy", "n_clean", "wall_s", "clean_recovery_differs_from_truth", "workload", "checkers", "per_fault")}, indent=1, sort_keys=True))
    return 0


def timing_main(a):
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    sample = []
    for w in (1, 4):
        for mix in (0.25, 0.5, 0.75):
            for ck in (0, a.n // 3):
                for _, base, disk, art, d_rec, truth, eng in cases(a.n, w, 0, mix, ck):
                    sample.append((base, disk, art, d_rec))
    reps = []
    for _ in range(a.repeats):
        o, r = [], []
        for base, disk, art, d_rec in sample:
            t0 = time.perf_counter(); ss.oracle_fast(art, d_rec); o.append(time.perf_counter() - t0)
            t0 = time.perf_counter(); p5.recover_from_disk(disk, base, "clean"); r.append(time.perf_counter() - t0)
        o.sort()
        reps.append((1e3 * sum(o) / len(o), 1e3 * o[int(0.95 * (len(o) - 1))], 1e3 * sum(r) / len(r)))
    ms = lambda i: {"mean": statistics.mean(x[i] for x in reps), "sd": statistics.stdev(x[i] for x in reps), "values": [x[i] for x in reps]}
    m = {"n": a.n, "checks_per_repeat": len(sample), "repeats": a.repeats,
         "oracle_mean_ms": ms(0), "oracle_p95_ms": ms(1), "recovery_replay_mean_ms": ms(2)}
    (out / "timing_tpcc.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    print(json.dumps(m, indent=1, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grid"); g.add_argument("--out", required=True); g.add_argument("--n", type=int, required=True)
    g.add_argument("--seeds", type=int, default=40); g.add_argument("--jobs", type=int, default=8); g.add_argument("--no-metadata", action="store_true")
    t = sub.add_parser("timing"); t.add_argument("--out", required=True); t.add_argument("--n", type=int, required=True); t.add_argument("--repeats", type=int, default=5)
    a = ap.parse_args(argv)
    return grid_main(a) if a.cmd == "grid" else timing_main(a)


if __name__ == "__main__":
    raise SystemExit(main())
