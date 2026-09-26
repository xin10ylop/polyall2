"""Raw taker trades (exact timestamps) restricted to the target local day window [D 00:00, D+1 06:00 local]
for closed 'highest' (and 'lowest') temperature events since START. Used for the same-day observation
(dead-bucket) strategy and its latency analysis.
Stored per month: data/weather/raw_d0/<YYYY-MM>.parquet with
  event_id, ts, mi, oi (0 YES token / 1 NO token), side (+1 BUY/-1 SELL, taker), price, size, w (crc32 of taker wallet)."""
import os, sys, time, zlib, random, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import requests
from common import D, TZ
from features import local_ts

OUT = f"{D}/raw_d0"
os.makedirs(OUT, exist_ok=True)
URL = "https://data-api.polymarket.com/trades"
_local = threading.local()


def get(params, tries=10):
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    d = 2
    for i in range(tries):
        try:
            r = _local.s.get(URL, params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(d + random.random()); d = min(d * 2, 120); continue
            return None
        except requests.RequestException:
            time.sleep(d + random.random()); d = min(d * 2, 120)
    return None


def fetch(ev, cids):
    j = get(dict(eventId=ev.event_id, limit=10000))
    if j is None:
        return None
    if len(j) >= 10000:
        j = []
        for c in cids:
            jj = get(dict(market=c, limit=10000))
            if jj is None:
                return None
            j.extend(jj)
    c2i = {c: i for i, c in enumerate(cids)}
    t0 = local_ts(pd.Timestamp(ev.date).date(), 0, TZ[ev.icao]).timestamp()
    t1 = t0 + 30 * 3600
    rows = [(int(ev.event_id), int(x["timestamp"]), c2i.get(x.get("conditionId"), -1), int(x.get("outcomeIndex", -1)),
             1 if x.get("side") == "BUY" else -1, float(x["price"]), float(x["size"]),
             zlib.crc32((x.get("proxyWallet") or "").lower().encode()))
            for x in j if t0 <= int(x["timestamp"]) < t1]
    return rows


def main(start="2026-05-01", kinds=("highest",), workers=4):
    R = pd.read_parquet(f"{D}/events_resolved.parquet")
    M = pd.read_parquet(f"{D}/markets.parquet")
    R = R[R.kind.isin(kinds) & R.clean & R.icao.isin(list(TZ))].copy()
    R["date"] = pd.to_datetime(R.date, errors="coerce")
    R = R[R.date >= start]
    cids = {k: list(g.conditionId) for k, g in M.groupby("event_id")}
    R["month"] = R.date.dt.strftime("%Y-%m")
    for mo, g in sorted(R.groupby("month")):
        fp = f"{OUT}/{mo}_{'-'.join(kinds)}.parquet"
        if os.path.exists(fp):
            continue
        rows = []; fails = 0; t = time.time()
        with ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(fetch, ev, cids[ev.event_id]) for _, ev in g.iterrows()]
            for f in as_completed(futs):
                r = f.result()
                if r is None:
                    fails += 1
                else:
                    rows.extend(r)
        df = pd.DataFrame(rows, columns=["event_id", "ts", "mi", "oi", "side", "price", "size", "w"])
        df = df.astype({"event_id": "int32", "ts": "int32", "mi": "int8", "oi": "int8", "side": "int8",
                        "price": "float32", "size": "float32", "w": "uint32"}).sort_values(["event_id", "ts"])
        df.to_parquet(fp, compression="zstd", compression_level=9)
        print(mo, len(g), "events", len(df), "trades", fails, "fails", round(time.time() - t), "s", flush=True)


if __name__ == "__main__":
    main(start=sys.argv[1] if len(sys.argv) > 1 else "2026-05-01")
