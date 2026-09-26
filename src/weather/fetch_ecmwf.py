"""ECMWF IFS HRES open data (AWS bucket ecmwf-forecasts), param mx2t3 (max 2m temperature in last 3h), 0.25 deg.
For each run (00z, 12z) and steps 3..57h: byte-range download of just the mx2t3 GRIB message, bilinear
interpolation to every resolution station. Output: data/weather/ecmwf/<run>.parquet with (run, step, icao, mx2t3_C).
Exact run times are kept so downstream code can enforce availability (run + 8h <= decision time)."""
import os, sys, json, time, random, tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import requests
import pygrib

D = "/home/user/polyall2/data/weather"
OUT = f"{D}/ecmwf"
os.makedirs(OUT, exist_ok=True)
BASE = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"
STEPS = list(range(3, 58, 3))
S = pd.read_csv(f"{D}/stations.csv")


def get(url, headers=None, tries=6):
    d = 1
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code in (200, 206):
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(d + random.random()); d *= 2
    return None


def interp(vals, lat, lon):
    # grid: lat 90..-90 step .25 (721), lon -180..179.75 (1440)
    fi = (90 - lat) / 0.25
    fj = (lon + 180) / 0.25
    i0 = int(np.floor(fi)); j0 = int(np.floor(fj)) % 1440
    i1 = min(i0 + 1, 720); j1 = (j0 + 1) % 1440
    di = fi - np.floor(fi); dj = fj - np.floor(fj)
    return (vals[i0, j0] * (1 - di) * (1 - dj) + vals[i1, j0] * di * (1 - dj) +
            vals[i0, j1] * (1 - di) * dj + vals[i1, j1] * di * dj)


def fetch_run(run):
    tag = run.strftime("%Y%m%d%H")
    fp = f"{OUT}/{tag}.parquet"
    if os.path.exists(fp):
        return tag, -1
    ymd = run.strftime("%Y%m%d"); hh = run.strftime("%H")
    rows = []
    for st in STEPS:
        stem = f"{BASE}/{ymd}/{hh}z/ifs/0p25/oper/{ymd}{hh}0000-{st}h-oper-fc"
        ri = get(stem + ".index")
        if ri is None:
            continue
        ent = None
        for line in ri.text.splitlines():
            d = json.loads(line)
            if d.get("param") == "mx2t3":
                ent = d; break
        if ent is None:
            continue
        rg = get(stem + ".grib2", headers={"Range": f"bytes={ent['_offset']}-{ent['_offset'] + ent['_length'] - 1}"})
        if rg is None:
            continue
        with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
            tf.write(rg.content); tf.flush()
            g = pygrib.open(tf.name)
            m = g.message(1)
            vals = m.values
            g.close()
        for _, s in S.iterrows():
            rows.append((run, st, s.icao, float(interp(vals, s.lat, s.lon)) - 273.15))
    if not rows:
        return tag, 0
    df = pd.DataFrame(rows, columns=["run", "step", "icao", "mx2t3"])
    df.to_parquet(fp, compression="zstd")
    return tag, len(df)


def main(start, end, workers=6):
    runs = []
    for d in pd.date_range(start, end, freq="D"):
        for h in (0, 12):
            runs.append(pd.Timestamp(d.year, d.month, d.day, h, tz="UTC"))
    runs = [r for r in runs if not os.path.exists(f"{OUT}/{r.strftime('%Y%m%d%H')}.parquet")]
    print("runs todo", len(runs), flush=True)
    t0 = time.time(); n = 0
    with ThreadPoolExecutor(workers) as ex:
        for f in as_completed([ex.submit(fetch_run, r) for r in runs]):
            tag, k = f.result(); n += 1
            if n % 20 == 0:
                print(n, tag, k, round(time.time() - t0), flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6)
