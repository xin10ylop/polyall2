"""Conservative maker backtest: one-sided bids on the FAVORITE token, filled only on TRADE-THROUGH.

At each decision time t (every `step` hours through the market's life, until `stop_h` hours before close):
  - reference price r = last taker trade price of the favorite token before t (normalized), fallback prices-history
  - favorite = token with r >= 0.5; skip if r outside [lo, hi]
  - place bid at b = floor_to_tick(r - delta); live until t + step
  - FILL only if some later taker trade in (t, t+step] prints the favorite at price <= b - tick
    (i.e. the market traded THROUGH our level, so price priority guarantees our fill). Fill qty = min(remaining, trade size)
  - per-market cap `cap_usd`; hold to resolution; maker pays no fee (rebates ignored)
Outputs per-fill ledger.
"""
import os, sys, json, glob, math
import numpy as np, pandas as pd
ROOT = os.path.join(os.path.dirname(__file__), "../..")

def run(trades, lo=0.5, hi=0.9, delta=0.01, step=1.0, stop_h=0.0, cap_usd=50.0, tick=0.01, cats=None, min_h=0.0):
    out = []
    for cid, g in trades.groupby("cid", sort=False):
        cat = g.cat.iloc[0]
        if cats and cat not in cats: continue
        g = g.sort_values("ts")
        cl = g.closed_ts.iloc[0]
        if not np.isfinite(cl): continue
        ts = g.ts.values; tok = g.tok.values; q = g.q.values; sz = g["size"].values; win_tok = None
        # winner token
        w0 = g.loc[g.tok == 0, "win"]; w1 = g.loc[g.tok == 1, "win"]
        if len(w0): winner = 0 if w0.iloc[0] == 1 else 1
        elif len(w1): winner = 1 if w1.iloc[0] == 1 else 0
        else: continue
        # price of token0 implied by each trade
        p0 = np.where(tok == 0, q, 1 - q)
        spent = 0.0
        t = ts[0] + 3600  # need some history
        end_t = cl - stop_h * 3600
        while t < end_t and spent < cap_usd:
            i = np.searchsorted(ts, t, side="right") - 1
            if i < 0: t += step * 3600; continue
            r0 = p0[i]
            fav = 0 if r0 >= 0.5 else 1
            r = r0 if fav == 0 else 1 - r0
            h_left = (cl - t) / 3600
            if lo <= r <= hi and h_left >= min_h:
                b = math.floor((r - delta) / tick + 1e-9) * tick
                j0 = i + 1; j1 = np.searchsorted(ts, t + step * 3600, side="right")
                for j in range(j0, j1):
                    # favorite price at trade j
                    pf = p0[j] if fav == 0 else 1 - p0[j]
                    if pf <= b - tick + 1e-9:
                        qty = min(sz[j], (cap_usd - spent) / b)
                        if qty <= 0: break
                        spent += qty * b
                        out.append((cid, cat, t, ts[j], h_left, r, b, qty, int(winner == fav)))
                        if spent >= cap_usd - 1e-6: break
            t += step * 3600
    return pd.DataFrame(out, columns=["cid", "cat", "t_order", "t_fill", "h_left", "ref", "bid", "qty", "win"])

def summarize(L, by=None):
    if L.empty: return "no fills"
    L = L.assign(cost=L.qty * L.bid, pnl=L.qty * (L.win - L.bid))
    def s(x):
        mk = x.groupby("cid").agg(cost=("cost", "sum"), pnl=("pnl", "sum"))
        r = mk.pnl / mk.cost
        return pd.Series({"mkts": len(mk), "fills": len(x), "cost": mk.cost.sum(), "pnl": mk.pnl.sum(),
                          "roi_$w": mk.pnl.sum() / mk.cost.sum(), "roi_mkt": r.mean(), "se": r.std() / np.sqrt(len(r)) if len(r) > 1 else np.nan,
                          "hit": (mk.pnl > 0).mean(), "hold_h": ((x.h_left)).median()})
    return L.groupby(by).apply(s, include_groups=False) if by else s(L)

if __name__ == "__main__":
    df = pd.read_parquet(f"{ROOT}/data/calib_trades.parquet")
    df["cat"] = df.feeType.str.replace("_fees.*", "", regex=True)
    import itertools
    pd.set_option("display.width", 250)
    for lo, hi, delta in [(0.5, 0.65, 0.01), (0.5, 0.8, 0.01), (0.65, 0.8, 0.01), (0.8, 0.9, 0.01), (0.5, 0.8, 0.03)]:
        L = run(df, lo=lo, hi=hi, delta=delta, step=1.0, cap_usd=50)
        print(f"== lo={lo} hi={hi} delta={delta}")
        print(summarize(L, "cat").round(4).to_string())
