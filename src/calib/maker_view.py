"""Maker-side view: for every taker trade, the resting maker BOUGHT the opposite token at price m = 1 - q.
Maker pays no fee (and earns a rebate we ignore). Maker ROI = (maker_win - m)/m.
Market-clustered: per (market, bucket) size-weighted average first."""
import sys, os
import pandas as pd, numpy as np
ROOT = os.path.join(os.path.dirname(__file__), "../..")
df = pd.read_parquet(f"{ROOT}/data/calib_trades.parquet")
df["m"] = 1 - df.q; df["mwin"] = 1 - df.win
df["month"] = pd.to_datetime(df.closed_ts, unit="s").dt.strftime("%m")
MB = [0, .5, .65, .8, .9, .95, .98, 1]
HB = [-1e9, 0, 1, 6, 24, 72, 24*7, 24*30, 1e9]
df["mb"] = pd.cut(df.m, MB); df["hb"] = pd.cut(df.h_to_close, HB)
df["cat"] = df.feeType.str.replace("_fees.*", "", regex=True)
def agg(g):
    mk = g.groupby("cid").agg(m=("m", lambda x: np.average(x, weights=g.loc[x.index, "size"])), w=("mwin", "mean"),
                             usd=("usd", "sum"), hold=("h_to_close", "median"))
    roi = (mk.w - mk.m) / mk.m
    se = roi.std(ddof=1) / np.sqrt(len(mk)) if len(mk) > 1 else np.nan
    return pd.Series({"mkts": len(mk), "maker_usd": (g["size"] * g.m).sum(), "m": mk.m.mean(), "win": mk.w.mean(),
                      "roi": roi.mean(), "se": se, "t": roi.mean() / se if se else np.nan, "hold_h_med": mk.hold.median()})
if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 1000)
    by = sys.argv[1].split(",")
    flt = sys.argv[2] if len(sys.argv) > 2 else None
    d = df.query(flt) if flt else df
    print(d.groupby(by, observed=True).apply(agg, include_groups=False).round(4).to_string())
