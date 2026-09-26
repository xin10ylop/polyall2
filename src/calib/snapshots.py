"""Snapshot (non-endogenous) calibration: price of token0 at fixed horizons before endDate/closedTime.
Uses clob prices-history (hourly), which is ~midpoint. Outputs data/calib_snap.parquet"""
import json, glob, os
import numpy as np, pandas as pd
import datetime as dt
ROOT = os.path.join(os.path.dirname(__file__), "../..")
def ts(s):
    if not s: return np.nan
    s = s.replace(" ", "T")
    if s.endswith("+00"): s += ":00"
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return np.nan
meta = {}
for fn in glob.glob(f"{ROOT}/data/raw/markets/*.jsonl"):
    for l in open(fn):
        m = json.loads(l); meta[m["conditionId"]] = m
H = [1, 3, 6, 12, 24, 48, 72, 168, 336]
rows = []
for fn in glob.glob(f"{ROOT}/data/raw/ph/*.json"):
    cid = os.path.basename(fn)[:-5]; m = meta.get(cid)
    if not m: continue
    d = json.load(open(fn))
    if len(d["t"]) < 3: continue
    t = np.array(d["t"]); p = np.array(d["p"])
    o = np.argsort(t); t = t[o]; p = p[o]
    op = [float(x) for x in json.loads(m["outcomePrices"])]
    y = int(op[0] > 0.5)
    end = ts(m.get("endDate")); cl = ts(m.get("closedTime")); cr = ts(m.get("createdAt"))
    fs = m.get("feeSchedule") or {}
    rate = fs.get("rate", 0.0) if m.get("feesEnabled") else 0.0
    for ref_name, ref in (("close", cl), ("end", end)):
        if not np.isfinite(ref): continue
        for h in H:
            x = ref - h * 3600
            if x < t[0] or x < cr: continue
            i = np.searchsorted(t, x, side="right") - 1
            if i < 0 or x - t[i] > 3 * 3600: continue   # stale
            rows.append((cid, m.get("feeType") or "none", ref_name, h, p[i], y, rate, bool(m.get("negRisk")), m.get("volumeNum"), (m.get("closedTime") or "")[:10], cl - end if np.isfinite(end) else np.nan))
df = pd.DataFrame(rows, columns=["cid", "feeType", "ref", "h", "p", "y", "rate", "negRisk", "vol", "closeday", "close_minus_end"])
df.to_parquet(f"{ROOT}/data/calib_snap.parquet"); print(len(df), df.cid.nunique())
