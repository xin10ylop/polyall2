"""Fetch taker trades (data-api) for every closed temperature event; store compact per-event parquet.

Columns: ts (int64 unix s), mi (int8 market index within event, as ordered in markets.parquet),
         oi (int8 outcomeIndex: 0=YES token, 1=NO token), side (int8 +1 BUY / -1 SELL, taker side),
         price (float32), size (float32 shares), w (uint32 hash of taker proxyWallet)
Takes care of the 10k-per-query cap by falling back to per-market queries.
"""
import os, sys, json, time, zlib, random, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import requests

OUTDIR = "/home/user/polyall2/data/weather/trade_bars"
BAR = 600  # seconds
os.makedirs(OUTDIR, exist_ok=True)
URL = "https://data-api.polymarket.com/trades"
_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def get(params, tries=10):
    delay = 2
    for i in range(tries):
        try:
            r = sess().get(URL, params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(delay + random.random()); delay = min(delay * 2, 120); continue
            return None
        except requests.RequestException:
            time.sleep(delay + random.random()); delay = min(delay * 2, 120)
    return None


def to_bars(df):
    """Convert taker trades to YES-equivalent 10-min bars per market.
    YES-equivalent price: YES token trades at p; NO token trades at 1-p with side flipped.
    'lift' = taker buys YES-equivalent (evidence of the YES ask), 'hit' = taker sells YES-equivalent (YES bid).
    Shares are YES-equivalent contracts (a NO share maps to one YES-equivalent share)."""
    if df.empty:
        return pd.DataFrame(columns=["bt", "mi", "kind", "vwap", "pmin", "pmax", "shares", "n", "nw"])
    d = df.copy()
    isno = d.oi == 1
    d["py"] = np.where(isno, 1 - d.price, d.price)
    d["sy"] = np.where(isno, -d.side, d.side)
    d["bt"] = (d.ts // BAR) * BAR
    d["kind"] = np.where(d.sy > 0, 1, -1).astype("int8")  # 1 lift (buy yes), -1 hit (sell yes)
    d["pv"] = d.py * d["size"]
    g = d.groupby(["bt", "mi", "kind"])
    out = g.agg(pv=("pv", "sum"), shares=("size", "sum"), pmin=("py", "min"), pmax=("py", "max"), n=("py", "size"),
                nw=("w", "nunique")).reset_index()
    out["vwap"] = (out.pv / out.shares).astype("float32")
    out = out.drop(columns="pv")
    return out.astype({"bt": "int64", "mi": "int8", "kind": "int8", "pmin": "float32", "pmax": "float32",
                       "shares": "float32", "n": "int32", "nw": "int16"})


def fetch_event(event_id, markets):
    """markets: DataFrame rows of this event (conditionId ordered)."""
    fp = os.path.join(OUTDIR, f"{event_id}.parquet")
    if os.path.exists(fp):
        return event_id, -1, False
    cid2i = {c: i for i, c in enumerate(markets.conditionId)}
    j = get(dict(eventId=event_id, limit=10000))
    if j is None:
        return event_id, None, False
    trunc = False
    if len(j) >= 10000:
        j = []
        for c in markets.conditionId:
            jj = get(dict(market=c, limit=10000))
            if jj is None:
                return event_id, None, False
            if len(jj) >= 10000:
                trunc = True
            j.extend(jj)
    rows = []
    for x in j:
        mi = cid2i.get(x.get("conditionId"), -1)
        rows.append((int(x["timestamp"]), mi, int(x.get("outcomeIndex", -1)), 1 if x.get("side") == "BUY" else -1,
                     float(x["price"]), float(x["size"]), zlib.crc32((x.get("proxyWallet") or "").encode())))
    df = pd.DataFrame(rows, columns=["ts", "mi", "oi", "side", "price", "size", "w"])
    bars = to_bars(df)
    bars.to_parquet(fp, compression="zstd")
    if trunc:
        with open(os.path.join(OUTDIR, "_truncated.txt"), "a") as f:
            f.write(f"{event_id}\n")
    return event_id, len(df), trunc


def main(kinds=("highest", "lowest"), since="2025-01-01", workers=4, limit=None):
    E = pd.read_parquet("/home/user/polyall2/data/weather/events.parquet")
    M = pd.read_parquet("/home/user/polyall2/data/weather/markets.parquet")
    E = E[E.kind.isin(kinds) & E.closed].copy()
    E["end"] = pd.to_datetime(E.endDate, utc=True, format="mixed")
    E = E[E.end >= since].sort_values("end", ascending=False)
    if limit:
        E = E.head(limit)
    groups = {k: g for k, g in M.groupby("event_id")}
    todo = [eid for eid in E.event_id if not os.path.exists(os.path.join(OUTDIR, f"{eid}.parquet"))]
    print("todo", len(todo), flush=True)
    t0 = time.time(); n = 0; fails = 0
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(fetch_event, eid, groups[eid]) for eid in todo if eid in groups]
        for f in as_completed(futs):
            eid, cnt, tr = f.result()
            n += 1
            if cnt is None:
                fails += 1
            if n % 200 == 0:
                print(n, "done", fails, "fails", round(time.time() - t0), "s", flush=True)
    print("finished", n, fails, flush=True)


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit=lim)
