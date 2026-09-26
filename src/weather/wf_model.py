"""Walk-forward model: produces mu/sigma (and obs_max floor) per station-day-decision row.

Pre-peak decisions ('D-1 12h', 'D0 07h'):
    f = combination of available bias-corrected base forecasts (NBM TXN, ECMWF mx2t3 daily max, OM models)
    bias_s = rolling mean of (y - f_s) over the previous 60 days (only days whose max was already final)
    sigma  = rolling std of (y - f_comb) over previous 60 days, floored; Student-t(5) errors
Intraday decisions ('D0 11h','D0 14h','D0 17h'):
    Y = max(obs_max, Z); Z ~ t5(mu_Z, sigma_Z), mu_Z = f_rem + a_h + k_h*(obs_now - f_now) with (a_h, k_h, sigma_Z)
    fit by OLS on all rows strictly before the evaluation month (expanding window, pooled over stations).
"""
import numpy as np
import pandas as pd
from model import rolling_stats, NU

PRE = ("D-1 12h", "D0 07h")
INTRA = ("D0 11h", "D0 14h", "D0 16h", "D0 18h")
SIG_FLOOR = {"F": 1.2, "C": 0.7}


def add_base_forecasts(F):
    F = F.copy()
    om_cols = [c for c in ["om_ecmwf_ifs025", "om_gfs_seamless", "om_icon_seamless"] if c in F]
    if om_cols:
        F["f_om"] = F[om_cols].mean(axis=1)
    return F


def prepeak(F, sources, window=60):
    """F: rows of one decision type (all stations). sources: list of column names of raw base forecasts."""
    F = F.copy().reset_index(drop=True)
    gap = 2 if F.dec.iloc[0] == "D-1 12h" else 1
    bc = []
    for s in sources:
        if s not in F or F[s].notna().sum() == 0:
            continue
        F[f"r_{s}"] = F.y - F[s]
        m, sd, n = rolling_stats(F, "icao", f"r_{s}", window_days=window, min_n=15, gap_days=gap)
        F[f"bc_{s}"] = F[s] + m
        F[f"sd_{s}"] = sd
        bc.append(s)
    if not bc:
        F["mu"] = np.nan; F["sigma"] = np.nan
        return F
    F["mu"] = F[[f"bc_{s}" for s in bc]].mean(axis=1)  # equal-weight average of bias-corrected sources
    F["r_comb"] = F.y - F.mu
    m, sd, n = rolling_stats(F, "icao", "r_comb", window_days=window, min_n=15, gap_days=gap)
    # r_comb is already bias corrected; add residual mean drift too (small)
    # convert residual s.d. to Student-t scale (var of t_nu = scale^2 * nu/(nu-2))
    F["sigma"] = np.maximum(sd * np.sqrt((NU - 2) / NU), F.unit.map(SIG_FLOOR))
    return F


def intraday(F, rem_col, now_col, obs_now_col="obs_last_f", train_before=None):
    """F: rows of one intraday decision type. Fit (a, k, sigma) on rows with date < month start (expanding)."""
    F = F.copy().reset_index(drop=True)
    F["month"] = pd.to_datetime(F.date).dt.to_period("M")
    F["mu"] = np.nan; F["sigma"] = np.nan
    ok = F[rem_col].notna() & F[now_col].notna() & F[obs_now_col].notna() & F.z.notna()
    for mo in sorted(F.month.unique()):
        tr = F[ok & (F.month < mo)]
        te_idx = F.index[(F.month == mo) & F[rem_col].notna() & F[now_col].notna() & F[obs_now_col].notna()]
        if len(tr) < 200 or len(te_idx) == 0:
            continue
        X = np.column_stack([np.ones(len(tr)), (tr[obs_now_col] - tr[now_col]).values])
        yv = (tr.z - tr[rem_col]).values
        beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        res = yv - X @ beta
        sig = np.sqrt(np.mean(res ** 2)) * np.sqrt((NU - 2) / NU)
        te = F.loc[te_idx]
        F.loc[te_idx, "mu"] = te[rem_col] + beta[0] + beta[1] * (te[obs_now_col] - te[now_col])
        F.loc[te_idx, "sigma"] = max(sig, 0.5)
    return F


# ---------------------------------------------------------------------------------------------
# Intraday exceedance model: E = y - obs_max in {0,1,...,K+}; ordinal logit P(E >= k) = sigmoid(x.b - th_k)
# ---------------------------------------------------------------------------------------------
from scipy.optimize import minimize as _minimize
from scipy.special import expit as _expit

KMAX = {"F": 8, "C": 5}


def _ord_nll(params, X, e, K):
    nb = X.shape[1]
    b = params[:nb]
    th = np.cumsum(np.concatenate([[params[nb]], np.exp(params[nb + 1:])]))  # increasing thresholds (K of them)
    s = X @ b
    # P(E >= k) for k=1..K
    ge = _expit(s[:, None] - th[None, :])  # n x K
    ge = np.concatenate([np.ones((len(s), 1)), ge, np.zeros((len(s), 1))], axis=1)  # k=0..K+1
    p = ge[np.arange(len(s)), np.minimum(e, K)] - ge[np.arange(len(s)), np.minimum(e, K) + 1]
    return -np.mean(np.log(np.clip(p, 1e-9, 1))) + 1e-4 * np.sum(b ** 2)


def _ord_fit(X, e, K):
    nb = X.shape[1]
    x0 = np.concatenate([np.zeros(nb), [0.0], np.zeros(K - 1)])
    r = _minimize(_ord_nll, x0, args=(X, e, K), method="L-BFGS-B")
    return r.x


def _ord_pmf(params, X, K):
    nb = X.shape[1]
    b = params[:nb]
    th = np.cumsum(np.concatenate([[params[nb]], np.exp(params[nb + 1:])]))
    ge = _expit((X @ b)[:, None] - th[None, :])
    ge = np.concatenate([np.ones((len(X), 1)), ge, np.zeros((len(X), 1))], axis=1)
    return ge[:, :-1] - ge[:, 1:]  # P(E=k) k=0..K (last = K or more)


def exceed_features(F, rem_col, sofar_col=None, day_col=None):
    """Design matrix: forecast remaining max minus obs max, current temp minus obs max, and (optional)
    full-day forecast minus obs max. All in market unit."""
    d_fc = (F[rem_col] - F.obs_max).values
    d_now = (F.obs_now - F.obs_max).values
    cols = [np.ones(len(F)), np.clip(d_fc, -15, 15), np.clip(d_now, -15, 0), np.clip(d_fc, 0, 15)]
    if day_col is not None and day_col in F:
        cols.append(np.clip((F[day_col] - F.obs_max).fillna(0).values, -15, 15))
    return np.column_stack(cols)


def intraday_exceed(F, rem_col, day_col=None, min_train=300):
    """Walk-forward by month, pooled over stations of one unit. Adds columns pmf (json list) and mu/sigma NaN."""
    F = F.copy().reset_index(drop=True)
    F["month"] = pd.to_datetime(F.date).dt.to_period("M")
    F["pmf"] = None
    ok = F[rem_col].notna() & F.obs_max.notna() & F.obs_now.notna()
    for unit, gu in F[ok].groupby("unit"):
        K = KMAX[unit]
        for mo in sorted(gu.month.unique()):
            tr = gu[(gu.month < mo) & gu.y.notna()]
            te = gu[gu.month == mo]
            if len(tr) < min_train or len(te) == 0:
                continue
            Xtr = exceed_features(tr, rem_col, day_col=day_col)
            etr = np.clip((tr.y - tr.obs_max).values, 0, None).astype(int)
            par = _ord_fit(Xtr, etr, K)
            P = _ord_pmf(par, exceed_features(te, rem_col, day_col=day_col), K)
            for i, idx in enumerate(te.index):
                F.at[idx, "pmf"] = P[i].tolist()
    F["mu"] = np.where(F.pmf.notna(), 0.0, np.nan)  # placeholders so downstream filters keep rows
    F["sigma"] = np.where(F.pmf.notna(), 1.0, np.nan)
    return F
