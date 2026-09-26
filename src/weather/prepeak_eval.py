"""Pre-peak forecast model (D-1 12:00 and D0 07:00 local) for all cities:
bias-corrected ECMWF IFS daily max (mx2t3) + NBM TXN (US) + Open-Meteo (NYC only), Student-t errors with rolling
per-station sigma; compared with market, stacked, and backtested with executable prints."""
import sys
import numpy as np
import pandas as pd
from common import D
from evaluate import load_features, attach_ecmwf, bucket_table
from wf_model import prepeak, PRE, add_base_forecasts
from backtest import market_probs, simulate, summarize
from near_dead import stack
from near_dead_report import bucket_logloss


def build():
    F = add_base_forecasts(attach_ecmwf(load_features()))
    F = F[F.dec.isin(PRE)]
    parts = []
    for dec in PRE:
        x = F[F.dec == dec]
        parts.append(prepeak(x, ["ec_max", "nbm_txn", "f_om"]))
    M = pd.concat(parts, ignore_index=True)
    M["obs_max"] = np.nan
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean]
    S = pd.read_parquet(f"{D}/market_state.parquet")
    S = S[S.dec.isin(PRE)]
    B = bucket_table(M[M.mu.notna() & M.sigma.notna()], R, S)
    B = market_probs(B, max_age_h=6.0)
    B = B[B.p_raw.notna()].reset_index(drop=True)
    B["p_last"] = B.last_px.clip(0.001, 0.999)
    B = stack(B, ["p_last"], "q_mktcal", min_train_events=300)
    B = stack(B, ["p_last", "q"], "q_stack", min_train_events=300)
    B["dec_order"] = np.where(B.dec == "D-1 12h", 0, 1)
    B.drop(columns=["month"]).to_parquet(f"{D}/prepeak_eval.parquet")
    return B, M


if __name__ == "__main__":
    B, M = build()
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
    B["date"] = pd.to_datetime(B.date)
    # point-forecast skill
    m = M[M.mu.notna() & M.y.notna() & (pd.to_datetime(M.date) >= "2026-03-15")]
    print("pre-peak point skill (Mar 15+):")
    print(m.groupby(["dec", "unit"]).apply(lambda g: pd.Series(dict(n=len(g), mae=(g.y - g.mu).abs().mean(), sd=(g.y - g.mu).std(), sigma=g.sigma.mean()))).round(3))
    X = B[B.q_stack.notna()]
    print("period", X.date.min().date(), X.date.max().date(), "events", X.event_id.nunique())
    for dec, g in X.groupby("dec"):
        print(dec, "events", g.event_id.nunique(), " ".join(f"LL_{c}={bucket_logloss(g[c].values, g.win.values).mean():.4f}" for c in ["p_last", "q", "q_mktcal", "q_stack"]))
    X = X.assign(half=np.where(X.date < "2026-07-01", "A: Mar-Jun", "B: Jul-Sep (holdout)"))
    rows = []
    for qc in ["q", "q_stack"]:
        for thr in [0.02, 0.05, 0.08, 0.12]:
            for sides in [("yes",), ("no",)]:
                T = simulate(X, thr=thr, fill="prints", stake=20.0, frac=0.5, qcol=qc, sides=sides, pmin=0.02, pmax=0.98)
                for half, t in T.groupby("half"):
                    s = summarize(t).to_dict(); s.update(q=qc, thr=thr, side=sides[0], half=half); rows.append(s)
    Rr = pd.DataFrame(rows)
    print(Rr[["q", "thr", "side", "half", "n", "hit", "avg_px", "avg_edge", "staked", "pnl", "roi", "maxdd", "t_stat"]].round(4).to_string())
    Rr.to_csv(f"{D}/prepeak_sims.csv", index=False)
