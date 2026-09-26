"""Fetch archived model forecasts at fixed lead offsets from open-meteo Previous Runs API.

temperature_2m_previous_dayN(t) = value predicted N*24h before valid time t (run init <= t - N*24h).
Conservative availability assumption used downstream: dayN value for valid time t is usable at decision time tau
iff t - N*24h + 8h <= tau (8h = generous model-run production + dissemination latency).
"""
import os, sys, time
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from nethelp import get_json

D = "/home/user/polyall2/data/weather"
OUT = f"{D}/fc"
os.makedirs(OUT, exist_ok=True)
MODELS = ["best_match", "ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
VARS = ["temperature_2m", "temperature_2m_previous_day1", "temperature_2m_previous_day2", "temperature_2m_previous_day3"]


def fetch(icao, lat, lon, start="2024-12-01", end="2026-09-27"):
    fp = f"{OUT}/{icao}.parquet"
    if os.path.exists(fp):
        return None
    frames = []
    cur = pd.Timestamp(start)
    e = pd.Timestamp(end)
    while cur <= e:
        nxt = min(cur + pd.DateOffset(months=5) - pd.Timedelta(days=1), e)
        j = get_json("https://previous-runs-api.open-meteo.com/v1/forecast",
                     {"latitude": lat, "longitude": lon, "hourly": ",".join(VARS), "models": ",".join(MODELS),
                      "start_date": cur.strftime("%Y-%m-%d"), "end_date": nxt.strftime("%Y-%m-%d"), "timezone": "GMT"},
                     ns="om_prev", timeout=180)
        if "hourly" not in j:
            raise RuntimeError(str(j)[:300])
        h = pd.DataFrame(j["hourly"])
        frames.append(h)
        cur = nxt + pd.Timedelta(days=1)
        time.sleep(15)
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df.to_parquet(fp, compression="zstd")
    return len(df)


if __name__ == "__main__":
    S = pd.read_csv(f"{D}/stations.csv")
    first = sys.argv[1:] if len(sys.argv) > 1 else None
    for _, r in S.iterrows():
        if first and r.icao not in first:
            continue
        try:
            n = fetch(r.icao, r.lat, r.lon)
            print(r.icao, n, flush=True)
        except Exception as ex:
            print(r.icao, "ERR", ex, flush=True)
            time.sleep(60)
