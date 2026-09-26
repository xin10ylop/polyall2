"""Grid of dead-bucket strategy simulations (delay after METAR obs time, price limit, window, margin)."""
import numpy as np
import pandas as pd
from common import D
from dead_latency import simulate, summarize

O = pd.read_parquet(f"{D}/dead_opps.parquet")
P = pd.read_parquet(f"{D}/dead_prints.parquet")
days = O.date.nunique()


def station_filter(O, min_match=0.99):
    """Walk-forward station reliability: use resolution_check match rate from months strictly before."""
    X = pd.read_parquet(f"{D}/resolution_check.parquet")[["icao", "date", "match"]]
    X["date"] = pd.to_datetime(X.date); X["m"] = X.date.dt.to_period("M")
    rows = []
    for icao, g in X.groupby("icao"):
        for m in sorted(g.m.unique()):
            prev = g[g.m < m]
            rows.append((icao, m, prev.match.mean() if len(prev) >= 20 else np.nan, len(prev)))
    S = pd.DataFrame(rows, columns=["icao", "m", "prior_match", "n_prior"])
    o = O.assign(m=pd.to_datetime(O.date).dt.to_period("M")).merge(S, on=["icao", "m"], how="left")
    return o.prior_match >= min_match


if __name__ == "__main__":
    rows = []
    ok = station_filter(O)
    for filt_name, OO in [("all stations", O), ("walk-fwd reliable stations", O[ok.values])]:
        for kind, margin in [("NO_dead", 1), ("NO_dead", 2), ("YES_top", 1)]:
            for delay in [0, 30, 60, 120, 300, 600, 1800]:
                for limit in [0.99, 0.98, 0.95]:
                    t = simulate(OO, P, delay_s=delay, window_s=600, limit=limit, frac=0.5, kind=kind, margin=margin)
                    s = summarize(t, days)
                    s.update(filter=filt_name, kind=kind, margin=margin, delay=delay, limit=limit)
                    rows.append(s)
    R = pd.DataFrame(rows)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    cols = ["filter", "kind", "margin", "delay", "limit", "n_trades", "staked", "pnl", "roi", "losers", "worst", "usd_per_day", "pnl_per_day", "pct_days_pos"]
    print(R[cols].round(4).to_string())
    R.to_csv(f"{D}/dead_sim_grid.csv", index=False)
