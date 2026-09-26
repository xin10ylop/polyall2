"""Realised resolution PnL of ALL actual maker fills in the historical weather sample (maker = counterparty of each
taker print), by window relative to the LOCAL observation day and by price bucket. Complements hist_as_audit.py:
this is what the makers who actually provided liquidity earned per share before rewards.
Usage: python src/audit/maker_fill_pnl.py [sample.jsonl]"""
import os, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from hist_as_audit import load, ROOT
data = load(sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/sample_weather_recent.jsonl")
rows = []
for m in data:
    if not np.isfinite(m["obs"]): continue
    h = (m["obs"] - m["TT"]) / 3600
    # maker sells YES when taker buys YES (HA) at yes-price TP; maker PnL/share = TP - y ; else maker buys YES: y - TP
    pnl_sh = np.where(m["HA"], m["TP"] - m["y"], m["y"] - m["TP"])
    # mid at trade time (last 1-min mid) -> taker's price improvement vs mid ~ half-spread paid
    i = np.clip(np.searchsorted(m["T"], m["TT"], side="right") - 1, 0, len(m["T"]) - 1)
    mid = m["P"][i]
    half = np.where(m["HA"], m["TP"] - mid, mid - m["TP"])
    rows.append(pd.DataFrame(dict(cid=m["cid"], h=h, p=m["TP"], sz=m["TS"], pnl=pnl_sh * m["TS"], half=half * m["TS"],
                                  notional=np.where(m["HA"], m["TP"], 1 - m["TP"]) * m["TS"], after=m["TT"] >= m["closed"])))
D = pd.concat(rows); D = D[~D.after]
D["win"] = pd.cut(D.h, [-1e9, -24, 0, 12, 24, 48, 1e9], labels=["post", "obs-day", "0-12h pre", "12-24h pre", "24-48h pre", ">48h pre"])
D["pb"] = pd.cut(D.p, [0, 0.05, 0.15, 0.35, 0.65, 0.85, 0.95, 1.0])
def agg(g):
    return pd.Series(dict(n=len(g), mkts=g.cid.nunique(), shares=g.sz.sum(), pnl=g.pnl.sum(), pnl_per_share=g.pnl.sum() / g.sz.sum(),
                          roi_on_notional=g.pnl.sum() / g.notional.sum(), halfspread_per_share=g.half.sum() / g.sz.sum()))
print("ALL actual maker fills, weather sample: resolution PnL (before rewards)")
print(D.groupby("win", observed=True).apply(agg).round(4).to_string())
print("\nby price bucket, windows >=12h before local obs day")
E = D[D.h >= 12]
print(E.groupby("pb", observed=True).apply(agg).round(4).to_string())
# market-clustered t-stat for >=12h window
g = E.groupby("cid").agg(pnl=("pnl", "sum"), sh=("sz", "sum"))
x = g.pnl / g.sh
print(f"\n>=12h pre-obs: market-clustered mean pnl/share={x.mean():+.4f} t={x.mean() / (x.std() / np.sqrt(len(x))):.2f} (n mkts={len(x)}); "
      f"volume-weighted {g.pnl.sum() / g.sh.sum():+.4f}")
