#!/usr/bin/env python3
"""Automatic mutation of the recovery code as an independent fault source.

The five hand-written recovery faults in v1-v5 were chosen by the authors of the oracle. Here
the faults are generated mechanically: the correct recovery procedure (RECOVERY_SRC below,
behaviourally identical to v5's correct on-disk recovery; this is checked before mutating) is
parsed with `ast`, and every applicable site receives one syntactic mutation:

  cmp      swap a comparison operator (<= / <, == / !=, in / not in, ...)
  bool     swap `and` / `or`
  not      drop a `not`
  if       force an `if` condition to True or to False
  const    integer constant +1 / -1; swap the strings "det" / "occ"
  key      swap one record-field name for another of the same kind
  del      delete a statement (append call or assignment)
  sorted   reverse a sort
  binop    keep only the left or only the right operand of `+`

Each mutant recovers every crash scenario. Ground truth decides, per (mutant, scenario),
whether the recovered state is wrong. A mutant is non-equivalent on this test set if it is
wrong (or raises) on at least one scenario. The oracle (v4 semantics, full metadata),
single-log flat replay and the history acceptor then judge each recovered state without
knowing which mutant produced it.
"""
from __future__ import annotations
import argparse, ast, copy, json, os, sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import real_recovery_prototype_v3 as p3
import real_recovery_prototype_v5 as p5
import scale_study as ss

RECOVERY_SRC = '''
def is_member(e):
    return e["commit"] and (e["mode"] == "det" or e["validated"])

def durable_order(members):
    det = sorted([e for e in members if e["mode"] == "det"], key=lambda e: e["det_pos"])
    occ = sorted([e for e in members if e["mode"] == "occ"], key=lambda e: e["occ_seq"])
    out = []
    used = 0
    for o in occ:
        for d in det[used:]:
            if d["det_pos"] <= o["det_frontier"]:
                out.append(d)
                used = used + 1
        out.append(o)
    return out + det[used:]

def recover(disk, initial):
    ents = disk["entries"]
    ck = disk["checkpoint"]
    members = [e for e in ents if is_member(e)]
    order = durable_order(members)
    if ck:
        inc = set(ck["included"])
        base = ck["state"]
        order = [e for e in order if e["tid"] not in inc]
    else:
        base = initial
    state = dict(base)
    for e in order:
        for wk, af in e["writes"]:
            state[wk] = af
    return state
'''

CMP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
       ast.In: ast.NotIn, ast.NotIn: ast.In}
KEYSWAP = {"det_pos": "occ_frontier", "occ_seq": "det_frontier", "det_frontier": "occ_seq",
           "commit": "validated", "validated": "commit", "entries": None, "checkpoint": None}


def enumerate_mutants(src):
    """Yields (operator, description, mutated source)."""
    tree = ast.parse(src)
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and type(node.ops[0]) in CMP:
            sites.append(("cmp", node, None))
        elif isinstance(node, ast.BoolOp):
            sites.append(("bool", node, None))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            sites.append(("not", node, None))
        elif isinstance(node, ast.If):
            sites.append(("if", node, True)); sites.append(("if", node, False))
        elif isinstance(node, ast.comprehension):
            for k in range(len(node.ifs)):
                sites.append(("if", node, ("drop", k)))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            pass
        elif isinstance(node, ast.Constant) and isinstance(node.value, int):
            sites.append(("const", node, +1)); sites.append(("const", node, -1))
        elif isinstance(node, ast.Constant) and node.value in ("det", "occ"):
            sites.append(("const", node, "swap"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and KEYSWAP.get(node.value):
            sites.append(("key", node, KEYSWAP[node.value]))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sorted":
            sites.append(("sorted", node, None))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            sites.append(("binop", node, "left")); sites.append(("binop", node, "right"))
    for fn in tree.body:
        for parent in ast.walk(fn):
            body = getattr(parent, "body", None)
            if not isinstance(body, list):
                continue
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                    sites.append(("del", stmt, None))
                elif isinstance(stmt, ast.Assign) and isinstance(parent, (ast.For, ast.If)):
                    sites.append(("del", stmt, None))
    index = {id(n): i for i, n in enumerate(ast.walk(tree))}
    for op, node, arg in sites:
        t = copy.deepcopy(tree)
        target = list(ast.walk(t))[index[id(node)]]
        line = getattr(node, "lineno", 0)
        if op == "cmp":
            desc = "%s -> %s" % (type(target.ops[0]).__name__, CMP[type(target.ops[0])].__name__)
            target.ops[0] = CMP[type(target.ops[0])]()
        elif op == "bool":
            desc = "and <-> or"
            target.op = ast.Or() if isinstance(target.op, ast.And) else ast.And()
        elif op == "not":
            desc = "drop not"
            target.op = ast.UAdd() if False else target.op
            _replace(t, target, target.operand)
        elif op == "if" and isinstance(arg, tuple):
            desc = "drop comprehension filter %d" % arg[1]
            del target.ifs[arg[1]]
        elif op == "if":
            desc = "if -> %s" % arg
            target.test = ast.Constant(value=arg)
        elif op == "const" and arg == "swap":
            desc = "'%s' -> '%s'" % (target.value, "occ" if target.value == "det" else "det")
            target.value = "occ" if target.value == "det" else "det"
        elif op == "const":
            desc = "%d -> %d" % (target.value, target.value + arg)
            target.value = target.value + arg
        elif op == "key":
            desc = "field '%s' -> '%s'" % (target.value, arg)
            target.value = arg
        elif op == "sorted":
            desc = "sorted(..., reverse=True)"
            target.keywords.append(ast.keyword(arg="reverse", value=ast.Constant(value=True)))
        elif op == "binop":
            desc = "a + b -> %s operand" % arg
            _replace(t, target, target.left if arg == "left" else target.right)
        elif op == "del":
            desc = "delete statement"
            _replace(t, target, ast.Pass())
        ast.fix_missing_locations(t)
        yield op, "line %d: %s" % (line, desc), ast.unparse(t)


def _replace(tree, old, new):
    for parent in ast.walk(tree):
        for field, value in ast.iter_fields(parent):
            if value is old:
                setattr(parent, field, new); return
            if isinstance(value, list):
                for i, v in enumerate(value):
                    if v is old:
                        value[i] = new; return


def load(src):
    ns = {}
    exec(compile(src, "<recovery>", "exec"), ns)
    return ns["recover"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--n", type=int, default=48)
    ap.add_argument("--keys", type=int, default=400)
    a = ap.parse_args(argv)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    configs = [("rmw", w, 0.0) for w in (1, 3, 8)] + [("ycsb", w, 0.99) for w in (1, 3, 8)]
    scenarios = []
    for workload, wpt, theta in configs:
        cfg = {"n": a.n, "keys": a.keys, "wpt": wpt, "workload": workload, "theta": theta}
        for dom in ss.ENV:
            for seed in range(a.seeds):
                for mix in (0.25, 0.5, 0.75):
                    for ck in (0, a.n // 3):
                        base, eng = ss.build(cfg, dom, seed, mix, ck)
                        if len(eng["committed"]) < 12:
                            continue
                        for drop_last in (0, 2, 4):
                            crash = p3.apply_crash(eng, drop_last)
                            disk = ss.entries_from_engine(eng, crash)
                            scenarios.append({"cfg": "%s_w%d" % (workload, wpt), "base": base, "disk": disk,
                                              "art": p5.to_artifacts(disk, base), "truth": crash["gt_state"]})
    original = load(RECOVERY_SRC)
    same_as_v5 = sum(original(s["disk"], s["base"]) == p5.recover_from_disk(s["disk"], s["base"], "clean") for s in scenarios)
    correct = sum(original(s["disk"], s["base"]) == s["truth"] for s in scenarios)

    checkers = {"oracle": lambda s, d: ss.oracle_fast(s["art"], d),
                "single_log_replay": lambda s, d: p5.single_log_check(s["disk"], s["base"], d),
                "history_acceptor": lambda s, d: p5.history_check(s["disk"], s["base"], d)}
    mutants = []
    pair = {ch: Counter() for ch in checkers}
    for mid, (op, desc, src) in enumerate(enumerate_mutants(RECOVERY_SRC)):
        rec = {"id": mid, "operator": op, "desc": desc, "wrong": 0, "raised": 0, "ok": 0,
               **{ch + "_true_detections": 0 for ch in checkers}, **{ch + "_false_reports": 0 for ch in checkers}}
        try:
            fn = load(src)
        except Exception as exc:
            rec["status"] = "does_not_compile"; mutants.append(rec); continue
        for s in scenarios:
            try:
                d = fn(s["disk"], s["base"])
                if not isinstance(d, dict):
                    raise TypeError("recovery did not return a state")
            except Exception:
                rec["raised"] += 1
                continue
            wrong = d != s["truth"]
            rec["wrong" if wrong else "ok"] += 1
            for ch, f in checkers.items():
                try:
                    pred = f(s, d)
                except Exception:
                    pred = "precfail"
                pair[ch]["buggy" if wrong else "clean"] += 1
                if wrong:
                    pair[ch]["detected" if pred == "mismatch" else ("abstained" if pred in ("uncertain", "precfail") else "missed")] += 1
                    rec[ch + "_true_detections"] += int(pred == "mismatch")
                else:
                    pair[ch]["false_bug" if pred == "mismatch" else ("abstained_clean" if pred in ("uncertain", "precfail") else "correct")] += 1
                    rec[ch + "_false_reports"] += int(pred == "mismatch")
        rec["status"] = ("wrong_state" if rec["wrong"] else ("raises_only" if rec["raised"] else "equivalent_on_test_set"))
        mutants.append(rec)

    nonequiv = [m for m in mutants if m["status"] == "wrong_state"]
    m = {"scenarios": len(scenarios), "scenario_configs": sorted({s["cfg"] for s in scenarios}),
         "original_equals_v5_correct_recovery": same_as_v5, "original_equals_truth": correct,
         "mutants_generated": len(mutants), "status": dict(Counter(x["status"] for x in mutants)),
         "by_operator": {op: dict(Counter(x["status"] for x in mutants if x["operator"] == op)) for op in sorted({x["operator"] for x in mutants})},
         "mutants_with_wrong_state": len(nonequiv),
         "mutant_level": {ch: {"detected_at_least_once": sum(1 for x in nonequiv if x[ch + "_true_detections"] > 0),
                               "detected_on_every_wrong_scenario": sum(1 for x in nonequiv if x[ch + "_true_detections"] == x["wrong"]),
                               "mutants_with_a_false_report": sum(1 for x in mutants if x.get(ch + "_false_reports", 0) > 0)} for ch in checkers},
         "pair_level": {ch: {"buggy_pairs": pair[ch]["buggy"], "detected": pair[ch]["detected"], "missed": pair[ch]["missed"],
                             "abstained": pair[ch]["abstained"],
                             "recall": pair[ch]["detected"] / pair[ch]["buggy"] if pair[ch]["buggy"] else None,
                             "clean_pairs": pair[ch]["clean"], "false_bug": pair[ch]["false_bug"],
                             "false_bug_rate": pair[ch]["false_bug"] / pair[ch]["clean"] if pair[ch]["clean"] else None} for ch in checkers},
         "undetected_by_oracle": [x for x in nonequiv if x["oracle_true_detections"] < x["wrong"]]}
    (out / "metrics_mutation.json").write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
    (out / "mutants.json").write_text(json.dumps(mutants, indent=1) + "\n")
    print(json.dumps(m, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
