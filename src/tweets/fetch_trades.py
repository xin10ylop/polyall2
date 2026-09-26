"""Fetch all taker trades (data-api v2, cursor pagination, no offset cap) for every bucket of the
tweet-count events in the research universe. One compact parquet per event:
 ts int64, k int8 (bucket index), oi int8 (0 YES token, 1 NO token), side int8 (+1 taker BUY, -1 taker SELL),
 price float32, size float32 (shares), w uint32 (hash of taker wallet)."""
import os, sys, time, zlib, random, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np, pandas as pd, requests
sys.path.insert(0, os.path.dirname(__file__))
from common import D, events

OUT = f"{D}/trades"; os.makedirs(OUT, exist_ok=True)
_l = threading.local()
def sess():
    if not hasattr(_l, "s"): _l.s = requests.Session()
    return _l.s

def get(params):
    delay = 2
    for i in range(10):
        try:
            r = sess().get("https://data-api.polymarket.com/v2/trades", params=params, timeout=60)
            if r.status_code == 200: return r.json()
            if r.status_code in (429, 500, 502, 503, 504): time.sleep(delay + random.random()); delay = min(delay * 2, 60); continue
            print("HTTP", r.status_code, r.text[:200], flush=True); return None
        except requests.RequestException:
            time.sleep(delay + random.random()); delay = min(delay * 2, 60)
    return None

def fetch_cid(cid):
    rows = []; cur = None
    while True:
        p = dict(condition=cid, limit=1000)
        if cur: p["cursor"] = cur
        j = get(p)
        if j is None: return None
        rows += j["data"]
        pg = j.get("pagination", {})
        if not pg.get("has_more") or not pg.get("next_cursor"): break
        cur = pg["next_cursor"]
    return rows

def universe():
    E, B = events()
    E = E[E.closed & E.resolved & ~E.slug.str.startswith("arch-") & E.start.notna()]
    E = E[E.start >= pd.Timestamp("2025-11-10", tz="UTC")]
    return E, B

def do_event(eid, b):
    fp = f"{OUT}/{eid}.parquet"
    if os.path.exists(fp): return eid, -1
    parts = []
    for _, r in b.iterrows():
        rows = fetch_cid(r.conditionId)
        if rows is None: return eid, None
        if not rows: continue
        df = pd.DataFrame(rows)
        parts.append(pd.DataFrame(dict(
            ts=df.timestamp.astype("int64"), k=np.int8(r.k),
            oi=(df.token_id.astype(str) != str(r.yes_tok)).astype("int8"),
            side=np.where(df.side == "BUY", 1, -1).astype("int8"),
            price=df.price.astype("float32"), size=df["size"].astype("float32"),
            w=df.proxy_wallet.map(lambda x: zlib.crc32(str(x).encode())).astype("uint32"))))
    out = pd.concat(parts) if parts else pd.DataFrame(columns=["ts", "k", "oi", "side", "price", "size", "w"])
    out.sort_values("ts").to_parquet(fp + ".tmp", index=False); os.replace(fp + ".tmp", fp)
    return eid, len(out)

if __name__ == "__main__":
    E, B = universe()
    th = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    print("events", len(E), flush=True)
    done = 0; tot = 0
    with ThreadPoolExecutor(th) as ex:
        futs = [ex.submit(do_event, e, B[B.event_id == e]) for e in E.event_id]
        for f in as_completed(futs):
            eid, n = f.result(); done += 1; tot += max(n or 0, 0)
            if n is None: print("FAIL", eid, flush=True)
            if done % 20 == 0: print(time.strftime("%H:%M:%S"), done, len(E), tot, flush=True)
    print("done", done, tot)
