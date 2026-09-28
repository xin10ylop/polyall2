"""Forward test scoring: Jev judges each LLM-gathered evidence bundle; after resolution, compare
Brier / log-loss of market mid vs LLM prob vs Jev prob, and simulated taker PnL at snapshot prices.
Usage: python fwd_score.py jev      -> adds Jev probabilities (no outcomes needed)
       python fwd_score.py resolve  -> fetch outcomes and score"""
import os, sys, json, math
import requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jev import decide, cost
ROOT = os.path.join(os.path.dirname(__file__), "../..")
D = f"{ROOT}/data/fwd_llm"
snap = {x["cid"]: x for x in json.load(open(f"{D}/markets_snapshot.json"))}
llm = []
for f in ("llm_a.json", "llm_b.json"):
    if os.path.exists(f"{D}/{f}"): llm += json.load(open(f"{D}/{f}"))
mode = sys.argv[1]
if mode == "jev":
    out = {}
    for r in llm:
        s = snap[r["cid"]]
        st = {"market_question": s["q"], "resolution_rules": s["desc"], "evidence_gathered": r["evidence"], "as_of": r.get("researched_at_utc")}
        a = decide(st, {"yes": {"type": "noul", "instructions": "Given the resolution rules and the evidence gathered so far, what is the probability this market resolves YES?",
                                "criteria": {"true": "The market resolves YES under its rules.", "false": "The market resolves NO under its rules."}}})
        out[r["cid"]] = a["yes"]["noul"]
    json.dump(out, open(f"{D}/jev_probs.json", "w"), indent=1)
    print("jev scored", len(out), cost())
else:
    jev = json.load(open(f"{D}/jev_probs.json")) if os.path.exists(f"{D}/jev_probs.json") else {}
    rows = []
    for r in llm:
        s = snap[r["cid"]]
        # gamma hides closed markets unless closed=true is passed
        m = requests.get("https://gamma-api.polymarket.com/markets", params={"condition_ids": r["cid"], "closed": "true"}, timeout=20).json()
        if not m: continue
        m = m[0]
        try: op = [float(x) for x in json.loads(m["outcomePrices"])]
        except Exception: continue
        if not m.get("closed") or max(op) < 0.99: continue
        y = int(op[0] > 0.5)
        pj = jev.get(r["cid"])
        pc = None if pj is None else 0.5 * r["p_yes"] + 0.5 * pj  # the pipeline's decision rule (research.py)
        rows.append((s["q"][:60], y, s["mid"], s["bid"], s["ask"], r["p_yes"], pj, pc))
    def brier(p, y): return (p - y) ** 2
    n = len(rows); print("resolved", n, "of", len(llm))
    if n:
        for name, idx in (("market", 2), ("llm", 5), ("jev", 6), ("llm+jev", 7)):
            v = [brier(x[idx], x[1]) for x in rows if x[idx] is not None]
            print(name, "Brier", round(sum(v) / len(v), 4), "n", len(v))
        for name, idx in (("llm", 5), ("jev", 6), ("llm+jev", 7)):
            pnl = 0; k = 0
            for x in rows:
                y, bid, ask, p = x[1], x[3], x[4], x[idx]
                if p is None: continue
                if p - ask > 0.05: pnl += (y - ask - 0.05 * ask * (1 - ask)) / ask; k += 1
                elif (1 - p) - (1 - bid) > 0.05: pnl += ((1 - y) - (1 - bid) - 0.05 * bid * (1 - bid)) / (1 - bid); k += 1
            print(name, "trades", k, "sum ROI", round(pnl, 3))
        for x in rows: print(x)
