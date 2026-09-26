"""Empirical 'remaining rise' model for daily max (and 'remaining drop' for daily min) from IEM ASOS history.
For station s, local hour H, running extreme R_H (so far), current temp T_H:
   rise = FinalMax - R_H  (>=0);  deficit = R_H - T_H  (>=0)
Table P(rise >= k | s, H, deficit_bin, season) with shrinkage to all-station pooled estimates.
Temperatures converted to the market unit: US stations integer °F (IEM tmpf rounded), others integer °C.
Walk-forward: fit(end_date) uses only days < end_date."""
import os, glob, math, json
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder
ROOT = os.path.join(os.path.dirname(__file__), "../..")
TF = TimezoneFinder()
ST = pd.read_csv(f"{ROOT}/data/weather/stations.csv").set_index("icao")
US_F = {"KLGA", "KATL", "KDAL", "KSEA", "KMIA", "KORD", "KLAX", "KBKF", "KAUS", "KHOU", "KSFO", "KDEN", "KJFK", "KBOS", "KPHX", "KIAH", "KDFW"}

def unit_for(icao): return "F" if icao.startswith("K") else "C"

def load_station(icao):
    fn = f"{ROOT}/data/weather/obs/{icao}.csv.gz"
    if not os.path.exists(fn): return None
    d = pd.read_csv(fn).dropna(subset=["tmpf"])
    tz = TF.timezone_at(lat=float(ST.loc[icao, "lat"]), lng=float(ST.loc[icao, "lon"]))
    t = pd.to_datetime(d["valid"], utc=True).dt.tz_convert(tz)
    u = unit_for(icao)
    if u == "F": temp = np.floor(d["tmpf"].values + 0.5)
    else: temp = np.round((d["tmpf"].values - 32) * 5 / 9)
    out = pd.DataFrame({"ltime": t, "temp": temp})
    out["day"] = out.ltime.dt.date; out["hour"] = out.ltime.dt.hour + out.ltime.dt.minute / 60
    out["month"] = out.ltime.dt.month
    return out

def features(o):
    """per (day, obs): running max/min so far, final max/min, deficit"""
    o = o.sort_values("ltime").copy()
    g = o.groupby("day")
    o["rmax"] = g.temp.cummax(); o["rmin"] = g.temp.cummin()
    o["fmax"] = g.temp.transform("max"); o["fmin"] = g.temp.transform("min")
    o["nobs"] = g.temp.transform("size")
    o = o[o.nobs >= 18]  # need a reasonably complete day
    o["rise"] = o.fmax - o.rmax; o["drop"] = o.rmin - o.fmin
    o["def_hi"] = (o.rmax - o.temp).clip(0, 4); o["def_lo"] = (o.temp - o.rmin).clip(0, 4)
    return o

class RiseModel:
    def __init__(self, stations, end_date=None, kind="highest"):
        self.kind = kind; rows = []
        for s in stations:
            o = load_station(s)
            if o is None: continue
            f = features(o); f["st"] = s
            if end_date is not None: f = f[pd.to_datetime(f.day) < pd.Timestamp(end_date)]
            rows.append(f)
        self.df = pd.concat(rows, ignore_index=True)
        self.df["hb"] = self.df.hour.astype(int)
        v = "rise" if kind == "highest" else "drop"; dcol = "def_hi" if kind == "highest" else "def_lo"
        self.df["x"] = self.df[v]; self.df["dd"] = self.df[dcol].astype(int)
        self.df["season"] = self.df.month.map(lambda m: (m % 12) // 3)
        self.tab = {}
        for keys in [("st", "hb", "dd", "season"), ("st", "hb", "dd"), ("hb", "dd", "season"), ("hb", "dd")]:
            g = self.df.groupby(list(keys)).x
            self.tab[keys] = {"n": g.size(), **{k: g.apply(lambda s, k=k: (s >= k).mean()) for k in (1, 2, 3, 4, 5)}}

    def p_ge(self, st, hour, dd, month, k, min_n=40):
        """P(remaining rise (or drop) >= k)."""
        if k <= 0: return 1.0
        k = min(k, 5); season = (month % 12) // 3; hb = int(hour); dd = int(min(max(dd, 0), 4))
        for keys, key in [(("st", "hb", "dd", "season"), (st, hb, dd, season)), (("st", "hb", "dd"), (st, hb, dd)),
                          (("hb", "dd", "season"), (hb, dd, season)), (("hb", "dd"), (hb, dd))]:
            t = self.tab[keys]
            if key in t["n"].index and t["n"][key] >= min_n:
                return float(t[k][key])
        return 0.5
