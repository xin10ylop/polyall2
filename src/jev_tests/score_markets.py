"""Score resolved markets with Jev (no market price given) and cache results.
Usage: python score_markets.py <feeType> <out.jsonl> [limit]"""
import sys, os, json, glob
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jev import decide, cost
ROOT = os.path.join(os.path.dirname(__file__), "../..")
ft, out = sys.argv[1], sys.argv[2]; lim = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9
done = set()
if os.path.exists(out):
    for l in open(out):
        try: done.add(json.loads(l)["cid"])
        except Exception: pass
ms = []
for fn in sorted(glob.glob(f"{ROOT}/data/raw/markets/*.jsonl")):
    for l in open(fn):
        m = json.loads(l)
        if m.get("feeType") == ft and m["conditionId"] not in done: ms.append(m)
seen = set(); ms = [m for m in ms if not (m["conditionId"] in seen or seen.add(m["conditionId"]))][:lim]
Q = {"yes": {"type": "noul",
             "instructions": "Estimate the probability that this prediction market resolves YES, i.e. that the listed word/phrase will be said (or the listed thing will happen) under the stated rules. Use base rates for this speaker and this type of event.",
             "criteria": {"true": "The term is said / the market resolves YES.", "false": "The term is not said / the market resolves NO."}}}
def run(m):
    st = {"event": m.get("eventTitle"), "market": m["question"], "rules": (m.get("description") or "")[:600],
          "event_date": (m.get("endDate") or "")[:10]}
    try:
        a = decide(st, Q)
        return {"cid": m["conditionId"], "jev": a["yes"]["noul"]}
    except Exception as e:
        return {"cid": m["conditionId"], "err": str(e)[:200]}
with ThreadPoolExecutor(8) as ex, open(out, "a") as f:
    for r in ex.map(run, ms):
        f.write(json.dumps(r) + "\n")
print("cost", cost())
