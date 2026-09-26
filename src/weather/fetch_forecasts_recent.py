"""Fetch last ~3 months of previous_dayN forecasts from the main open-meteo forecast API (it serves
previous_dayN variables for dates within its rolling ~3-month archive window). Same semantics as Previous Runs API."""
import os, sys, time
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from nethelp import get_json

D = "/home/user/polyall2/data/weather"
OUT = f"{D}/fc_recent"
os.makedirs(OUT, exist_ok=True)
MODELS = ["best_match", "ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
VARS = ["temperature_2m", "temperature_2m_previous_day1", "temperature_2m_previous_day2", "temperature_2m_previous_day3"]


def fetch(icao, lat, lon, start, end):
    fp = f"{OUT}/{icao}.parquet"
    if os.path.exists(fp):
        return None
    j = get_json("https://api.open-meteo.com/v1/forecast",
                 {"latitude": lat, "longitude": lon, "hourly": ",".join(VARS), "models": ",".join(MODELS),
                  "start_date": start, "end_date": end, "timezone": "GMT"}, ns="om_recent", timeout=180, max_tries=4)
    if "hourly" not in j:
        raise RuntimeError(str(j)[:300])
    df = pd.DataFrame(j["hourly"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df.to_parquet(fp, compression="zstd")
    return len(df)


if __name__ == "__main__":
    start, end = sys.argv[1], sys.argv[2]
    S = pd.read_csv(f"{D}/stations.csv")
    for _, r in S.iterrows():
        try:
            n = fetch(r.icao, r.lat, r.lon, start, end)
            print(r.icao, n, flush=True)
        except Exception as ex:
            print(r.icao, "ERR", ex, flush=True)
        time.sleep(3)
