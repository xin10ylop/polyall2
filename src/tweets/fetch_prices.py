"""Fetch CLOB prices-history (midpoint) at 10-min fidelity for the YES token of every bucket in the universe,
from max(bucket created, window start - 3d) to min(closedTime, window end)+2h. One parquet per event:
 t int32, k int8, p float32."""
import os, sys, time, random, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np, pandas as pd, requests
sys.path.insert(0, os.path.dirname(__file__))
from common import D
from fetch_trades import universe

OUT = f"{D}/prices"; os.makedirs(OUT, exist_ok=True)
FID = 10
_l = threading.local()
def sess():
    if not hasattr(_l, "s"): _l.s = requests.Session()
    return _l.s

def get(params):
    delay = 2
    for i in range(10):
        try:
            r = sess().get("https://clob.polymarket.com/prices-history", params=params, timeout=60)
            if r.status_code == 200: return r.json().get("history", [])
            if r.status_code in (429, 500, 502, 503, 504): time.sleep(delay + random.random()); delay = min(delay * 2, 60); continue
            return []
        except requests.RequestException:
            time.sleep(delay + random.random()); delay = min(delay * 2, 60)
    return None

def do_event(e, b):
    fp = f"{OUT}/{e.event_id}.parquet"
    if os.path.exists(fp): return e.event_id, -1
    parts = []
    ws = int(e.start.timestamp()); we = int(e.end.timestamp())
    for _, r in b.iterrows():
        s = ws - 3 * 86400
        if pd.notna(r.created): s = max(s, int(r.created.timestamp()))
        en = we + 7200
        if pd.notna(r.closedTime): en = min(en, int(r.closedTime.timestamp()) + 7200)
        en = max(en, s + 3600)
        T, P = [], []
        a = s
        while a < en:
            z = min(en, a + 14 * 86400)
            h = get(dict(market=r.yes_tok, startTs=a, endTs=z, fidelity=FID))
            if h is None: return e.event_id, None
            for x in h: T.append(x["t"]); P.append(x["p"])
            a = z
        if T:
            parts.append(pd.DataFrame(dict(t=np.array(T, "int32"), k=np.int8(r.k), p=np.array(P, "float32"))))
    out = pd.concat(parts).drop_duplicates(["t", "k"]) if parts else pd.DataFrame(dict(t=[], k=[], p=[]))
    out.to_parquet(fp + ".tmp", index=False, compression="zstd"); os.replace(fp + ".tmp", fp)
    return e.event_id, len(out)

if __name__ == "__main__":
    E, B = universe()
    th = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    done = 0
    with ThreadPoolExecutor(th) as ex:
        futs = [ex.submit(do_event, e, B[B.event_id == e.event_id]) for _, e in E.iterrows()]
        for f in as_completed(futs):
            eid, n = f.result(); done += 1
            if n is None: print("FAIL", eid, flush=True)
            if done % 25 == 0: print(time.strftime("%H:%M:%S"), done, len(E), flush=True)
    print("done")
