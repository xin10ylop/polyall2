"""Maker variant on small-account buckets, trade-through fills only.
At each decision step t (every `life` hours on the hourly grid) post:
  YES bid at b = floor_tick(q - m)       (only if b >= 0.01 and b <= mid - 0.005, i.e. a genuine resting bid)
  NO bid  at 1 - a, a = ceil_tick(q + m) (YES-equivalent ask; only if a <= 0.99 and a >= mid + 0.005)
Order lives (t, t+life]; replaced at the next step. Filled ONLY if a later taker print trades STRICTLY through
our price in that interval (YES bid: YES-equivalent taker-sell prints at py < b; NO bid: taker-buy prints at
py > a). Filled shares = min(order shares, through-print shares). Price = our limit. No fee. Hold to resolution.
Output per (config): fills table data/tweets/maker_fills.parquet"""
import os, sys, glob, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from common import D, events
from bt_build import yes_equiv

SMALL = ["WhiteHouse", "tedcruz", "ZelenskyyUa", "NYCMayor", "cz_binance", "khamenei_ir"]
MARGINS = [0.03, 0.05, 0.08, 0.12]
LIVES = [1, 6]
ORDER_USD = 200.0

def run():
    df = pd.read_parquet("/tmp/claude-0/bt_all.parquet",
                         columns=["event_id", "t", "k", "q", "mid", "won", "H", "acct", "gap", "stall", "oos", "end"])
    df = df[df.acct.isin(SMALL) & ~df.gap & (df.stall <= 120) & (df.t % 3600 == 0)]
    E, B = events(); tick = B.set_index(["event_id", "k"]).tick.fillna(0.01).to_dict()
    out = []
    for eid, g in df.groupby("event_id"):
        TR = pd.read_parquet(f"{D}/trades/{eid}.parquet").sort_values("ts")
        py, lift = yes_equiv(TR)
        TR = TR.assign(py=py, lift=lift)
        for k, gk in g.groupby("k"):
            tr = TR[TR.k == k]
            tl, pl, sl = tr.ts.values[tr.lift.values], tr.py.values[tr.lift.values], tr["size"].values[tr.lift.values]
            th, ph, sh = tr.ts.values[~tr.lift.values], tr.py.values[~tr.lift.values], tr["size"].values[~tr.lift.values]
            tk = tick.get((eid, k), 0.01) or 0.01
            for life in LIVES:
                gg = gk[gk.t % (life * 3600) == 0]
                for r in gg.itertuples():
                    t0, t1 = r.t, r.t + life * 3600
                    i0, i1 = np.searchsorted(th, [t0, t1], side="right")
                    j0, j1 = np.searchsorted(tl, [t0, t1], side="right")
                    for m in MARGINS:
                        b = np.floor((r.q - m) / tk + 1e-9) * tk
                        if b >= 0.01 and b <= r.mid - 0.005:
                            thru = sh[i0:i1][ph[i0:i1] < b - 1e-9].sum()
                            if thru > 0:
                                sz = min(ORDER_USD / b, thru)
                                out.append((eid, k, r.t, life, m, "y", b, sz, thru * b, float(r.won), r.acct, r.oos, r.end, r.H, r.q, r.mid))
                        a = np.ceil((r.q + m) / tk - 1e-9) * tk
                        if a <= 0.99 and a >= r.mid + 0.005:
                            thru = sl[j0:j1][pl[j0:j1] > a + 1e-9].sum()
                            if thru > 0:
                                c = 1 - a
                                sz = min(ORDER_USD / c, thru)
                                out.append((eid, k, r.t, life, m, "n", c, sz, thru * c, 1 - float(r.won), r.acct, r.oos, r.end, r.H, r.q, r.mid))
    F = pd.DataFrame(out, columns=["event_id", "k", "t", "life", "m", "side", "px", "shares", "thru_usd", "pay", "acct", "oos", "end", "H", "q", "mid"])
    F.to_parquet(f"{D}/maker_fills.parquet", index=False)
    # posting counts (for fill-rate) per config
    return F, df

def wk_t(v, end):
    w = v.groupby(end.dt.tz_convert(None).dt.to_period("W")).sum()
    return w.mean() / (w.std(ddof=1) / np.sqrt(len(w))) if len(w) > 2 and w.std() > 0 else np.nan

def summarize(F, days):
    F = F.assign(usd=F.shares * F.px, pnl=F.shares * (F.pay - F.px))
    r = dict(fills=len(F), events=F.event_id.nunique(), hit=(F.pay).mean(), avg_px=F.px.mean(),
             usd=F.usd.sum(), pnl=F.pnl.sum(), roi=F.pnl.sum() / F.usd.sum() if len(F) else np.nan,
             t_wk=wk_t(F.pnl, F.end) if len(F) else np.nan, fills_day=len(F) / days, usd_day=F.usd.sum() / days,
             thru_usd_day=F.thru_usd.sum() / days, pnl_day=F.pnl.sum() / days)
    eq = F.groupby("end").pnl.sum().sort_index().cumsum().values
    r["mdd"] = float((np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]).max()) if len(eq) else 0
    return r

if __name__ == "__main__":
    F, df = run()
    is_days = (df[~df.oos].t.max() - df[~df.oos].t.min()) / 86400
    oos_days = (df[df.oos].t.max() - df[df.oos].t.min()) / 86400
    rows = []
    for life in LIVES:
        for m in MARGINS:
            for side in ["y", "n", "both"]:
                for oos in [False, True]:
                    f = F[(F.life == life) & (F.m == m) & (F.oos == oos) & ((F.side == side) if side != "both" else True)]
                    r = summarize(f, oos_days if oos else is_days); r.update(life=life, m=m, side=side, oos=oos); rows.append(r)
    R = pd.DataFrame(rows)
    R.to_csv(f"{D}/maker_grid.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["life", "m", "side", "oos", "fills", "events", "hit", "avg_px", "usd", "pnl", "roi", "t_wk", "mdd", "fills_day", "usd_day", "pnl_day", "thru_usd_day"]
    print("IS days %.0f  OOS days %.0f" % (is_days, oos_days))
    print(R[cols].round(3).to_string(index=False))
