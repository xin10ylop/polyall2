"""Estimate Jev's knowledge cutoff / outcome leakage: ask Jev whether resolved markets resolved YES,
given only question + rules. High discrimination on old markets but chance-level on recent ones => leakage.
Usage: python leakage_test.py <glob_of_day_files> <n> <out.jsonl>
"""
import sys, json, glob, random, os
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jev import decide, cost

files = sorted(glob.glob(sys.argv[1])); n = int(sys.argv[2]); out = sys.argv[3]
rows = []
for fn in files:
    for l in open(fn):
        m = json.loads(l)
        if (m.get("volumeNum") or 0) < 20000: continue
        if m.get("feeType") in ("crypto_fees_v2", "crypto_fees"): continue
        if "sports" in (m.get("feeType") or ""): continue
        try:
            op = [float(x) for x in json.loads(m["outcomePrices"])]
            oc = json.loads(m["outcomes"])
        except Exception:
            continue
        if oc[:2] != ["Yes", "No"] or max(op) < 0.99: continue
        rows.append((m, int(op[0] > 0.5)))
random.seed(7); random.shuffle(rows); rows = rows[:n]

def run(x):
    m, y = x
    state = {"market_question": m["question"], "rules": m["description"][:500],
             "market_created": (m.get("createdAt") or "")[:10], "deadline": (m.get("endDate") or "")[:10]}
    try:
        a = decide(state, {"yes": {"type": "noul",
            "instructions": "Based on everything you know about the world, did (or will) this prediction market resolve YES?",
            "criteria": {"true": "The event described happened / the market resolved YES.",
                         "false": "The event did not happen / the market resolved NO."}}})
        return {"id": m["id"], "q": m["question"], "end": m["endDate"], "y": y, "p": a["yes"]["noul"]}
    except Exception as e:
        return {"id": m["id"], "err": str(e)}

with ThreadPoolExecutor(8) as ex, open(out, "w") as f:
    for r in ex.map(run, rows):
        f.write(json.dumps(r) + "\n")
print("cost", cost())
