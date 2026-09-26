"""Market-only calibration: are last-traded bucket prices calibrated vs realized outcomes?"""
import json
import numpy as np
import pandas as pd
from common import D


def load_long():
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    S = pd.read_parquet(f"{D}/market_state.parquet")
    R = R[(R.kind == "highest") & R.clean]
    S = S.merge(R[["event_id", "city", "icao", "unit", "date", "win_idx", "fees", "n_b", "los", "his"]], on="event_id")
    S["win"] = (S.mi == S.win_idx).astype(int)
    S["date"] = pd.to_datetime(S.date)
    return S


def calib_table(S, px="last_px", bins=(0, .02, .05, .1, .2, .3, .4, .5, .6, .7, .8, .9, .95, .98, 1)):
    x = S.dropna(subset=[px]).copy()
    x["bin"] = pd.cut(x[px], bins, include_lowest=True)
    g = x.groupby("bin", observed=True).agg(n=("win", "size"), px=(px, "mean"), freq=("win", "mean"))
    g["se"] = np.sqrt(g.freq * (1 - g.freq) / g.n)
    g["freq-px"] = g.freq - g.px
    return g


if __name__ == "__main__":
    S = load_long()
    pd.set_option("display.width", 200)
    for dec in ["D-1 12h", "D0 07h", "D0 11h", "D0 14h", "D0 17h"]:
        x = S[(S.dec == dec) & (S.last_age_h < 6)]
        print("==", dec, "rows", len(x), "events", x.event_id.nunique())
        print(calib_table(x).round(4).to_string())
