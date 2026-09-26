"""Derive resolution station (ICAO) per event from description URLs; fetch station coords from aviationweather.gov."""
import json, re, os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from nethelp import get_json

D = "/home/user/polyall2/data/weather"


def station_of(desc):
    m = re.search(r"timeseries\?site=([A-Za-z0-9]{4})", desc)
    if m:
        return m.group(1).upper(), "NOAA"
    m = re.search(r"wunderground\.com/(?:history/daily/[^\s]*?/|weather/)([A-Z0-9]{4})\b", desc)
    if m:
        return m.group(1).upper(), "WU"
    if "weather.gov.hk" in desc:
        return "HKO", "HKO"
    if "cwa.gov.tw" in desc:
        return "CWA46692", "CWA"
    return None, None


def main():
    E = pd.read_parquet(f"{D}/events.parquet")
    descs = json.load(open(f"{D}/descriptions.json"))
    T = E[E.kind != "other"].copy()
    st = T.desc_hash.map(lambda h: station_of(descs.get(h, "")))
    T["icao"] = [s[0] for s in st]
    T["source"] = [s[1] for s in st]
    T["unit"] = T.desc_hash.map(lambda h: "C" if "degrees Celsius" in descs.get(h, "") else ("F" if "degrees Fahrenheit" in descs.get(h, "") else "?"))
    T[["event_id", "slug", "kind", "city", "icao", "source", "unit"]].to_parquet(f"{D}/event_station.parquet")
    print(T.groupby(["icao", "source"]).size().to_string())
    icaos = sorted(set(i for i in T.icao if i and len(i) == 4))
    j = get_json("https://aviationweather.gov/api/data/stationinfo", {"ids": ",".join(icaos), "format": "json"}, ns="awc")
    rows = [dict(icao=x["icaoId"], name=x.get("site"), lat=x["lat"], lon=x["lon"], elev=x.get("elev"), country=x.get("country")) for x in j]
    S = pd.DataFrame(rows)
    # Hong Kong Observatory HQ (resolution source for HK), approx coords
    S = pd.concat([S, pd.DataFrame([dict(icao="HKO", name="Hong Kong Observatory HQ", lat=22.3019, lon=114.1742, elev=32, country="HK"),
                                    dict(icao="CWA46692", name="CWA Taipei station 466920", lat=25.0377, lon=121.5149, elev=6, country="TW")])])
    S.to_csv(f"{D}/stations.csv", index=False)
    print(S.to_string())
    missing = set(icaos) - set(S.icao)
    print("missing", missing)


if __name__ == "__main__":
    main()
