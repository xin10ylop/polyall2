"""Latency/edge analysis of deterministic dead buckets and executable NO prices around the killing METAR.

Inputs: dead_opps.parquet (one row per bucket death, margin m), dead_prints.parquet (prints relative to the
killing METAR observation time `valid`, dtv seconds; exe = print on the side we would take).
"""
import sys
import numpy as np
import pandas as pd
from common import D

FINE = [-1800, -600, -300, -120, -60, 0, 15, 30, 45, 60, 90, 120, 180, 240, 300, 450, 600, 900, 1200, 1800, 3600, 7200, 14400, 28800]


def latency_table(O, P, kind="NO_dead", margin=1):
    o = O[(O.kind == kind) & (O.margin == margin)]
    p = P[P.opp.isin(o.opp) & P.exe].copy()
    p["bin"] = pd.cut(p.dtv, FINE, right=False)
    n_opp = len(o)
    g = p.groupby("bin", observed=False)
    t = pd.DataFrame({
        "opps_with_print": g.opp.nunique() / n_opp,
        "prints": g.px.size(),
        "shares": g.sh.sum(),
        "vwap": g.apply(lambda x: np.average(x.px, weights=x.sh) if len(x) else np.nan),
        "med_px": g.px.median(),
        "opps_px<=0.99": g.apply(lambda x: x[x.px <= 0.99].opp.nunique()) / n_opp,
        "sh_px<=0.99": g.apply(lambda x: x[x.px <= 0.99].sh.sum()),
        "usd_edge<=0.99": g.apply(lambda x: ((1 - x.px) * x.sh)[x.px <= 0.99].sum()),
        "opps_px<=0.97": g.apply(lambda x: x[x.px <= 0.97].opp.nunique()) / n_opp,
        "sh_px<=0.97": g.apply(lambda x: x[x.px <= 0.97].sh.sum()),
    })
    return t, n_opp


def simulate(O, P, delay_s, window_s=600, limit=0.99, frac=0.5, fee_rate=0.05, kind="NO_dead", margin=1, max_usd=None):
    """Enter at valid + delay_s (delay = METAR publication + our reaction). Take executable prints with price
    <= limit in [delay, delay+window) at their printed prices, capped at frac of printed shares (and max_usd)."""
    o = O[(O.kind == kind) & (O.margin == margin)][["opp", "win", "fees", "city", "date", "icao", "event_id", "valid", "day0"]]
    p = P[P.exe & (P.dtv >= delay_s) & (P.dtv < delay_s + window_s) & (P.px <= limit)]
    p = p.merge(o, on="opp")
    p["sh_take"] = p.sh * frac
    if max_usd is not None:
        p = p.sort_values(["opp", "dtv"])
        p["cum_usd"] = (p.sh_take * p.px).groupby(p.opp).cumsum()
        p = p[p.cum_usd - p.sh_take * p.px < max_usd]
    fr = np.where(p.fees, fee_rate, 0.0)
    p["fee"] = p.sh_take * fr * p.px * (1 - p.px)
    payoff = 1 - p.win if kind == "NO_dead" else p.win
    p["cost"] = p.sh_take * p.px + p.fee
    p["pnl"] = p.sh_take * payoff - p.cost
    t = p.groupby("opp").agg(cost=("cost", "sum"), pnl=("pnl", "sum"), sh=("sh_take", "sum"), win=("win", "first"),
                             date=("date", "first"), city=("city", "first"), icao=("icao", "first"))
    return t


def summarize(t, days):
    if len(t) == 0:
        return {}
    daily = t.groupby("date").pnl.sum()
    return dict(n_trades=len(t), staked=t.cost.sum(), pnl=t.pnl.sum(), roi=t.pnl.sum() / t.cost.sum(),
                losers=(t.pnl < 0).sum(), worst=t.pnl.min(), usd_per_day=t.cost.sum() / days, pnl_per_day=t.pnl.sum() / days,
                pct_days_pos=(daily > 0).mean())


if __name__ == "__main__":
    O = pd.read_parquet(f"{D}/dead_opps.parquet")
    P = pd.read_parquet(f"{D}/dead_prints.parquet")
    days = O.date.nunique()
    pd.set_option("display.width", 250)
    for kind, m in [("NO_dead", 1), ("NO_dead", 2), ("YES_top", 1)]:
        t, n = latency_table(O, P, kind, m)
        print(f"===== {kind} margin={m}: opportunities {n}, P(bucket actually won) = {O[(O.kind==kind)&(O.margin==m)].win.mean():.4f}")
        print(t.round(4).to_string())
