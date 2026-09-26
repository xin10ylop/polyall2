"""Assemble model probabilities vs market prices per (event, decision, bucket); score and backtest trading rules.

Usage: python evaluate.py <source_set>
Outputs data/weather/eval_<tag>.parquet (long table) used by backtest.py
"""
import sys, json, os, glob
import numpy as np
import pandas as pd
from common import D, TZ
from model import bucket_probs, bucket_probs_pmf
from wf_model import prepeak, intraday, intraday_exceed, PRE, INTRA, add_base_forecasts


def load_features(stations=None):
    fs = sorted(glob.glob(f"{D}/feat/*.parquet"))
    out = []
    for f in fs:
        icao, unit = os.path.basename(f)[:-8].rsplit("_", 1)
        if stations and icao not in stations:
            continue
        out.append(pd.read_parquet(f))
    F = pd.concat(out, ignore_index=True)
    F["date"] = pd.to_datetime(F.date)
    return F


def attach_ecmwf(F):
    fp = f"{D}/ecmwf_daily.parquet"
    if not os.path.exists(fp):
        return F
    E = pd.read_parquet(fp)  # icao, unit, date, dec, ec_max, ec_rem, ec_now
    E["date"] = pd.to_datetime(E.date)
    return F.merge(E, on=["icao", "unit", "date", "dec"], how="left")


def model_rows(F, sources_pre, rem_col, now_col, intra_kind="exceed", day_col=None):
    parts = []
    for dec in PRE:
        x = F[F.dec == dec]
        if len(x):
            parts.append(prepeak(x, sources_pre))
    for dec in INTRA:
        x = F[F.dec == dec]
        if len(x):
            if intra_kind == "exceed":
                parts.append(intraday_exceed(x, rem_col, day_col=day_col))
            else:
                parts.append(intraday(x, rem_col, now_col, obs_now_col="obs_now"))
    return pd.concat(parts, ignore_index=True)


def bucket_table(M, R, S):
    """M: model rows (icao,unit,date,dec,mu,sigma,obs_max). R: resolved events. S: market state."""
    R = R.copy(); R["date"] = pd.to_datetime(R.date)
    if "pmf" not in M:
        M = M.assign(pmf=None)
    X = R.merge(M[["icao", "unit", "date", "dec", "mu", "sigma", "obs_max", "y", "pmf"]], on=["icao", "unit", "date"])
    X = X[X.mu.notna() & X.sigma.notna()]
    rows = []
    for _, r in X.iterrows():
        los = json.loads(r.los); his = json.loads(r.his)
        if r.dec in INTRA and r.pmf is not None:
            p = bucket_probs_pmf(los, his, r.obs_max, r.pmf)
        else:
            om = r.obs_max if r.dec in INTRA else None
            p = bucket_probs(los, his, r.mu, r.sigma, obs_max=om)
        for j, q in enumerate(p):
            rows.append((r.event_id, r.dec, j, q, int(j == r.win_idx)))
    B = pd.DataFrame(rows, columns=["event_id", "dec", "mi", "q", "win"])
    B = B.merge(S, on=["event_id", "dec", "mi"], how="left")
    B = B.merge(R[["event_id", "city", "icao", "unit", "date", "fees", "n_b", "slug"]], on="event_id", how="left")
    return B
