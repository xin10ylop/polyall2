"""Adverse selection of 2-sided quoting in weather temperature markets as a function of time relative to
the station-LOCAL start of the target day (local midnight), using station timezone from the rules' ICAO."""
import os, sys, json, re, math, datetime as dt
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder
sys.path.insert(0, os.path.dirname(__file__))
import hist_quote_as2 as H
ROOT = os.path.join(os.path.dirname(__file__), "../..")
TF = TimezoneFinder()
st = pd.read_csv(f"{ROOT}/data/weather/stations.csv").set_index("icao")
MON = {m: i for i, m in enumerate(["january","february","march","april","may","june","july","august","september","october","november","december"], 1)}
data = H.load(f"{ROOT}/data/sample_weather_recent.jsonl")
rx = re.compile(r"(?:site=|/history/daily/[^\s]*?/)([A-Za-z0-9]{4})\b")
ok = []
for m in data:
    s = rx.search(m["desc"]); q = m["q"].lower()
    md = re.search(r" on (\w+) (\d+)", q)
    if not s or not md or md.group(1) not in MON: continue
    icao = s.group(1).upper()
    if icao not in st.index: continue
    tz = TF.timezone_at(lat=float(st.loc[icao, "lat"]), lng=float(st.loc[icao, "lon"]))
    yr = dt.datetime.utcfromtimestamp(m["end"]).year
    day = dt.date(yr, MON[md.group(1)], int(md.group(2)))
    m["local0"] = dt.datetime.combine(day, dt.time(0, 0), ZoneInfo(tz)).timestamp()
    # hours relative to local midnight of target day expressed through "end" for run_one: hte = (end - t)/3600
    # we want window in hours BEFORE local midnight: hb = (local0 - t)/3600  => shift: set m['end'] = local0
    m["end"] = m["local0"]
    ok.append(m)
print("markets with station tz", len(ok), "of", len(data))
for d in [0.01, 0.02, 0.03]:
    for (hmin, hmax, lab) in [(24, 1e9, "before D-1 local midnight"), (12, 24, "D-1 00-12 local"), (6, 12, "D-1 12-18 local"),
                              (0, 6, "D-1 18-24 local"), (-6, 0, "D 00-06 local"), (-10, -6, "D 06-10 local"), (-14, -10, "D 10-14"), (-30, -14, "D 14-end+")]:
        R = H.run(ok, d=d, hmin=hmin, hmax=hmax)
        if R.empty: continue
        md = R.mins.sum() / 1440
        print(f"d={d:.2f} {lab:28s} mkts={len(R):5d} mkt_days={md:7.1f} fills={R.fills.sum():6d} per_mkt_day=${R.pnl.sum() / md:7.3f}")
