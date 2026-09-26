"""Intraday probabilistic strategy ("near-dead" buckets): forecast (ECMWF mx2t3 remaining max, NBM for US)
+ running observed max + current temperature + hour of day -> P(daily max in bucket), walk-forward.
Compared to and stacked with the market price; backtested with executable taker prints.

Outputs data/weather/near_dead_eval.parquet (bucket x decision rows with q, q_stack, q_mktcal, market state)."""
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from common import D
from evaluate import load_features, attach_ecmwf, bucket_table
from wf_model import intraday_exceed, INTRA
from backtest import market_probs


def model_intraday():
    F = attach_ecmwf(load_features())
    F["obs_now"] = np.where(F.unit == "F", F.obs_last_f, F.obs_last)
    # station-level walk-forward ECMWF bias (y - ec_max at D0 07h over the previous 30 days)
    from model import rolling_stats
    b = F[(F.dec == "D0 07h") & F.ec_max.notna()][["icao", "unit", "date", "y", "ec_max"]].copy().reset_index(drop=True)
    b["r"] = b.y - b.ec_max
    m, sd, n = rolling_stats(b, "icao", "r", window_days=30, min_n=10, gap_days=1)
    b["ec_bias"] = m
    F = F.merge(b[["icao", "unit", "date", "ec_bias"]], on=["icao", "unit", "date"], how="left")
    F["ec_rem_adj"] = F.ec_rem + F.ec_bias.fillna(0)
    F["ec_sofar_adj"] = F.ec_sofar + F.ec_bias.fillna(0)
    F = F[F.dec.isin(INTRA)]
    parts = []
    for dec in INTRA:
        x = F[F.dec == dec]
        fF = x[x.unit == "F"]; fC = x[x.unit == "C"]
        if len(fF):
            parts.append(intraday_exceed(fF, "ec_rem_adj", sofar_col="ec_sofar_adj", day_col="nbm_rem_max" if fF.nbm_rem_max.notna().mean() > .5 else None))
        if len(fC):
            parts.append(intraday_exceed(fC, "ec_rem_adj", sofar_col="ec_sofar_adj"))
        print(dec, flush=True)
    return pd.concat(parts, ignore_index=True)


def _logit(p):
    p = np.clip(p, 0.003, 0.997)
    return np.log(p / (1 - p))


def stack(B, cols, name, min_train_events=300):
    """Walk-forward (monthly expanding) logistic recalibration on bucket rows, per decision hour."""
    B[name] = np.nan
    B["month"] = pd.to_datetime(B.date).dt.to_period("M")
    for dec, g in B.groupby("dec"):
        for mo in sorted(g.month.unique()):
            tr = g[(g.month < mo)]
            te = g[g.month == mo]
            if tr.event_id.nunique() < min_train_events:
                continue
            X = np.column_stack([_logit(tr[c].values) for c in cols])
            lr = LogisticRegression(C=100.0, max_iter=1000).fit(X, tr.win.values)
            Xt = np.column_stack([_logit(te[c].values) for c in cols])
            B.loc[te.index, name] = lr.predict_proba(Xt)[:, 1]
    return B


def main():
    M = model_intraday()
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean]
    S = pd.read_parquet(f"{D}/market_state.parquet")
    S = S[S.dec.isin(INTRA)]
    B = bucket_table(M[M.pmf.notna()], R, S)
    B = market_probs(B, max_age_h=3.0)
    B = B[B.p_raw.notna()].reset_index(drop=True)   # need a fresh market price for comparison
    B["p_last"] = B.last_px.clip(0.001, 0.999)
    B = stack(B, ["p_last"], "q_mktcal")
    B = stack(B, ["p_last", "q"], "q_stack")
    B["dec_order"] = B.dec.str[3:5].astype(int)
    B.drop(columns=["month"]).to_parquet(f"{D}/near_dead_eval.parquet")
    print(B.shape, B.event_id.nunique(), B.date.min(), B.date.max())


if __name__ == "__main__":
    main()
