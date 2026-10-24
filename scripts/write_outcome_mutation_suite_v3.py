#!/usr/bin/env python3
"""Constructed mutation suite, v2: same 4,800-cell grid and M0-M9 recovery mutations as
write_outcome_paper_level.py (v1), but every checker is a real procedure.

What changed relative to v1
  v1 scored each baseline with a formula over the fault name and a hash (e.g. checksum =
  hash % 3 == 0) and scored the proposed oracle as `diff > 0`, i.e. the label itself.
  v2 removes all of that. For each cell an engine-side writer emits durable artifacts
  (per-stream logs with LSNs, redo, validation and commit markers, cross-stream order
  metadata, checkpoint, crash-cut torn tail). The recovery under test replays the mutated
  transaction list and yields a recovered state plus an applied-record trace. Each checker
  reads only the artifacts, the pre-workload base state and the recovered state (the two
  no-crash checkers additionally get the live schedule, as their definition requires).
  No checker reads the mutation name, the label, or a hash.

Workload, state model, mutations and grid enumeration are copied verbatim from v1 so cell
ids line up. Ground truth label: a cell is non-equivalent iff the recovered state differs
from the engine-side replay of the durable committed prefix.

--crash-cut none     durable prefix = whole live schedule (labels identical to v1)
--crash-cut stratum  the crash cuts the schedule at a seed/stratum-derived point (28..35
                     of 36 txns) and leaves a torn record shaped by the crash stratum
"""
from __future__ import annotations

import argparse, csv, hashlib, json, math, os, random, sqlite3, sys, time
from collections import defaultdict
from pathlib import Path

SEEDS = [2026062803, 2026062804, 2026062805, 2026062806, 2026062807, 2026062808, 2026062809, 2026062810]
ENGINE_FAMILIES = ["hybrid_dual_log", "deterministic_batch", "occ_mvcc_per_thread_log", "weak_marker_stressor"]
MUTATIONS = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]
NEGATIVE_MUTATIONS = ["M0", "M9"]
CRASH_STRATA = ["redo_append", "validation_marker", "commit_marker", "checkpoint_write", "checkpoint_truncation"]
MIX_RATIOS = [0.0, 0.25, 0.50, 0.75]
MOD = 100000
CHECKPOINT_AFTER = 12
WRITE_MODEL = "overwrite"   # v3: "arith" reproduces v2 exactly; "overwrite" makes writes non-commutative
CHECKERS = ["oracle", "single_log_flat_replay", "checksum_flat_replay", "history_acceptor",
            "log_sanity_artifacts", "log_sanity_trace", "crash_no_crash_diff", "writecheck_no_crash"]


# ----------------------- copied verbatim from v1 (workload + mutations) -----------------------

def stable_int(text):
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def quoted(name):
    return '"' + name.replace('"', '""') + '"'


def table_names(con):
    rows = con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall()
    return [str(row[0]) for row in rows]


def row_value(row):
    total = 0.0
    seen = False
    for value in row:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            total += abs(float(value))
            seen = True
        elif isinstance(value, bytes):
            total += len(value)
        elif isinstance(value, str):
            total += len(value.strip())
    if not seen and total <= 0:
        return None
    return int(total * 100) % 100000


def load_sqlite_domain(path, domain):
    con = sqlite3.connect(str(path))
    records = []
    try:
        for table in table_names(con):
            try:
                rows = con.execute("select * from %s limit 180" % quoted(table)).fetchall()
            except Exception:
                continue
            for idx, row in enumerate(rows):
                value = row_value(row)
                if value is None:
                    continue
                records.append({"key": "%s:%s:%03d" % (domain, table, idx), "family": table, "value": max(1, value)})
            if len(records) >= 420:
                break
    finally:
        con.close()
    return records


def load_job_domain(root):
    files = sorted((root / "queries").glob("*.sql"))
    if not files:
        files = sorted(root.glob("**/*.sql"))
    records = []
    for idx, path in enumerate(files[:160]):
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        joins = text.count(" join ") + text.count(",")
        preds = text.count(" and ") + text.count(" or ") + text.count("=") + text.count(" like ")
        tables = text.count(" from ") + text.count(" join ")
        value = (joins * 101 + preds * 37 + tables * 53 + len(text)) % 100000
        records.append({"key": "job_queries:%s" % path.stem, "family": "job_sql", "value": max(1, value)})
    return records


def build_transactions(records, seed, mix_ratio, engine_family, length):
    rng = random.Random(seed + stable_int(engine_family))
    keys = [r["key"] for r in records]
    if len(keys) < 12:
        return []
    hot = keys[:6]
    txs = []
    for i in range(36):
        mode = "calvin" if rng.random() < mix_ratio else "occ"
        if i in (0, 2, 4):
            mode = "calvin"
        if i in (1, 3, 5):
            mode = "occ"
        key = hot[i % len(hot)] if i < 12 else rng.choice(keys)
        base = records[stable_int(key) % len(records)]["value"]
        writes = []
        for j in range(length):
            wkey = key if j == 0 else rng.choice(keys)
            delta = ((base + seed + i * 19 + j * 7) % 31) - 15
            if delta == 0:
                delta = 3
            factor = 1
            if engine_family in {"hybrid_dual_log", "weak_marker_stressor"} and i < 8 and j == 0:
                factor = 2 + (i % 2)
            writes.append({"key": wkey, "delta": delta, "factor": factor})
        txs.append({"tx_id": "tx%02d" % i, "mode": mode, "writes": writes})
    return txs


def apply_txs(initial, txs):
    state = dict(initial)
    for tx in txs:
        for write in tx["writes"]:
            old = state.get(write["key"], 0)
            state[write["key"]] = int((old * write["factor"] + write["delta"]) % 100000)
    return state


def initial_state(records, seed, scale):
    rng = random.Random(seed)
    rows = list(records)
    rng.shuffle(rows)
    n = min(len(rows), max(32, scale))
    return {row["key"]: int(row["value"]) for row in rows[:n]}


def mutate_txs(txs, mutation, stratum):
    mutated = [dict(tx, writes=[dict(w) for w in tx["writes"]]) for tx in txs]
    if mutation == "M1":
        for i in range(len(mutated) - 1):
            if mutated[i]["mode"] != mutated[i + 1]["mode"] and mutated[i]["writes"][0]["key"] == mutated[i + 1]["writes"][0]["key"]:
                mutated[i], mutated[i + 1] = mutated[i + 1], mutated[i]
                return mutated
        mutated[0], mutated[1] = mutated[1], mutated[0]
    elif mutation == "M2":
        return mutated[:-1] if stratum in {"commit_marker", "checkpoint_truncation"} else mutated + [mutated[-1]]
    elif mutation == "M3":
        return [tx for tx in mutated if not (tx["mode"] == "occ" and tx["tx_id"] in {"tx01", "tx03", "tx05"})]
    elif mutation == "M4":
        return mutated[4:] + mutated[:4]
    elif mutation == "M5":
        return mutated[:24]
    elif mutation == "M6":
        return mutated + [mutated[6], mutated[7]]
    elif mutation == "M7":
        return [tx for tx in mutated if tx["tx_id"] not in {"tx02", "tx04"}]
    elif mutation == "M8":
        for tx in mutated[:8]:
            for write in tx["writes"]:
                write["factor"] = max(1, write["factor"] - 1)
    elif mutation in NEGATIVE_MUTATIONS:
        return mutated
    return mutated


def diff_count(left, right):
    keys = set(left) | set(right)
    return sum(1 for key in keys if left.get(key) != right.get(key))


# ----------------------- engine side: durable artifacts (independent of the mutation) -----------------------

def crash_cut(mode, n, domain, engine, seed, stratum):
    if mode == "none":
        return n
    return 28 + stable_int("cut:%s:%s:%s:%s" % (domain, engine, seed, stratum)) % 8


def write_artifacts(live, k, stratum, engine, seed, init):
    """Emit what a crash at cut k leaves on disk. Uses the live schedule only."""
    durable = live[:k]
    logs = defaultdict(list)
    lsn = defaultdict(int)

    def log_of(tx, idx):
        if tx["mode"] == "calvin":
            return "det"
        return "occ_t%d" % (idx % 3) if engine == "occ_mvcc_per_thread_log" else "occ"

    prev = "^"
    for gi, tx in enumerate(durable):
        name = log_of(tx, gi)
        lsn[name] += 1
        rec = {"log": name, "lsn": lsn[name], "tid": tx["tx_id"], "mode": tx["mode"],
               "writes": [dict(w) for w in tx["writes"]], "commit": True}
        if tx["mode"] == "occ":
            rec["validated"] = True
        if engine == "deterministic_batch":
            rec["gseq"] = gi                      # batch sequence number
        elif engine == "occ_mvcc_per_thread_log":
            rec["cts"] = gi                       # commit timestamp
        else:
            rec["pred"] = prev                    # cross-stream predecessor pointer
            if engine == "weak_marker_stressor" and stable_int("weak:%s:%s:%s" % (seed, stratum, tx["tx_id"])) % 3 == 0:
                del rec["pred"]                   # marker not persisted
        logs[name].append(rec)
        prev = tx["tx_id"]

    # torn tail: the in-flight transaction at the crash point
    if k < len(live) and stratum in {"redo_append", "validation_marker", "commit_marker"}:
        tx = live[k]
        name = log_of(tx, k)
        lsn[name] += 1
        rec = {"log": name, "lsn": lsn[name], "tid": tx["tx_id"], "mode": tx["mode"], "commit": False,
               "writes": [dict(w) for w in tx["writes"]]}
        if stratum == "redo_append":
            rec["writes"] = rec["writes"][: len(rec["writes"]) // 2]
        if stratum == "commit_marker" and tx["mode"] == "occ":
            rec["validated"] = True
        logs[name].append(rec)

    ckpt = None
    if stratum in {"checkpoint_write", "checkpoint_truncation"} and k > CHECKPOINT_AFTER:
        included = [tx["tx_id"] for tx in durable[:CHECKPOINT_AFTER]]
        state = apply_txs(init, durable[:CHECKPOINT_AFTER])
        if stratum == "checkpoint_write":
            keys = sorted(state)
            ckpt = {"valid": False, "included": included, "state": {x: state[x] for x in keys[: len(keys) // 2]}}
        else:
            inc = set(included)
            wm = {}
            for name in list(logs):
                kept = [r for r in logs[name] if r["tid"] not in inc]
                gone = [r["lsn"] for r in logs[name] if r["tid"] in inc]
                wm[name] = max(gone) if gone else 0
                logs[name] = kept
            ckpt = {"valid": True, "included": included, "state": state, "watermarks": wm}
    return {"engine": engine, "logs": {n: rs for n, rs in logs.items()}, "checkpoint": ckpt}


# ----------------------- checkers (read artifacts + base + recovered state only) -----------------------

def all_records(art):
    return [r for rs in art["logs"].values() for r in rs]


def committed_records(art):
    return [r for r in all_records(art) if r.get("commit") and (r["mode"] != "occ" or r.get("validated"))]


def base_state(art, init):
    ck = art["checkpoint"]
    return dict(ck["state"]) if ck and ck.get("valid") else dict(init)


def replay(base, recs):
    return apply_txs(base, [{"writes": r["writes"]} for r in recs])


def verdict(ref, recovered):
    return "match" if diff_count(ref, recovered) == 0 else "mismatch"


def recs_commute(a, b):
    by_key = defaultdict(list)
    for w in a["writes"]:
        by_key[w["key"]].append(w["factor"])
    for w in b["writes"]:
        fs = by_key.get(w["key"])
        if fs is not None and (w["factor"] != 1 or any(f != 1 for f in fs)):
            return False
    return True


def oracle_order(art, recs):
    """Durable global order from the engine's order metadata; None when the metadata leaves
    an outcome-relevant (non-commuting) cross-log pair unordered."""
    if all("gseq" in r for r in recs):
        return sorted(recs, key=lambda r: r["gseq"])
    if all("cts" in r for r in recs):
        return sorted(recs, key=lambda r: r["cts"])
    idx = {r["tid"]: i for i, r in enumerate(recs)}
    n = len(recs)
    succ = [set() for _ in range(n)]
    for rs in art["logs"].values():
        chain = sorted([r for r in rs if r["tid"] in idx], key=lambda r: r["lsn"])
        for a, b in zip(chain, chain[1:]):
            succ[idx[a["tid"]]].add(idx[b["tid"]])
    for r in recs:
        p = r.get("pred")
        if p is not None and p in idx:
            succ[idx[p]].add(idx[r["tid"]])
    reach = [0] * n
    indeg = [0] * n
    for a in range(n):
        for b in succ[a]:
            indeg[b] += 1
    order = []
    ready = sorted([i for i in range(n) if indeg[i] == 0], key=lambda i: (recs[i]["log"], recs[i]["lsn"]))
    indeg2 = list(indeg)
    while ready:
        a = ready.pop(0)
        order.append(a)
        for b in sorted(succ[a]):
            indeg2[b] -= 1
            if indeg2[b] == 0:
                ready.append(b)
        ready.sort(key=lambda i: (recs[i]["log"], recs[i]["lsn"]))
    if len(order) != n:
        return None
    for a in reversed(order):
        m = 0
        for b in succ[a]:
            m |= (1 << b) | reach[b]
        reach[a] = m
    for a in range(n):
        for b in range(a + 1, n):
            if recs[a]["log"] == recs[b]["log"]:
                continue
            if (reach[a] >> b) & 1 or (reach[b] >> a) & 1:
                continue
            if not recs_commute(recs[a], recs[b]):
                return None
    return [recs[i] for i in order]


def check_oracle(art, init, recovered):
    recs = committed_records(art)
    order = oracle_order(art, recs)
    if order is None:
        return "uncertain"
    return verdict(replay(base_state(art, init), order), recovered)


def check_single_log(art, init, recovered):
    recs = sorted(committed_records(art), key=lambda r: (r["lsn"], r["log"]))
    return verdict(replay(base_state(art, init), recs), recovered)


def table_of(key):
    return key.rsplit(":", 1)[0]


def table_digests(state):
    per = defaultdict(list)
    for k, v in state.items():
        per[table_of(k)].append((k, int(v)))
    return {t: hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest() for t, rows in per.items()}


def check_checksum(art, init, recovered):
    """Marker-blind tool: replays every redo record present, flat LSN order, from the
    pre-workload state, then compares per-table digests."""
    recs = sorted(all_records(art), key=lambda r: (r["lsn"], r["log"]))
    return "match" if table_digests(replay(init, recs)) == table_digests(recovered) else "mismatch"


def affine_of(writes, key):
    f, d = 1, 0
    for w in writes:
        if w["key"] == key:
            f, d = (f * w["factor"]) % MOD, (d * w["factor"] + w["delta"]) % MOD
    return f, d


def key_reachable(base_val, maps, target):
    """Is target reachable by applying the affine maps (one per member txn) in SOME order?"""
    units = [d for f, d in maps if f == 1]
    nonunits = [(f, d) for f, d in maps if f != 1]
    if not nonunits:
        return (base_val + sum(units)) % MOD == target % MOD
    if not units and all(f == 0 for f, _ in nonunits):
        # pure overwrites: the last writer decides, so any member's after-image is reachable
        return target % MOD in {d % MOD for _, d in nonunits}
    m = len(nonunits)
    if m > 4 or (m + 1) ** len(units) > 200000:
        return None
    slots = {tuple([0] * (m + 1))}
    for d in units:
        nxt = set()
        for s in slots:
            for j in range(m + 1):
                t = list(s); t[j] = (t[j] + d) % MOD
                nxt.add(tuple(t))
        slots = nxt
    import itertools
    for perm in set(itertools.permutations(nonunits)):
        for s in slots:
            v = (base_val + s[0]) % MOD
            for j, (f, d) in enumerate(perm):
                v = (v * f + d + s[j + 1]) % MOD
            if v == target % MOD:
                return True
    return False


def check_history(art, init, recovered):
    """Order-blind acceptor: same durable membership and base as the oracle; accepts iff
    every key's recovered value is produced by some ordering of the members writing it
    (per-key necessary condition for the existence of a serialization)."""
    recs = committed_records(art)
    base = base_state(art, init)
    per_key = defaultdict(list)
    for r in recs:
        for key in {w["key"] for w in r["writes"]}:
            per_key[key].append(affine_of(r["writes"], key))
    unknown = False
    for key in set(base) | set(recovered) | set(per_key):
        got = recovered.get(key)
        if key not in per_key:
            if got != base.get(key):
                return "mismatch"
            continue
        if got is None:
            return "mismatch"
        ok = key_reachable(base.get(key, 0), per_key[key], got)
        if ok is None:
            unknown = True
        elif not ok:
            return "mismatch"
    return "uncertain" if unknown else "match"


def check_log_sanity_artifacts(art):
    """Structural checks on the durable artifacts only; no replay, no recovered state."""
    ck = art["checkpoint"]
    included = set(ck["included"]) if ck and ck.get("valid") else set()
    wm = (ck or {}).get("watermarks", {}) if ck and ck.get("valid") else {}
    seen = set()
    tids = {r["tid"] for r in all_records(art)}
    for name, rs in art["logs"].items():
        expect = wm.get(name, 0) + 1
        for r in sorted(rs, key=lambda r: r["lsn"]):
            if r["lsn"] != expect:
                return "mismatch"                       # gap / non-monotone LSN
            expect += 1
            if r["tid"] in seen:
                return "mismatch"                       # duplicate redo
            seen.add(r["tid"])
            if r.get("commit") and not r["writes"]:
                return "mismatch"                       # commit without redo
            if r.get("commit") and r["mode"] == "occ" and not r.get("validated"):
                return "mismatch"                       # occ commit without validation
            p = r.get("pred")
            if p is not None and p != "^" and p not in tids and p not in included:
                return "mismatch"                       # dangling predecessor
        if rs and not all(r.get("commit") for r in sorted(rs, key=lambda r: r["lsn"])[:-1]):
            return "mismatch"                           # uncommitted record that is not the tail
    return "match"


def check_log_sanity_trace(art, trace):
    """Structural checks on the recovery's applied-record trace against the artifacts; no
    replay, no state. Flags duplicates, non-committed applies, omitted commits and
    within-log LSN inversions."""
    ck = art["checkpoint"]
    included = set(ck["included"]) if ck and ck.get("valid") else set()
    committed = {r["tid"]: r for r in committed_records(art)}
    if len(set(trace)) != len(trace):
        return "mismatch"
    for tid in trace:
        if tid not in committed and tid not in included:
            return "mismatch"
    if any(tid not in set(trace) for tid in committed):
        return "mismatch"
    last = {}
    for tid in trace:
        r = committed.get(tid)
        if r is None:
            continue
        if r["lsn"] < last.get(r["log"], 0):
            return "mismatch"
        last[r["log"]] = r["lsn"]
    return "match"


def check_crash_no_crash(init, live, recovered):
    """Differential against the no-crash run's final state (whole live schedule)."""
    return verdict(apply_txs(init, live), recovered)


def check_writecheck_no_crash(init, live):
    """WriteCheck-style: run the workload WITHOUT a crash and compare the engine's final
    state to a serial replay of its commit order. It never observes recovery."""
    engine_final = apply_txs(init, live)
    serial = dict(init)
    for tx in live:
        serial = apply_txs(serial, [tx])
    return verdict(serial, engine_final)


# ----------------------- driver -----------------------

def score_cell(domain, records, engine, mutation, seed, stratum, mix, length, scale, contention, cut_mode):
    init = initial_state(records, seed + stable_int(domain + engine), scale)
    live = build_transactions(records, seed, mix, engine, length)
    if not live:
        return None
    if WRITE_MODEL == "overwrite":
        # v3: every write is a blind overwrite with a per-(txn, write) after-image. Encoded as
        # the affine map v -> 0*v + after, so replay, commutativity (factor != 1 means the
        # pair does not commute) and the history acceptor need no other change.
        for i, tx in enumerate(live):
            for j, w in enumerate(tx["writes"]):
                w["factor"] = 0
                w["delta"] = (stable_int(w["key"]) + seed * 31 + i * 1009 + j * 97) % MOD
    k = crash_cut(cut_mode, len(live), domain, engine, seed, stratum)
    art = write_artifacts(live, k, stratum, engine, seed, init)
    durable = live[:k]
    truth = apply_txs(init, durable)                     # engine-side ground truth
    replayed = mutate_txs(durable, mutation, stratum)    # recovery under test
    recovered = apply_txs(init, replayed)
    trace = [tx["tx_id"] for tx in replayed]
    diff = diff_count(truth, recovered)
    t0 = time.perf_counter()
    o = check_oracle(art, init, recovered)
    oracle_s = time.perf_counter() - t0
    row = {
        "cell_id": "%s_%s_%s_%s_%s_%s_%s_%s" % (domain, engine, mutation, seed, stratum, mix, length, scale),
        "domain": domain, "engine_family": engine, "mutation": mutation, "seed": seed,
        "crash_stratum": stratum, "mix_ratio": mix, "tx_length": length, "scale": scale,
        "contention": contention, "crash_cut": k, "diff_count": diff,
        "non_equivalent": int(diff > 0),
        "oracle": o,
        "single_log_flat_replay": check_single_log(art, init, recovered),
        "checksum_flat_replay": check_checksum(art, init, recovered),
        "history_acceptor": check_history(art, init, recovered),
        "log_sanity_artifacts": check_log_sanity_artifacts(art),
        "log_sanity_trace": check_log_sanity_trace(art, trace),
        "crash_no_crash_diff": check_crash_no_crash(init, live, recovered),
        "writecheck_no_crash": check_writecheck_no_crash(init, live),
        "oracle_check_us": round(1e6 * oracle_s, 2),
    }
    return row


def summarize(rows):
    def block(sub):
        ne = [r for r in sub if r["non_equivalent"]]
        eq = [r for r in sub if not r["non_equivalent"]]
        out = {"n_non_equivalent": len(ne), "n_equivalent": len(eq)}
        for ch in CHECKERS:
            out[ch] = {
                "coverage_non_equivalent": (sum(r[ch] == "mismatch" for r in ne) / len(ne)) if ne else None,
                "uncertain_non_equivalent": (sum(r[ch] == "uncertain" for r in ne) / len(ne)) if ne else None,
                "missed_non_equivalent": sum(r[ch] == "match" for r in ne),
                "false_report_equivalent": (sum(r[ch] == "mismatch" for r in eq) / len(eq)) if eq else None,
                "uncertain_equivalent": (sum(r[ch] == "uncertain" for r in eq) / len(eq)) if eq else None,
            }
        return out
    res = {"overall": block(rows)}
    for field in ("mutation", "engine_family", "domain", "crash_stratum"):
        res["by_" + field] = {v: block([r for r in rows if r[field] == v]) for v in sorted({r[field] for r in rows})}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--crash-cut", choices=["none", "stratum"], default="stratum")
    ap.add_argument("--write-model", choices=["arith", "overwrite"], default="overwrite")
    args = ap.parse_args(argv)
    global WRITE_MODEL
    WRITE_MODEL = args.write_model
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    paths = {
        "chinook_sqlite": os.environ.get("RESEARCHOS_DATASET_CHINOOK_SQLITE", ""),
        "northwind_sqlite": os.environ.get("RESEARCHOS_DATASET_NORTHWIND_SQLITE", ""),
        "job_queries": os.environ.get("RESEARCHOS_DATASET_JOB_QUERIES", ""),
    }
    missing = [k for k, v in paths.items() if not v or not Path(v).exists()]
    if missing:
        print(json.dumps({"error": "datasets unavailable", "missing": missing})); return 1
    domains = {
        "chinook_sqlite": load_sqlite_domain(Path(paths["chinook_sqlite"]), "chinook_sqlite"),
        "northwind_sqlite": load_sqlite_domain(Path(paths["northwind_sqlite"]), "northwind_sqlite"),
        "job_queries": load_job_domain(Path(paths["job_queries"])),
    }

    t_start = time.perf_counter()
    cells = []
    # enumeration order copied from v1 (mix depends on len(cells))
    for domain, records in domains.items():
        for engine in ENGINE_FAMILIES:
            for seed in SEEDS:
                for stratum in CRASH_STRATA:
                    for mutation in MUTATIONS:
                        mix = MIX_RATIOS[(stable_int(domain + engine + str(seed)) + len(cells)) % len(MIX_RATIOS)]
                        length = [1, 3, 5, 8][stable_int(mutation + engine) % 4]
                        scale = [64, 128, 256][stable_int(domain + str(seed)) % 3]
                        contention = ["low", "medium", "high"][stable_int(stratum + mutation) % 3]
                        cell = score_cell(domain, records, engine, mutation, seed, stratum, mix, length, scale, contention, args.crash_cut)
                        if cell:
                            cells.append(cell)
                    for mutation in NEGATIVE_MUTATIONS:
                        cell = score_cell(domain, records, engine, mutation, seed, stratum, 0.5, 3, 128, "medium", args.crash_cut)
                        if cell:
                            cells.append(cell)
    wall = time.perf_counter() - t_start

    metrics = {"crash_cut_mode": args.crash_cut, "write_model": args.write_model, "n_cells": len(cells), "wall_s": round(wall, 2),
               "domain_records": {k: len(v) for k, v in domains.items()},
               "dataset_paths": paths, "checkers": CHECKERS}
    metrics.update(summarize(cells))
    us = sorted(r["oracle_check_us"] for r in cells)
    metrics["oracle_check_us"] = {"mean": round(sum(us) / len(us), 2), "median": us[len(us) // 2], "p95": us[int(0.95 * (len(us) - 1))]}
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    with (out / "cell_results.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cells[0].keys())); w.writeheader()
        for r in cells:
            w.writerow(r)

    def pct(x):
        return "n/a" if x is None else "%.1f" % (100 * x)
    lines = ["# Mutation suite v3 (%s writes, %s crash cut): %d cells, %d non-equivalent, %d equivalent" % (
        args.write_model, args.crash_cut, len(cells), metrics["overall"]["n_non_equivalent"], metrics["overall"]["n_equivalent"]), "",
        "| checker | coverage on non-equivalent % | uncertain on non-equivalent % | false report on equivalent % | uncertain on equivalent % |",
        "| --- | ---: | ---: | ---: | ---: |"]
    for ch in CHECKERS:
        b = metrics["overall"][ch]
        lines.append("| %s | %s | %s | %s | %s |" % (ch, pct(b["coverage_non_equivalent"]), pct(b["uncertain_non_equivalent"]),
                                                    pct(b["false_report_equivalent"]), pct(b["uncertain_equivalent"])))
    lines += ["", "## Coverage on non-equivalent cells by mutation (%; n in header)", "",
              "| checker | " + " | ".join("%s (n=%d)" % (m, metrics["by_mutation"][m]["n_non_equivalent"]) for m in MUTATIONS) + " |",
              "| --- | " + " | ".join("---:" for _ in MUTATIONS) + " |"]
    for ch in CHECKERS:
        lines.append("| %s | " % ch + " | ".join(pct(metrics["by_mutation"][m][ch]["coverage_non_equivalent"]) for m in MUTATIONS) + " |")
    allm = MUTATIONS + NEGATIVE_MUTATIONS
    lines += ["", "## False report on equivalent cells by mutation (%; n in header)", "",
              "| checker | " + " | ".join("%s (n=%d)" % (m, metrics["by_mutation"][m]["n_equivalent"]) for m in allm) + " |",
              "| --- | " + " | ".join("---:" for _ in allm) + " |"]
    for ch in CHECKERS:
        lines.append("| %s | " % ch + " | ".join(pct(metrics["by_mutation"][m][ch]["false_report_equivalent"]) for m in allm) + " |")
    (out / "tables.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
