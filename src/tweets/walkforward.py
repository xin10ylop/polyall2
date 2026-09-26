"""Walk-forward model parameters: for each month start M, fit (hl, alpha) per (acct, horizon bin) using only
calibration points whose target window ended before M (t + H < M), excluding tracker-outage periods.
Saves data/tweets/wf_params.json : {"YYYY-MM": {acct: {hb: {hl, alpha, n}}}}"""
import json, sys, numpy as np, pandas as pd
from common import D, gaps
from calibrate import HLS, fit_alpha

MONTHS = pd.date_range("2025-12-01", "2026-10-01", freq="MS", tz="UTC")
MIN_N = 150

def load(tag=""):
    P = pd.read_parquet(f"{D}/calib_points{tag}.parquet")
    keep = np.ones(len(P), bool)
    for a in P.acct.unique():
        m = (P.acct == a).values
        s = P.t.values - 7 * 86400; e = P.t.values + P.H.values * 3600
        for g0, g1 in gaps(a):
            keep &= ~(m & ~((e <= g0) | (s >= g1)))
    return P[keep]

def fit(P):
    out = {}
    for (a, hb), g in P.groupby(["acct", "hb"]):
        if len(g) < MIN_N: continue
        best = None
        for hl in HLS:
            al, ll = fit_alpha(g.n.values, g[f"mu_{hl}"].values)
            if best is None or ll > best[2]: best = (hl, al, ll)
        out.setdefault(a, {})[str(hb)] = dict(hl=best[0], alpha=best[1], n=int(len(g)))
    return out

if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    P = load(tag)
    W = {}
    for M in MONTHS:
        m = M.value // 10**9
        tr = P[(P.t + P.H * 3600) < m]
        W[M.strftime("%Y-%m")] = fit(tr)
        print(M.strftime("%Y-%m"), {a: len(v) for a, v in W[M.strftime("%Y-%m")].items()}, flush=True)
    json.dump(W, open(f"{D}/wf_params{tag}.json", "w"), indent=1)
