"""End-to-end evaluation for a set of stations and forecast sources.
python run_eval.py <tag> <pre_sources comma> <intraday: nbm|ec> [stations...]"""
import sys, json
import numpy as np
import pandas as pd
from common import D
from evaluate import load_features, attach_ecmwf, model_rows, bucket_table
from wf_model import add_base_forecasts
from backtest import market_probs


def main(tag, pre_sources, intra, stations):
    F = add_base_forecasts(attach_ecmwf(load_features(stations)))
    F["obs_now"] = np.where(F.unit == "F", F.obs_last_f, F.obs_last)
    if intra == "nbm":
        rem, now = "nbm_rem_max", "nbm_tmp_now"
    else:
        rem, now = "ec_rem", "ec_sofar"
        F["obs_now"] = F.obs_max  # compare obs max-so-far with forecast max-so-far
    M = model_rows(F, pre_sources, rem, now)
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    R = R[(R.kind == "highest") & R.clean]
    if stations:
        R = R[R.icao.isin(stations)]
    S = pd.read_parquet(f"{D}/market_state.parquet")
    B = bucket_table(M, R, S)
    B = market_probs(B)
    B.to_parquet(f"{D}/eval_{tag}.parquet")
    print(tag, B.shape, B.event_id.nunique())
    return B


if __name__ == "__main__":
    tag = sys.argv[1]; pre = sys.argv[2].split(","); intra = sys.argv[3]; st = sys.argv[4:] or None
    main(tag, pre, intra, st)
