"""Can Jev predict which rewarded markets are TOXIC to quote (adverse selection) from text alone?
1) For each market: realized per-market-day PnL of naive 2-sided quoting (d=2c, 20 sh) in the 12-72h-before-end window.
2) Jev scores (no prices, no outcomes): info-event likelihood, information intensity.
3) AUC / rank correlation of Jev scores vs realized toxicity; compare with simple category baseline.
"""
import os, sys, json
import numpy as np, pandas as pd
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../live"))
from common.jev import decide, cost
import hist_quote_as2 as H
ROOT = os.path.join(os.path.dirname(__file__), "../..")
OUT = f"{ROOT}/data/jev_toxicity.jsonl"
data = H.load(sys.argv[1])
rows = []
for m in data:
    r = H.run_one(m, d=0.02, hmin=12, hmax=72)
    if r and r["mins"] >= 600:
        r["per_day"] = r["pnl"] / (r["mins"] / 1440); r["q"] = m["q"]; r["ev"] = m["ev"]; r["desc"] = m["desc"]; rows.append(r)
df = pd.DataFrame(rows); print("markets with >=10h quoting", len(df))
Q = {
 "info_event": {"type": "noul", "instructions": "About 48 hours before this prediction market's end date: is it likely that a scheduled or otherwise foreseeable real-world event (announcement, data release, game, speech, vote, filing, launch, live broadcast, measurement) will occur BEFORE the end date and sharply move the probability of this market?",
                "criteria": {"true": "Yes, decisive information is likely to arrive during the market's remaining life.", "false": "No, the probability should drift slowly; no decisive information is expected before the end."}},
 "intensity": {"type": "score", "instructions": "How intense is the news/information flow that moves this market's probability, in its final 2-3 days?",
               "criteria": ["Quiet: little new information arrives", "Moderate: occasional updates", "Hot: frequent or live information (live events, counters, observations, breaking news)"]},
}
done = {}
if os.path.exists(OUT):
    for l in open(OUT):
        x = json.loads(l); done[x["cid"]] = x
def score(r):
    if r["cid"] in done: return done[r["cid"]]
    st = {"event": r["ev"], "market": r["q"], "rules": r["desc"], "hours_until_end": 48}
    try:
        a = decide(st, Q)
        return {"cid": r["cid"], "info_event": a["info_event"]["noul"], "intensity": a["intensity"]["score"]}
    except Exception as e:
        return {"cid": r["cid"], "err": str(e)[:100]}
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(score, [r for _, r in df.iterrows()]))
with open(OUT, "w") as f:
    for x in res: f.write(json.dumps(x) + "\n")
J = pd.DataFrame([x for x in res if "err" not in x])
df = df.merge(J, on="cid")
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
df["toxic"] = (df.per_day < -2).astype(int)
print("n", len(df), "toxic share", df.toxic.mean().round(3), "cost", cost())
for c in ["info_event", "intensity"]:
    print(c, "AUC(toxic)", round(roc_auc_score(df.toxic, df[c]), 3), "spearman(per_day)", round(spearmanr(df[c], df.per_day).correlation, 3))
df["jq"] = pd.qcut(df.info_event.rank(method="first"), 4, labels=False)
print(df.groupby("jq").agg(n=("cid", "size"), per_day=("per_day", "mean"), med=("per_day", "median"), toxic=("toxic", "mean"), fills=("fills", "mean")).round(3))
print(df.groupby("ft").agg(n=("cid", "size"), per_day=("per_day", "mean"), toxic=("toxic", "mean")).round(3))
df.to_csv(f"{ROOT}/data/jev_toxicity_eval.csv", index=False)
