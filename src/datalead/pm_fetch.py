"""Polymarket price history (YES token, clob prices-history, fidelity 10 min, <=14-day windows) and taker trade
prints (data-api /trades?market=, takerOnly default=true, offset cap 10000) for a list of markets.
Cache: data/datalead/pm/ph/<cid>.json  {"t":[..],"p":[..]}
       data/datalead/pm/tr/<cid>.csv   ts,side,oi,price,size
"""
import os, json, time, csv
from concurrent.futures import ThreadPoolExecutor
import requests

D = os.path.join(os.path.dirname(__file__), "../../data/datalead/pm")
S = requests.Session()


def _get(url, params, tries=6):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=40)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except Exception:
            pass
        time.sleep(1.5 * 2 ** i)
    return "FAIL"


def price_history(cid, tok, t0, t1, fid=10):
    fn = os.path.join(D, "ph", f"{cid}.json")
    if os.path.exists(fn):
        return json.load(open(fn))
    T, P = [], []
    s = int(t0)
    while s < t1:
        e = int(min(t1, s + 14 * 86400))
        d = _get("https://clob.polymarket.com/prices-history", {"market": tok, "startTs": s, "endTs": e, "fidelity": fid})
        if d == "FAIL":
            return None
        for h in (d or {}).get("history", []):
            T.append(h["t"]); P.append(h["p"])
        s = e
    out = {"t": T, "p": P}
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    json.dump(out, open(fn, "w"))
    return out


def trades(cid):
    fn = os.path.join(D, "tr", f"{cid}.csv")
    if os.path.exists(fn):
        with open(fn) as f:
            r = csv.reader(f); next(r)
            return [(int(a), b, int(c), float(d), float(e)) for a, b, c, d, e in r]
    rows, off = [], 0
    while off <= 10000:
        d = _get("https://data-api.polymarket.com/trades", {"market": cid, "limit": 1000 if off < 10000 else 500, "offset": off})
        if d == "FAIL":
            return None
        if not d:
            break
        rows += [(int(t["timestamp"]), t["side"][0], int(t.get("outcomeIndex") or 0), float(t["price"]), float(t["size"])) for t in d]
        if len(d) < 1000:
            break
        off += 1000
    rows.sort()
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    with open(fn + ".tmp", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["ts", "side", "oi", "price", "size"]); w.writerows(rows)
    os.replace(fn + ".tmp", fn)
    return rows


def fetch_all(items, threads=6):
    """items: list of (cid, yes_token, t0, t1)"""
    def one(it):
        cid, tok, t0, t1 = it
        try:
            a = price_history(cid, tok, t0, t1)
            b = trades(cid)
            return cid, len(a["t"]) if a else -1, len(b) if b is not None else -1
        except Exception as e:
            return cid, repr(e), None
    n = 0
    with ThreadPoolExecutor(threads) as ex:
        for r in ex.map(one, items):
            n += 1
            if n % 100 == 0:
                print(time.strftime("%H:%M:%S"), n, len(items), flush=True)
