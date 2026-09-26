"""Observation processing: METAR-based daily max per station/local date (in the market's unit) + intraday max-so-far."""
import os
import numpy as np
import pandas as pd
from common import D, TZ, f2c, round_half_up

US_F = {"KATL", "KAUS", "KBKF", "KDAL", "KDCA", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KPHX", "KSEA", "KSFO"}


def load_obs(icao, unit):
    fp = f"{D}/obs/{icao}.csv.gz"
    if not os.path.exists(fp):
        return None
    df = pd.read_csv(fp)
    df["utc"] = pd.to_datetime(df["valid"], utc=True)
    df = df.dropna(subset=["tmpf"])
    # drop absurd values
    df = df[(df.tmpf > -80) & (df.tmpf < 135)]
    if unit == "F":
        df["t"] = round_half_up(df.tmpf.values)  # whole deg F as displayed by WU/NOAA
    else:
        df["t"] = round_half_up(f2c(df.tmpf.values))  # METAR whole deg C
    loc = df.utc.dt.tz_convert(TZ[icao])
    df["ldate"] = loc.dt.date
    df["lhour"] = loc.dt.hour + loc.dt.minute / 60.0
    return df[["utc", "ldate", "lhour", "t", "tmpf"]].sort_values("utc").reset_index(drop=True)


def daily_max(obs):
    g = obs.groupby("ldate")
    out = g.agg(tmax=("t", "max"), nobs=("t", "size"), tmin=("t", "min"))
    return out


if __name__ == "__main__":
    for icao, unit in [("KATL", "F"), ("EGLC", "C")]:
        o = load_obs(icao, unit)
        print(icao, len(o), o.head(3))
        print(daily_max(o).tail(5))
