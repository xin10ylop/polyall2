"""Fetch CLOB LP-reward configs (/rewards/markets/current, all pages) and join to open tweet-count buckets.
Saves data/tweets/books/rewards_<ts>.parquet"""
import json, time, os, sys, requests, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from common import D
from build_events import SERIES_ACCT, parse_bucket
S = requests.Session(); rows = []; cur = None
for i in range(2000):
    p = {"next_cursor": cur} if cur else {}
    j = S.get("https://clob.polymarket.com/rewards/markets/current", params=p, timeout=60).json()
    for m in j.get("data", []):
        rows.append(dict(conditionId=m["condition_id"], rate_per_day=sum(c.get("rate_per_day", 0) for c in m.get("rewards_config", [])),
                         max_spread=m.get("rewards_max_spread"), min_size=m.get("rewards_min_size"),
                         total_daily=m.get("total_daily_rate")))
    cur = j.get("next_cursor")
    if not cur or cur == "LTE=" or not j.get("data"): break
R = pd.DataFrame(rows).drop_duplicates("conditionId")
print("rewarded markets (all Polymarket):", len(R), "sum $/day", R.rate_per_day.sum().round(0))
evs = [json.loads(l) for l in open(f"{D}/gamma/events_open.jsonl")]
M = []
for e in evs:
    a = SERIES_ACCT.get(e.get("seriesSlug") or "")
    if not a: continue
    for m in e["markets"]:
        if parse_bucket(m.get("groupItemTitle")) is None or m.get("closed"): continue
        M.append(dict(acct=a, event=e["title"], label=m["groupItemTitle"], conditionId=m["conditionId"]))
M = pd.DataFrame(M).merge(R, on="conditionId", how="left")
M.to_parquet(f"{D}/books/rewards_{time.strftime('%Y%m%dT%H%M%S')}.parquet", index=False)
g = M.groupby("acct").agg(buckets=("label", "size"), rewarded=("rate_per_day", lambda x: (x > 0).sum()),
                          usd_per_day=("rate_per_day", "sum"), max_spread_c=("max_spread", "median"), min_size=("min_size", "median"))
print(g.to_string())
print(M[M.rate_per_day > 0].groupby(["acct", "event"]).rate_per_day.agg(["size", "sum"]).to_string())
