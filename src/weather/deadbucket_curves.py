"""Price/volume path of the executable side around the death time of each dead bucket (exact prints)."""
import glob, os, sys
import numpy as np
import pandas as pd
from common import D

BINS = [-3600, -1800, -600, -300, -60, 0, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200, 10800, 21600]


def curves(O, T, contested_min_yes=0.03):
    T = T.copy()
    isno = T.oi == 1
    T["py"] = np.where(isno, 1 - T.price, T.price)
    T["sy"] = np.where(isno, -T.side, T.side)
    groups = {k: g for k, g in T.groupby(["event_id", "mi"])}
    recs = []
    for r in O.itertuples():
        g = groups.get((r.event_id, r.mi))
        if g is None:
            continue
        dt_all = g.ts.values.astype(np.int64) - r.t_death
        # contested: last YES-eq trade (any side) in the 2h before death had YES price >= threshold
        pre = g[(dt_all < 0) & (dt_all >= -7200)]
        yes_pre = pre.py.values[-1] if len(pre) else np.nan
        if r.kind == "NO_dead":
            s = g[g.sy == -1]; px = 1 - s.py.values
        else:
            s = g[g.sy == 1]; px = s.py.values
        dt = s.ts.values.astype(np.int64) - r.t_death
        for d, p, z in zip(dt, px, s["size"].values):
            if BINS[0] <= d < BINS[-1]:
                recs.append((r.Index, r.kind, yes_pre, d, p, z))
    C = pd.DataFrame(recs, columns=["opp", "kind", "yes_pre", "dt", "px", "sh"])
    C["bin"] = pd.cut(C.dt, BINS, right=False)
    return C


if __name__ == "__main__":
    lag = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    O = pd.read_parquet(f"{D}/deadbucket_lag{lag}.parquet")
    files = sorted(glob.glob(f"{D}/raw_d0/*_highest.parquet"))
    T = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    T = T[T.event_id.isin(O.event_id.unique())]
    C = curves(O, T)
    C.drop(columns="bin").to_parquet(f"{D}/deadbucket_curves_lag{lag}.parquet")
    pd.set_option("display.width", 220)
    for kind in ["NO_dead", "YES_top"]:
        for lab, cond in [("all", C.yes_pre.notna() | C.yes_pre.isna()), ("contested(yes_pre>=0.03)", C.yes_pre >= 0.03 if kind == "NO_dead" else C.yes_pre <= 0.97)]:
            x = C[(C.kind == kind) & cond]
            g = x.groupby("bin", observed=True).agg(opps=("opp", "nunique"), prints=("px", "size"), shares=("sh", "sum"),
                                                     med_px=("px", "median"), vwap=("px", lambda p: np.average(p, weights=x.loc[p.index, "sh"])),
                                                     sh_le99=("sh", lambda s: s[x.loc[s.index, "px"] <= 0.99].sum()),
                                                     sh_le97=("sh", lambda s: s[x.loc[s.index, "px"] <= 0.97].sum()))
            print("==", kind, lab, "opps", x.opp.nunique())
            print(g.round(4).to_string())
