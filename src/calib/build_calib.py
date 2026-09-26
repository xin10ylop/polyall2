"""Join taker trades with market metadata & outcomes -> one normalized table.
Each taker trade is expressed as 'taker BOUGHT token k at price q' (a SELL of token j at p == BUY of other token at 1-p).
Output: data/calib_trades.parquet
"""
import json, glob, gzip, os, sys
import datetime as dt
import pandas as pd, numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "../..")

def ts(s):
    if not s: return np.nan
    s = s.replace(" ", "T")
    if s.endswith("+00"): s += ":00"
    s = s.replace("Z", "+00:00")
    try: return dt.datetime.fromisoformat(s).timestamp()
    except Exception: return np.nan

meta = {}
for fn in glob.glob(f"{ROOT}/data/raw/markets/*.jsonl"):
    for l in open(fn):
        m = json.loads(l)
        meta[m["conditionId"]] = m

frames = []
for fn in glob.glob(f"{ROOT}/data/raw/trades/*.csv.gz"):
    cid = os.path.basename(fn)[:-7]
    m = meta.get(cid)
    if m is None: continue
    try:
        t = pd.read_csv(fn)
    except Exception:
        continue
    if t.empty: continue
    op = [float(x) for x in json.loads(m["outcomePrices"])]
    w = int(np.argmax(op))
    fs = m.get("feeSchedule") or {}
    t["cid"] = cid
    t["feeType"] = m.get("feeType") or "none"
    t["rate"] = fs.get("rate", 0.0) if m.get("feesEnabled") else 0.0
    t["negRisk"] = bool(m.get("negRisk"))
    t["vol"] = m.get("volumeNum")
    t["end_ts"] = ts(m.get("endDate")); t["closed_ts"] = ts(m.get("closedTime")); t["created_ts"] = ts(m.get("createdAt"))
    t["eventId"] = m.get("eventId")
    buy = t["side"] == "B"
    t["tok"] = np.where(buy, t["oi"], 1 - t["oi"])
    t["q"] = np.where(buy, t["price"], 1 - t["price"])
    t["win"] = (t["tok"] == w).astype(int)
    t["tok_is_yes"] = (t["tok"] == 0).astype(int)
    frames.append(t)
df = pd.concat(frames, ignore_index=True)
df = df[(df.q > 0) & (df.q < 1)]
df["usd"] = df["q"] * df["size"]
df["h_to_close"] = (df.closed_ts - df.ts) / 3600
df["h_to_end"] = (df.end_ts - df.ts) / 3600
df.to_parquet(f"{ROOT}/data/calib_trades.parquet")
print(len(df), df.cid.nunique())
