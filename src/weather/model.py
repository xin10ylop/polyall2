"""Probabilistic model for the daily max (integer, market unit) and bucket probabilities.

Pre-peak decisions (no obs info):   Y ~ Dist(mu = f + bias_city, sigma)
Intraday decisions:                 Y = max(obs_max, Z),  Z ~ Dist(mu_Z, sigma_Z)
All parameters are fit strictly on data dated before the evaluated day (walk-forward).
"""
import json
import numpy as np
import pandas as pd
from scipy import stats

NU = 5.0  # Student-t degrees of freedom (fat tails); set None for Gaussian


def cdf(x, mu, sig, nu=NU):
    z = (x - mu) / sig
    return stats.t.cdf(z, nu) if nu else stats.norm.cdf(z)


def bucket_probs(los, his, mu, sig, obs_max=None, nu=NU):
    """Probabilities for buckets with inclusive integer bounds (None = open end)."""
    los = [(-np.inf if (l is None or (isinstance(l, float) and np.isnan(l))) else l) for l in los]
    his = [(np.inf if (h is None or (isinstance(h, float) and np.isnan(h))) else h) for h in his]
    def F(y):  # P(Y <= y) for integer-valued Y, y may be +-inf
        if y == np.inf:
            return 1.0
        if y == -np.inf:
            return 0.0
        if obs_max is not None and not np.isnan(obs_max) and y < obs_max:
            return 0.0
        return float(cdf(y + 0.5, mu, sig, nu))
    p = np.array([F(h) - F(l - 1) for l, h in zip(los, his)])
    p = np.clip(p, 0, 1)
    s = p.sum()
    return p / s if s > 0 else p


def rolling_stats(df, key, resid_col, date_col="date", window_days=60, min_n=15, gap_days=1):
    """For each row, mean/std of resid_col over rows of the same key with date in
    [date - gap - window, date - gap] (strictly before to avoid look-ahead)."""
    out_m = np.full(len(df), np.nan); out_s = np.full(len(df), np.nan); out_n = np.zeros(len(df))
    d = pd.to_datetime(df[date_col]).values
    for k, idx in df.groupby(key).indices.items():
        dd = d[idx]; rr = df[resid_col].values[idx]
        order = np.argsort(dd)
        dd = dd[order]; rr = rr[order]; ii = idx[order]
        for j in range(len(ii)):
            hi = dd[j] - np.timedelta64(gap_days, "D")
            lo = hi - np.timedelta64(window_days, "D")
            m = (dd <= hi) & (dd > lo) & ~np.isnan(rr)
            if m.sum() >= min_n:
                out_m[ii[j]] = rr[m].mean(); out_s[ii[j]] = rr[m].std(ddof=1); out_n[ii[j]] = m.sum()
    return out_m, out_s, out_n


def bucket_probs_pmf(los, his, obs_max, pmf, tail_decay=0.5):
    """Bucket probabilities from a pmf over E = Y - obs_max (last entry = 'K or more', spread geometrically)."""
    pmf = list(pmf)
    K = len(pmf) - 1
    vals = {}
    for k in range(K):
        vals[obs_max + k] = pmf[k]
    # spread the open-ended mass over K..K+10 geometrically
    w = np.array([tail_decay ** i for i in range(11)]); w = w / w.sum()
    for i in range(11):
        vals[obs_max + K + i] = pmf[K] * w[i]
    out = []
    for l, h in zip(los, his):
        l = -np.inf if l is None else l; h = np.inf if h is None else h
        out.append(sum(v for y, v in vals.items() if l <= y <= h))
    p = np.array(out)
    return p / p.sum() if p.sum() > 0 else p
