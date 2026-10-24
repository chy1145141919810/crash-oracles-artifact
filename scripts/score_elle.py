#!/usr/bin/env python3
"""Score Elle's verdicts against ground truth, next to our own checkers on the same runs.
usage: score_elle.py ROOT   (ROOT has one folder per workload with index.csv and elle_*.txt)
Elle verdict false -> reports an anomaly; true -> accepts; anything else -> no verdict."""
import csv, json, sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
CONFIGS = [("elle_cli_default", "elle-cli default (strict-serializable)"), ("elle_wfr", "Elle, wfr-keys"),
           ("elle_lin", "Elle, linearizable-keys"), ("elle_wfr_lin", "Elle, wfr-keys + linearizable-keys")]
OURS = ["oracle", "single_log_replay", "history_acceptor"]
FAULTS = ["flat_order", "ignore_validation", "torn_commit_include", "stale_checkpoint_noreapply", "truncate_suffix"]


def load(path):
    out, anoms = {}, {}
    if not path.exists():
        return None, None
    for line in path.read_text().splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2 or not parts[0].endswith(".edn"):
            continue
        out[parts[0]] = parts[1]
        anoms[parts[0]] = parts[2] if len(parts) > 2 else ""
    return out, anoms


def outcome(verdict, buggy):
    if verdict == "false":
        return "detected" if buggy else "false_bug"
    if verdict == "true":
        return "missed" if buggy else "correct_clean"
    return "abstained" if buggy else "abstained_clean"


def block(rows, col):
    b = [r for r in rows if r["buggy"] == "1"]; c = [r for r in rows if r["buggy"] == "0"]
    cb, cc = Counter(r[col] for r in b), Counter(r[col] for r in c)
    return {"recall": cb["detected"] / len(b) if b else None, "false_bug_rate": cc["false_bug"] / len(c) if c else None,
            "detected": cb["detected"], "missed": cb["missed"], "false_bug": cc["false_bug"],
            "no_verdict": cb["abstained"] + cc["abstained_clean"]}


res = {}
L = ["# Elle (rw-register) on exported client histories, next to our checkers on the same runs", ""]
for w in sorted(p for p in root.iterdir() if (p / "index.csv").exists()):
    rows = list(csv.DictReader(open(w / "index.csv", newline="")))
    cols, anom_count = list(OURS), {}
    for key, _ in CONFIGS:
        v, an = load(w / (key + ".txt"))
        if v is None:
            continue
        missing = sum(1 for r in rows if r["file"] not in v)
        for r in rows:
            r[key] = outcome(v.get(r["file"], "missing"), r["buggy"] == "1")
        cols.append(key)
        anom_count[key] = dict(Counter(an[r["file"]] for r in rows if v.get(r["file"]) == "false").most_common(6))
        anom_count[key]["_histories_without_result"] = missing
    nb = sum(r["buggy"] == "1" for r in rows)
    res[w.name] = {"n": len(rows), "n_buggy": nb, "n_clean": len(rows) - nb,
                   "checkers": {c: block(rows, c) for c in cols},
                   "per_fault_detected": {f: {"n_buggy": sum(1 for r in rows if r["fault"] == f and r["buggy"] == "1"),
                                              **{c: sum(1 for r in rows if r["fault"] == f and r[c] == "detected") for c in cols}} for f in FAULTS},
                   "elle_anomaly_types_on_reports": anom_count}
    names = dict(CONFIGS)
    f3 = lambda x: "n/a" if x is None else "%.3f" % x
    L += ["## %s: %d runs (%d buggy, %d clean)" % (w.name, len(rows), nb, len(rows) - nb), "",
          "| checker | recall | false-bug rate | detected | missed | false bugs | no verdict |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for c in cols:
        b = res[w.name]["checkers"][c]
        L.append("| %s | %s | %s | %d | %d | %d | %d |" % (names.get(c, c), f3(b["recall"]), f3(b["false_bug_rate"]), b["detected"], b["missed"], b["false_bug"], b["no_verdict"]))
    L += ["", "| fault | buggy | " + " | ".join(names.get(c, c) for c in cols) + " |", "| --- | ---: | " + " | ".join("---:" for _ in cols) + " |"]
    for f in FAULTS:
        d = res[w.name]["per_fault_detected"][f]
        L.append("| %s | %d | " % (f, d["n_buggy"]) + " | ".join(str(d[c]) for c in cols) + " |")
    L += ["", "Anomaly types on Elle's reports: " + json.dumps(anom_count), ""]
(root / "elle_summary.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
(root / "elle_summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print("\n".join(L))
