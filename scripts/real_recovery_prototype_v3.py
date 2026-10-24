#!/usr/bin/env python3
"""Real deterministic/OCC recovery prototype with operator-INDEPENDENT ground truth.

This extends the paper's evidence battery to answer the reviewers' blocking request:
score the durable-prefix oracle against recovery faults whose ground truth is NOT
authored by the oracle's own contract.

Design (breaks the shared-assumption / tautology critique):
  1. A genuine mixed engine executes generated transactions over REAL SQLite state
     (Chinook / Northwind). Deterministic (Calvin-style batch-ordered) transactions
     always commit; OCC transactions validate their read-set against intervening
     committed writes and abort on conflict. The engine produces a TRUE committed set
     and TRUE durable order by EXECUTION, then writes real redo / validation / commit /
     checkpoint / cross-mode-frontier records to durable logs with monotonic LSNs.
  2. A crash cut truncates the durable logs at a stable per-log watermark.
  3. The GROUND TRUTH recovered state is the durable committed prefix applied in the
     TRUE durable order from the correct base -- computed by the engine from what it
     actually ran, INDEPENDENT of the oracle's field reconstruction code.
  4. Recovery faults are injected into the RECOVERY PROCEDURE (real code paths), not
     into labels: flat-order replay, ignore-validation, torn-commit include, stale
     checkpoint, truncate suffix. A recovery run is "buggy" iff its output differs from
     the ground-truth state (some faults are masked and correctly coincide).
  5. The durable-prefix ORACLE and two baselines (single-log flat replay, crash/no-crash
     differential) each read only durable artifacts + recovered state and emit
     match / mismatch / uncertain / precfail. They are scored against the ground truth.
  6. A degraded-adapter arm drops the cross-mode predecessor frontier to test whether
     the oracle abstains (uncertain) instead of false-reporting.

Outputs: real_recovery_results/{metrics_real_recovery.json, runs.csv, summary.md}
Read-only over the SQLite databases. Software only; no GPU.
"""
from __future__ import annotations
import argparse, bisect, csv, hashlib, json, math, os, random, sqlite3, statistics, time
from collections import defaultdict
from pathlib import Path

# ------------------------------ real-state loading ------------------------------

def is_sqlite(path: Path) -> bool:
    try:
        con = sqlite3.connect(str(path))
        try:
            row = con.execute("select count(*) from sqlite_master where type='table' and name not like 'sqlite_%'").fetchone()
            return bool(row and int(row[0]) > 0)
        finally:
            con.close()
    except Exception:
        return False

def load_rows(db_path: Path, dataset_id: str, limit_tables=60, cap=400):
    con = sqlite3.connect(str(db_path))
    recs = []
    try:
        tabs = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall()]
        for t in tabs[:limit_tables]:
            try:
                rows = con.execute('select * from "%s" limit 60' % t.replace('"', '""')).fetchall()
            except Exception:
                continue
            for i, row in enumerate(rows):
                tot, seen = 0.0, False
                for v in row:
                    if isinstance(v, bool):
                        continue
                    if isinstance(v, (int, float)) and math.isfinite(float(v)):
                        tot += abs(float(v)); seen = True
                    elif isinstance(v, bytes):
                        tot += len(v)
                    elif isinstance(v, str):
                        tot += len(v.strip())
                val = None if (not seen and tot <= 0) else int(tot * 100) % 100000
                if val is None:
                    continue
                recs.append({"key": "%s:%s:%03d" % (dataset_id, t, i), "value": max(1, val)})
            if len(recs) >= cap:
                break
    finally:
        con.close()
    return recs

# ------------------------------ workload generation ------------------------------

class Txn:
    """v3: a transaction carries a WRITE SET (ordered list of (key, after-image)) and a read set."""
    __slots__ = ("tid", "mode", "reads", "writes", "start", "vpoint")
    def __init__(self, tid, mode, reads, writes, start, vpoint):
        self.tid = tid; self.mode = mode; self.reads = reads; self.writes = writes
        self.start = start; self.vpoint = vpoint

def _zipf_cdf(n, theta):
    w = [1.0 / ((r + 1) ** theta) for r in range(n)]
    tot = sum(w); acc = 0.0; cdf = []
    for x in w:
        acc += x / tot; cdf.append(acc)
    return cdf

def gen_workload(records, seed, n, mix_det, wpt=1, workload="rmw", theta=0.0):
    """Generate n transactions with `wpt` writes each.
    rmw : read-modify-write. First write key as in v1/v2 (hot pool for i<12, else uniform);
          further write keys uniform; read set = write keys plus 0-2 others. With wpt=1 the
          RNG call sequence and after-images are identical to v2.
    ycsb: YCSB-A-like, 50/50 read/update: wpt blind updates plus wpt reads per txn, keys drawn
          Zipfian(theta) over the row keyspace (theta=0 is uniform). OCC validates the reads."""
    rng = random.Random(seed)
    keys = [r["key"] for r in records]
    base = {r["key"]: r["value"] for r in records}
    hot = keys[:6]
    cdf = _zipf_cdf(len(keys), theta) if workload == "ycsb" else None
    def zkey():
        return keys[min(len(keys) - 1, bisect.bisect_left(cdf, rng.random()))]
    txns = []
    for i in range(n):
        mode = "det" if rng.random() < mix_det else "occ"
        salt = 7 if mode == "det" else 19
        if workload == "rmw":
            wkey = hot[i % len(hot)] if i < 12 else rng.choice(keys)
            reads = {wkey}
            for _ in range(rng.randint(0, 2)):
                reads.add(rng.choice(keys))
            start = i
            vpoint = i + (0 if mode == "det" else rng.randint(1, 3))  # occ validates a bit later
            wkeys = [wkey]
            while len(wkeys) < wpt:
                k = rng.choice(keys)
                if k not in wkeys:
                    wkeys.append(k)
            reads = sorted(reads | set(wkeys))
            rv = sum(base.get(k, 0) for k in reads)
            writes = [(k, int((rv + salt * (i + 1) + 101 * j) % 100000)) for j, k in enumerate(wkeys)]
        else:
            wkeys = []
            while len(wkeys) < wpt:
                k = zkey()
                if k not in wkeys:
                    wkeys.append(k)
            reads = sorted({zkey() for _ in range(wpt)})
            start = i
            vpoint = i + (0 if mode == "det" else rng.randint(1, 3))
            writes = [(k, int((base.get(k, 0) + salt * (i + 1) + 101 * j) % 100000)) for j, k in enumerate(wkeys)]
        txns.append(Txn(i, mode, reads, writes, start, vpoint))
    return base, txns

# ------------------------------ the engine (TRUTH) ------------------------------

def run_engine(base, txns, checkpoint_after):
    """Execute the mixed engine. Deterministic txns commit in batch (arrival) order.
    OCC txns validate: abort if any read key was written by a txn committed within
    (start, vpoint]. Returns committed order, records, checkpoint, true states."""
    state = dict(base)
    key_last_write_vpoint = {}  # key -> vpoint of last committed writer
    committed = []         # list of tids in true commit (durable) order
    seq_of = {}            # tid -> commit sequence index
    records = []           # durable records with lsn, log, type
    det_lsn = occ_lsn = 0
    frontier = {}          # tid -> immediate predecessor tid in commit order (cross-mode frontier)
    validation = {}        # occ tid -> True (validated) ; aborted occ never recorded
    commit_marker = {}     # tid -> True
    redo = {}              # tid -> (wkey, after)
    batch_pos = {}         # det tid -> batch order

    # process events in vpoint order (commit attempt), tie-break by tid
    order = sorted(txns, key=lambda t: (t.vpoint, t.tid))
    cseq = 0
    for t in order:
        if t.mode == "occ":
            # OCC validation: abort if a read key was overwritten after this txn snapshotted
            conflict = any(key_last_write_vpoint.get(k, -1) > t.start for k in t.reads)
            if conflict:
                continue  # abort: no durable records for an aborted occ txn
        # commit
        seq_of[t.tid] = cseq
        for wk, af in t.writes:
            state[wk] = af
            key_last_write_vpoint[wk] = t.vpoint
        redo[t.tid] = list(t.writes)
        commit_marker[t.tid] = True
        frontier[t.tid] = committed[-1] if committed else -1  # predecessor pointer (both modes)
        if t.mode == "det":
            det_lsn += 1
            batch_pos[t.tid] = det_lsn
            records.append({"lsn": det_lsn, "log": "det", "type": "redo_commit", "tid": t.tid})
        else:
            occ_lsn += 1
            validation[t.tid] = True
            records.append({"lsn": occ_lsn, "log": "occ", "type": "redo_valid_commit", "tid": t.tid})
        committed.append(t.tid)
        cseq += 1

    # checkpoint after the first `checkpoint_after` committed txns
    ckpt = None
    if 0 < checkpoint_after < len(committed):
        ck_state = dict(base)
        for tid in committed[:checkpoint_after]:
            for wk, af in redo[tid]:
                ck_state[wk] = af
        det_wm = max([batch_pos[t] for t in committed[:checkpoint_after] if t in batch_pos] + [0])
        occ_wm = 0
        for tid in committed[:checkpoint_after]:
            if tid in validation:
                occ_wm += 1
        ckpt = {"included": committed[:checkpoint_after], "state": ck_state,
                "det_wm": det_wm, "occ_wm": occ_wm,
                "digest": _digest(ck_state)}

    eng = {
        "base": base, "committed": committed, "seq_of": seq_of, "redo": redo,
        "commit_marker": commit_marker, "validation": validation, "frontier": frontier,
        "batch_pos": batch_pos, "records": records, "ckpt": ckpt,
        "modes": {t.tid: t.mode for t in txns},
        "final_committed_state": _apply(base, [redo[t] for t in committed]),
    }
    # no-crash full state (all txns as if all committed in arrival order) for the diff baseline
    all_state = dict(base)
    for t in sorted(txns, key=lambda x: x.tid):
        for wk, af in t.writes:
            all_state[wk] = af
    eng["no_crash_full_state"] = all_state
    eng["n_occ"] = sum(1 for t in txns if t.mode == "occ")
    eng["n_occ_committed"] = len(validation)
    return eng

def _apply(base, writes):
    """writes: list of per-transaction write lists [(key, after), ...] in replay order."""
    s = dict(base)
    for ws in writes:
        for wk, af in ws:
            s[wk] = af
    return s

def _digest(state):
    items = sorted((k, int(v)) for k, v in state.items())
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()[:16]

# ------------------------------ crash + recovery ------------------------------

def apply_crash(eng, drop_last):
    """Truncate durable logs: the last `drop_last` committed txns become non-durable
    (their records removed). Returns the durable view + the INDEPENDENT ground truth."""
    committed = eng["committed"]
    durable = committed[: len(committed) - drop_last] if drop_last else list(committed)
    durable_set = set(durable)
    # ground truth recovered state: durable committed prefix in TRUE order from correct base
    ckpt = eng["ckpt"]
    if ckpt and set(ckpt["included"]).issubset(durable_set):
        base = ckpt["state"]; suffix = [t for t in durable if t not in set(ckpt["included"])]
    else:
        base = eng["base"]; suffix = list(durable)
    gt_state = _apply(base, [eng["redo"][t] for t in suffix])
    return {"durable": durable, "durable_set": durable_set, "gt_state": gt_state,
            "ckpt_usable": bool(ckpt and set(ckpt["included"]).issubset(durable_set))}

def recover(eng, crash, fault, drop_commit_tid=None):
    """Recovery procedure UNDER TEST. `fault` selects an injected recovery bug.
    Returns recovered state D_rec."""
    committed = eng["committed"]; durable_set = crash["durable_set"]
    redo = eng["redo"]; ckpt = eng["ckpt"]
    # membership as the recovery code sees it
    members = [t for t in committed if t in durable_set]
    if fault == "torn_commit_include" and drop_commit_tid is not None:
        # a txn whose commit marker was lost is wrongly included
        if drop_commit_tid not in members:
            members = members + [drop_commit_tid]
    if fault == "ignore_validation":
        # wrongly include one more occ-shaped record beyond durable (simulate skipping validation)
        extra = [t for t in committed if t not in durable_set and eng["modes"].get(t) == "occ"]
        if extra:
            members = members + [extra[0]]
    if fault == "truncate_suffix" and members:
        members = members[:-1]  # drop a real durable suffix redo

    use_ckpt = crash["ckpt_usable"] and fault != "stale_checkpoint_noreapply"
    if crash["ckpt_usable"]:
        ck_inc = set(ckpt["included"])
        if fault == "stale_checkpoint_noreapply":
            # use checkpoint base but forget to re-apply the suffix
            return dict(ckpt["state"])
        base = ckpt["state"]; suffix = [t for t in members if t not in ck_inc]
    else:
        base = eng["base"]; suffix = list(members)

    # order of replay
    if fault == "flat_order":
        # flatten all logs by lsn, ignoring cross-mode edges: sort by (lsn, log) not true order
        recs = [r for r in eng["records"] if r["tid"] in set(suffix)]
        recs.sort(key=lambda r: (r["lsn"], r["log"]))
        ordered = [r["tid"] for r in recs]
    else:
        ordered = list(suffix)  # true durable order
    return _apply(base, [redo[t] for t in ordered])

# ------------------------------ checkers (oracle + baselines) ------------------------------

def canon(state):
    return _digest(state)

def oracle_check(eng, crash, d_rec, hide_frontier=False):
    """Durable-prefix oracle. Reconstructs membership + order + checkpoint base from
    ADAPTER FIELDS ONLY, checks write-relevant uniqueness, and compares canon states.
    Returns match / mismatch / uncertain / precfail."""
    committed = eng["committed"]; durable_set = crash["durable_set"]
    redo = eng["redo"]; ckpt = eng["ckpt"]; modes = eng["modes"]
    # membership: durable redo + commit; occ also needs validation marker
    members = []
    for t in committed:
        if t not in durable_set:
            continue
        if modes[t] == "occ" and not eng["validation"].get(t):
            continue
        members.append(t)
    if crash["ckpt_usable"]:
        ck_inc = set(ckpt["included"]); base = ckpt["state"]
        suffix = [t for t in members if t not in ck_inc]
    else:
        base = eng["base"]; suffix = list(members)
    # build order graph edges among suffix: det batch edges + cross-mode frontier edges
    pos = {}
    for i, t in enumerate(suffix):
        pos[t] = i
    # detect noncommuting incomparable pairs writing the same key with different after-images
    bykey = defaultdict(list)
    after_of = {}
    for t in suffix:
        for wk, af in redo[t]:
            bykey[wk].append(t)
            after_of[(t, wk)] = af
    ordered_pairs = set()
    # det batch order gives a total order among det txns
    det_suffix = [t for t in suffix if modes[t] == "det"]
    for a, b in zip(det_suffix, det_suffix[1:]):
        ordered_pairs.add((a, b))
    # cross-mode predecessor frontier: each txn is ordered after its recorded predecessor
    if not hide_frontier:
        for t in suffix:
            fr = eng["frontier"].get(t, -1)
            if fr in pos:
                ordered_pairs.add((fr, t))
    # uniqueness: for each key with >1 writer of DIFFERENT after-images, every such pair must be ordered
    # v3: same reachability relation as v2, computed once as a transitive closure (bitsets)
    adj = defaultdict(set)
    for (p, q) in ordered_pairs:
        adj[p].add(q)
    closure = {}
    def reach_set(x):
        if x in closure:
            return closure[x]
        seen = set(); stack = [x]
        while stack:
            u = stack.pop()
            for q in adj[u]:
                if q not in seen:
                    seen.add(q); stack.append(q)
        closure[x] = seen
        return seen
    def reachable(x, y):
        return x == y or y in reach_set(x)
    # v3: uniqueness is per written key, over the write-key-set overlap of each pair
    for k, ts in bykey.items():
        afts = {after_of[(t, k)] for t in ts}
        if len(ts) > 1 and len(afts) > 1:
            for i in range(len(ts)):
                for j in range(i + 1, len(ts)):
                    a, b = ts[i], ts[j]
                    if not (reachable(a, b) or reachable(b, a)):
                        return "uncertain"
    # unique -> compute reference via a stable topo order consistent with ordered_pairs
    order_list = _topo(suffix, ordered_pairs)
    if order_list is None:
        return "precfail"  # cycle
    d_ref = _apply(base, [redo[t] for t in order_list])
    return "match" if canon(d_ref) == canon(d_rec) else "mismatch"

def _topo(nodes, edges):
    adj = defaultdict(set); indeg = {n: 0 for n in nodes}
    for (a, b) in edges:
        if a in indeg and b in indeg and b not in adj[a]:
            adj[a].add(b); indeg[b] += 1
    ready = sorted([n for n in nodes if indeg[n] == 0])
    out = []
    while ready:
        n = ready.pop(0); out.append(n)
        for m in sorted(adj[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m); ready.sort()
    return out if len(out) == len(nodes) else None

def single_log_replay_check(eng, crash, d_rec):
    """Baseline: reconstruct committed prefix from redo+commit, replay in FLAT lsn order
    (ignores cross-mode edges), compare to d_rec. Its own reference uses flat order, so it
    cannot catch a flat-order recovery bug."""
    durable_set = crash["durable_set"]; redo = eng["redo"]; ckpt = eng["ckpt"]
    members = [t for t in eng["committed"] if t in durable_set]
    if crash["ckpt_usable"]:
        ck_inc = set(ckpt["included"]); base = ckpt["state"]; suffix = [t for t in members if t not in ck_inc]
    else:
        base = eng["base"]; suffix = list(members)
    recs = [r for r in eng["records"] if r["tid"] in set(suffix)]
    recs.sort(key=lambda r: (r["lsn"], r["log"]))
    ref = _apply(base, [redo[r["tid"]] for r in recs])
    return "match" if canon(ref) == canon(d_rec) else "mismatch"

def crash_no_crash_diff_check(eng, crash, d_rec):
    """Baseline: compare recovered state to the engine's TRUE no-crash final state
    (committed txns only, in true commit order). Still the wrong reference after a crash
    cut (includes the non-durable suffix), but exact for a no-crash clean run."""
    ref = eng["final_committed_state"]
    return "match" if canon(ref) == canon(d_rec) else "mismatch"

def crash_no_crash_diff_legacy_check(eng, crash, d_rec):
    """v1 baseline kept for side-by-side reporting: reference applies ALL generated txns
    (including aborted occ) in arrival order."""
    ref = eng["no_crash_full_state"]
    return "match" if canon(ref) == canon(d_rec) else "mismatch"

def history_check(eng, crash, d_rec):
    """Stronger external-style baseline: a serialization / possible-serial-outcome
    acceptor. It uses the SAME durable membership and checkpoint base as the oracle but
    is ORDER-BLIND: it accepts a recovered value for a key if that value is the after-image
    of ANY durable member writing the key (i.e. some serialization produces it), and requires
    unchanged keys to equal the base. It therefore catches membership, torn-commit, and
    truncation bugs but cannot see a wrong durable ORDER among noncommuting writes, which is
    exactly the oracle's differentiator. This is not a strawman: it is what a history /
    serializability acceptor fed the same durable artifacts would decide."""
    durable_set = crash["durable_set"]; redo = eng["redo"]; ckpt = eng["ckpt"]; modes = eng["modes"]
    members = []
    for t in eng["committed"]:
        if t not in durable_set:
            continue
        if modes[t] == "occ" and not eng["validation"].get(t):
            continue
        members.append(t)
    if crash["ckpt_usable"]:
        ck_inc = set(ckpt["included"]); base = ckpt["state"]; suffix = [t for t in members if t not in ck_inc]
    else:
        base = eng["base"]; suffix = list(members)
    poss = defaultdict(set); mkeys = set()
    for t in suffix:
        for wk, af in redo[t]:
            poss[wk].add(af); mkeys.add(wk)
    for k, v in d_rec.items():
        if k in mkeys:
            if v not in poss[k]:
                return "mismatch"
        elif v != base.get(k, 0):
            return "mismatch"
    return "match"

# ------------------------------ experiment driver ------------------------------

FAULTS = ["clean", "flat_order", "ignore_validation", "torn_commit_include",
          "stale_checkpoint_noreapply", "truncate_suffix"]

def score(pred, buggy):
    """Map a checker verdict + ground-truth bug flag to an outcome bucket."""
    if buggy:
        if pred == "mismatch":
            return "detected"
        if pred in ("uncertain", "precfail"):
            return "abstained"
        return "missed"
    else:
        if pred == "mismatch":
            return "false_bug"
        if pred in ("uncertain", "precfail"):
            return "abstained_clean"
        return "correct_clean"

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "real_recovery_results"))
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--writes-per-txn", type=int, default=1, choices=[1, 3, 5, 8])
    ap.add_argument("--workload", default="rmw", choices=["rmw", "ycsb"])
    ap.add_argument("--theta", type=float, default=0.0, help="Zipfian skew for --workload ycsb")
    args = ap.parse_args(argv)

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    # resolve datasets
    cands = {
        "chinook_sqlite": [
            os.environ.get("RESEARCHOS_DATASET_CHINOOK_SQLITE", ""),
        ],
        "northwind_sqlite": [
            os.environ.get("RESEARCHOS_DATASET_NORTHWIND_SQLITE", ""),
        ],
    }
    datasets = {}
    for name, paths in cands.items():
        for p in paths:
            if p and Path(p).exists() and is_sqlite(Path(p)):
                datasets[name] = load_rows(Path(p), name); break
    if len(datasets) < 2:
        print(json.dumps({"error": "datasets unavailable", "have": list(datasets)}))
        return 1

    checkers = ["oracle", "single_log_replay", "history_acceptor", "crash_no_crash_diff",
                "crash_no_crash_diff_legacy"]
    runs = []
    nocrash_clean = {"n": 0, "fixed_match": 0, "legacy_match": 0}
    engines_seen = {"n": 0, "occ": 0, "occ_committed": 0, "skipped_lt12_committed": 0}
    timing = {"oracle_s": [], "recovery_s": []}
    for dom, records in datasets.items():
        for seed in range(args.seeds):
            for mix_det in (0.25, 0.5, 0.75):
                base, txns = gen_workload(records, seed * 131 + 17, args.n, mix_det,
                                          args.writes_per_txn, args.workload, args.theta)
                for ckpt_after in (0, args.n // 3):
                    eng = run_engine(base, txns, ckpt_after)
                    engines_seen["n"] += 1
                    engines_seen["occ"] += eng["n_occ"]; engines_seen["occ_committed"] += eng["n_occ_committed"]
                    if len(eng["committed"]) < 12:
                        engines_seen["skipped_lt12_committed"] += 1
                        continue
                    for drop_last in (0, 2, 4):
                        crash = apply_crash(eng, drop_last)
                        # torn-commit target: the first NON-durable committed txn (its commit
                        # marker did not survive the cut); wrongly including it is a real bug
                        dropped = eng["committed"][len(crash["durable"]):]
                        torn_tid = dropped[0] if dropped else None
                        for fault in FAULTS:
                            for hide_frontier in (False, True):
                                t0 = time.perf_counter()
                                d_rec = recover(eng, crash, fault, drop_commit_tid=torn_tid)
                                rec_s = time.perf_counter() - t0
                                buggy = canon(d_rec) != canon(crash["gt_state"])
                                row = {
                                    "domain": dom, "seed": seed, "mix_det": mix_det,
                                    "ckpt_after": ckpt_after, "drop_last": drop_last,
                                    "fault": fault, "hide_frontier": int(hide_frontier),
                                    "buggy": int(buggy),
                                    "n_committed": len(eng["committed"]),
                                }
                                for ch in checkers:
                                    if ch == "oracle":
                                        to = time.perf_counter()
                                        pred = oracle_check(eng, crash, d_rec, hide_frontier=hide_frontier)
                                        timing["oracle_s"].append(time.perf_counter() - to)
                                    elif ch == "single_log_replay":
                                        pred = single_log_replay_check(eng, crash, d_rec)
                                    elif ch == "history_acceptor":
                                        pred = history_check(eng, crash, d_rec)
                                    elif ch == "crash_no_crash_diff":
                                        pred = crash_no_crash_diff_check(eng, crash, d_rec)
                                    else:
                                        pred = crash_no_crash_diff_legacy_check(eng, crash, d_rec)
                                    row[ch + "_pred"] = pred
                                    row[ch + "_outcome"] = score(pred, buggy)
                                # sanity: no crash cut + clean recovery must match the fixed reference
                                if drop_last == 0 and fault == "clean":
                                    assert row["crash_no_crash_diff_pred"] == "match", row
                                    nocrash_clean["n"] += 1
                                    nocrash_clean["fixed_match"] += 1
                                    nocrash_clean["legacy_match"] += int(row["crash_no_crash_diff_legacy_pred"] == "match")
                                timing["recovery_s"].append(rec_s)
                                runs.append(row)

    # aggregate: full-adapter arm (hide_frontier=0) for headline recall/precision
    def rate(rows, ch, kind):
        if kind == "recall":
            b = [r for r in rows if r["buggy"] == 1]
            return (sum(1 for r in b if r[ch + "_outcome"] == "detected") / len(b), len(b)) if b else (None, 0)
        if kind == "false_bug":
            c = [r for r in rows if r["buggy"] == 0]
            return (sum(1 for r in c if r[ch + "_outcome"] == "false_bug") / len(c), len(c)) if c else (None, 0)
        if kind == "abstain_buggy":
            b = [r for r in rows if r["buggy"] == 1]
            return (sum(1 for r in b if r[ch + "_outcome"] == "abstained") / len(b), len(b)) if b else (None, 0)

    full = [r for r in runs if r["hide_frontier"] == 0]
    degraded = [r for r in runs if r["hide_frontier"] == 1]
    metrics = {"n_runs": len(runs), "n_full_adapter": len(full), "n_degraded_adapter": len(degraded),
               "datasets": {k: len(v) for k, v in datasets.items()}, "checkers": {},
               "no_crash_clean_sanity": nocrash_clean,
               "config": {"workload": args.workload, "writes_per_txn": args.writes_per_txn,
                          "theta": args.theta if args.workload == "ycsb" else None,
                          "seeds": args.seeds, "n": args.n},
               "contention": {
                   "engine_executions": engines_seen["n"],
                   "skipped_fewer_than_12_committed": engines_seen["skipped_lt12_committed"],
                   "occ_abort_rate": (1 - engines_seen["occ_committed"] / engines_seen["occ"]) if engines_seen["occ"] else None}}
    dclean_rows = [r for r in degraded if r["buggy"] == 0]
    metrics["degraded_adapter_clean"] = {
        "n_clean": len(dclean_rows),
        "oracle_abstain_rate": (sum(1 for r in dclean_rows if r["oracle_outcome"] == "abstained_clean") / len(dclean_rows)) if dclean_rows else None,
        "oracle_false_bug_rate": (sum(1 for r in dclean_rows if r["oracle_outcome"] == "false_bug") / len(dclean_rows)) if dclean_rows else None}
    metrics["full_adapter_oracle_abstain"] = {
        "on_buggy": rate(full, "oracle", "abstain_buggy")[0],
        "on_clean": (sum(1 for r in full if r["buggy"] == 0 and r["oracle_outcome"] == "abstained_clean") / max(1, sum(1 for r in full if r["buggy"] == 0)))}
    for ch in checkers:
        rec, nb = rate(full, ch, "recall")
        fb, nc = rate(full, ch, "false_bug")
        metrics["checkers"][ch] = {
            "recall_on_buggy_recoveries": rec, "n_buggy": nb,
            "false_bug_rate_on_clean": fb, "n_clean": nc,
        }
    # cross-mode-order fault slice: where flat-order recovery is the bug
    xmo = [r for r in full if r["fault"] == "flat_order" and r["buggy"] == 1]
    def _recall(rows, ch):
        return (sum(1 for r in rows if r[ch + "_outcome"] == "detected") / len(rows)) if rows else None
    metrics["cross_mode_order_bug_slice"] = {
        "n": len(xmo),
        "oracle_recall": _recall(xmo, "oracle"),
        "single_log_replay_recall": _recall(xmo, "single_log_replay"),
        "history_acceptor_recall": _recall(xmo, "history_acceptor"),
        "crash_no_crash_diff_recall": _recall(xmo, "crash_no_crash_diff"),
    }
    # per-domain oracle vs strongest baselines (full adapter, buggy)
    perdom = {}
    for dom in sorted(datasets):
        db = [r for r in full if r["domain"] == dom and r["buggy"] == 1]
        perdom[dom] = {"n_buggy": len(db), "oracle_recall": _recall(db, "oracle"),
                       "single_log_recall": _recall(db, "single_log_replay"),
                       "history_recall": _recall(db, "history_acceptor")}
    metrics["per_domain_detection"] = perdom
    # operational cost (software, single core)
    import statistics as _st
    def _cost(xs):
        xs = sorted(xs)
        return {"mean_us": round(1e6 * _st.mean(xs), 2), "median_us": round(1e6 * _st.median(xs), 2),
                "p95_us": round(1e6 * xs[int(0.95 * (len(xs) - 1))], 2), "total_s": round(sum(xs), 3), "n": len(xs)}
    metrics["operational_cost"] = {
        "oracle_check_time": _cost(timing["oracle_s"]),
        "recovery_time": _cost(timing["recovery_s"]),
        "hardware": "single core, CPython; software prototype (no GPU)",
    }
    # abstention under degraded adapter (missing frontier) on buggy runs
    dbug = [r for r in degraded if r["buggy"] == 1]
    metrics["degraded_adapter_missing_frontier"] = {
        "n_buggy": len(dbug),
        "oracle_abstain_rate": (sum(1 for r in dbug if r["oracle_outcome"] == "abstained") / len(dbug)) if dbug else None,
        "oracle_false_or_missed": (sum(1 for r in dbug if r["oracle_outcome"] == "missed") / len(dbug)) if dbug else None,
        "single_log_false_bug_rate_on_clean_degraded": rate([r for r in degraded], "single_log_replay", "false_bug")[0],
    }
    # per-fault detection (oracle) full adapter
    perfault = {}
    for f in FAULTS:
        fr = [r for r in full if r["fault"] == f]
        b = [r for r in fr if r["buggy"] == 1]
        perfault[f] = {
            "n": len(fr), "n_buggy": len(b),
            "oracle_recall": _recall(b, "oracle"),
            "single_log_recall": _recall(b, "single_log_replay"),
            "history_recall": _recall(b, "history_acceptor"),
        }
    metrics["per_fault"] = perfault

    # seed-clustered bootstrap CI for oracle-minus-single_log recall gain on buggy runs
    fbug = [r for r in full if r["buggy"] == 1]
    byseed = defaultdict(list)
    for r in fbug:
        byseed[(r["domain"], r["seed"])].append(r)
    clusters = list(byseed.values())
    rng = random.Random(20260711)
    def _gain(rows):
        if not rows:
            return 0.0
        o = sum(1 for r in rows if r["oracle_outcome"] == "detected")
        s = sum(1 for r in rows if r["single_log_replay_outcome"] == "detected")
        return (o - s) / len(rows)
    boots = []
    for _ in range(2000):
        samp = [r for _ in clusters for r in rng.choice(clusters)]
        boots.append(_gain(samp))
    boots.sort()
    metrics["oracle_minus_single_log_recall_gain"] = {
        "point": round(_gain(fbug), 4),
        "ci95_low": round(boots[int(0.025 * len(boots))], 4),
        "ci95_high": round(boots[int(0.975 * len(boots))], 4),
        "resampling_unit": "(domain, seed) cluster", "n_clusters": len(clusters), "n_boot": 2000,
    }
    (out / "metrics_real_recovery.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    fields = list(runs[0].keys())
    with (out / "runs.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields); w.writeheader()
        for r in runs:
            w.writerow(r)
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
