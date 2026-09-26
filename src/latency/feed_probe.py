"""Measure latency of PUBLIC observation feeds vs METAR observation time for weather-market stations.
Polls every 15 s: aviationweather.gov METAR API and api.weather.gov latest observation (NWS API).
Records first-seen UTC time of each new observation. Output: data/latency/feed_probe.jsonl"""
import os, time, json, datetime as dt, requests
OUT = os.path.join(os.path.dirname(__file__), "../../data/latency"); os.makedirs(OUT, exist_ok=True)
US = ["KLGA", "KATL", "KDAL", "KSEA", "KMIA", "KORD", "KLAX", "KBKF", "KAUS", "KHOU", "KSFO"]
INTL = ["EGLC", "LFPB", "EDDM", "LEMD", "LIMC", "EPWA", "EHAM", "CYYZ", "SBGR", "SAEZ", "MMMX"]
S = requests.Session(); S.headers["User-Agent"] = "polyall2-research (latency probe)"
seen = {}
def rec(src, st, obs_ts, extra):
    k = (src, st, obs_ts)
    if k in seen: return
    seen[k] = time.time()
    with open(f"{OUT}/feed_probe.jsonl", "a") as f:
        f.write(json.dumps({"src": src, "st": st, "obs": obs_ts, "first_seen": seen[k], "lag_s": seen[k] - obs_ts, **extra}) + "\n")
end = time.time() + float(os.environ.get("PROBE_MIN", 90)) * 60
while time.time() < end:
    t0 = time.time()
    try:
        for grp in (US[:6], US[6:], INTL[:6], INTL[6:]):
            d = S.get("https://aviationweather.gov/api/data/metar", params={"ids": ",".join(grp), "format": "json", "hours": 1}, timeout=15).json()
            for x in d:
                rec("awc", x["icaoId"], x["obsTime"], {"temp": x.get("temp"), "receipt": x.get("receiptTime")})
        for st in US:
            try:
                x = S.get(f"https://api.weather.gov/stations/{st}/observations/latest", timeout=15).json()["properties"]
                ts = dt.datetime.fromisoformat(x["timestamp"]).timestamp()
                rec("nws", st, ts, {"temp": (x.get("temperature") or {}).get("value")})
            except Exception:
                pass
    except Exception as e:
        print("err", e, flush=True)
    time.sleep(max(1, 15 - (time.time() - t0)))
