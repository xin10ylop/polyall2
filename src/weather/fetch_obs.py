"""Fetch METAR observations (routine+special) from IEM for all resolution stations; HKO daily max for Hong Kong."""
import os, sys, io, time
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from nethelp import get_text

D = "/home/user/polyall2/data/weather"
OUT = f"{D}/obs"
os.makedirs(OUT, exist_ok=True)


def iem_id(icao):
    return icao[1:] if (icao.startswith("K") and len(icao) == 4) else icao


def fetch_station(icao, start="2024-12-01", end="2026-09-27"):
    fp = f"{OUT}/{icao}.csv.gz"
    s = pd.Timestamp(start); e = pd.Timestamp(end)
    frames = []
    # chunk by ~6 months
    cur = s
    while cur < e:
        nxt = min(cur + pd.DateOffset(months=6), e)
        url = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
        params = [("station", iem_id(icao)), ("data", "tmpf"), ("year1", cur.year), ("month1", cur.month), ("day1", cur.day),
                  ("year2", nxt.year), ("month2", nxt.month), ("day2", nxt.day), ("tz", "Etc/UTC"), ("format", "onlycomma"),
                  ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("direct", "no"), ("report_type", "3"), ("report_type", "4")]
        # nethelp caches by url+params(dict) -> encode as dict with list values
        pdict = {}
        for k, v in params:
            pdict.setdefault(k, []).append(v)
        txt = get_text(url, pdict, ns="iem_asos", timeout=300)
        if txt:
            df = pd.read_csv(io.StringIO(txt), na_values=["M"])
            frames.append(df)
        cur = nxt
        time.sleep(1.0)
    df = pd.concat(frames).dropna(subset=["tmpf"]).drop_duplicates(["valid"])
    df.to_csv(fp, index=False, compression="gzip")
    return len(df)


def fetch_hko():
    import json
    from nethelp import get_json
    rows = []
    for dt, code in [("CLMMAXT", "max"), ("CLMMINT", "min")]:
        for yr in (2025, 2026):
            j = get_json("https://data.weather.gov.hk/weatherAPI/opendata/opendata.php",
                         {"dataType": dt, "rformat": "json", "station": "HKO", "year": yr}, ns="hko")
            for r in j.get("data", []):
                rows.append(dict(kind=code, date=f"{r[0]}-{int(r[1]):02d}-{int(r[2]):02d}", val=r[3], flag=r[4] if len(r) > 4 else None))
    pd.DataFrame(rows).to_csv(f"{OUT}/HKO_daily.csv", index=False)
    return len(rows)


if __name__ == "__main__":
    S = pd.read_csv(f"{D}/stations.csv")
    for icao in S.icao:
        if icao in ("HKO", "CWA46692"):
            continue
        if os.path.exists(f"{OUT}/{icao}.csv.gz"):
            continue
        try:
            n = fetch_station(icao)
            print(icao, n, flush=True)
        except Exception as ex:
            print(icao, "ERR", ex, flush=True)
    try:
        print("HKO", fetch_hko())
    except Exception as ex:
        print("HKO ERR", ex)
