"""Compare METAR-derived daily max (IEM) with the winning bucket of each resolved event."""
import os, sys
import numpy as np
import pandas as pd
from common import D
from obs import load_obs, daily_max


def in_bucket(v, lo, hi):
    ok = np.ones(len(v), bool)
    ok &= np.where(pd.isna(lo), True, v >= lo)
    ok &= np.where(pd.isna(hi), True, v <= hi)
    return ok


def main():
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[R.clean & (R.kind == "highest")]
    out = []
    for (icao, unit), g in R.groupby(["icao", "unit"]):
        if unit not in ("C", "F"):
            continue
        o = load_obs(icao, unit)
        if o is None:
            continue
        dm = daily_max(o)
        gg = g.copy()
        gg["obs_max"] = gg.date.map(dm.tmax)
        gg["nobs"] = gg.date.map(dm.nobs)
        out.append(gg)
    X = pd.concat(out)
    X = X[X.obs_max.notna()]
    X["match"] = in_bucket(X.obs_max.values, X.win_lo.values, X.win_hi.values)
    # signed distance from bucket
    X["dist"] = np.where(X.match, 0, np.where(~pd.isna(X.win_lo) & (X.obs_max < X.win_lo), X.obs_max - X.win_lo,
                                             np.where(~pd.isna(X.win_hi) & (X.obs_max > X.win_hi), X.obs_max - X.win_hi, 0)))
    X.to_parquet(f"{D}/resolution_check.parquet")
    s = X.groupby(["icao", "source"]).agg(n=("match", "size"), match=("match", "mean"), mean_dist=("dist", "mean"),
                                           below=("dist", lambda d: (d < 0).mean()), above=("dist", lambda d: (d > 0).mean()))
    print(s.round(3).to_string())
    print(X.groupby("source").match.mean())
    return X


if __name__ == "__main__":
    main()
