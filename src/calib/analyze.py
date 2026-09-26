"""Market-clustered calibration analysis of taker buys.
For each (market, bucket) we take the size-weighted avg taker price and outcome, so each market counts once per bucket.
Edge per $1 staked (ROI) = (win - q - fee)/q, fee per share = rate*q*(1-q) (assumed; exponent 1).
"""
import sys, os
import pandas as pd, numpy as np
ROOT = os.path.join(os.path.dirname(__file__), "../..")
df = pd.read_parquet(f"{ROOT}/data/calib_trades.parquet")
df["fee"] = df.rate * df.q * (1 - df.q)
PB = [0, .02, .05, .1, .2, .35, .5, .65, .8, .9, .95, .98, .995, 1]
HB = [-1e9, 0, 1, 6, 24, 72, 24*7, 24*30, 1e9]
df["pb"] = pd.cut(df.q, PB); df["hb"] = pd.cut(df.h_to_close, HB)

def agg(g):
    # per-market aggregation first
    mk = g.groupby("cid").apply(lambda x: pd.Series({"q": np.average(x.q, weights=x["size"]), "win": x.win.iloc[0] if x.win.nunique()==1 else np.average(x.win, weights=x["size"]),
                                                      "fee": np.average(x.fee, weights=x["size"]), "usd": x.usd.sum()}), include_groups=False)
    if len(mk) == 0: return pd.Series(dtype=float)
    pnl = mk.win - mk.q - mk.fee          # per share
    roi = pnl / mk.q
    se = roi.std(ddof=1) / np.sqrt(len(mk)) if len(mk) > 1 else np.nan
    return pd.Series({"mkts": len(mk), "usd": mk.usd.sum(), "avg_q": mk.q.mean(), "winrate": mk.win.mean(),
                      "roi": roi.mean(), "roi_se": se, "t": roi.mean() / se if se and se > 0 else np.nan})

def table(by):
    out = df.groupby(by, observed=True).apply(agg, include_groups=False)
    return out

if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    what = sys.argv[1] if len(sys.argv) > 1 else "pb"
    by = what.split(",")
    print(table(by).round(4).to_string())
