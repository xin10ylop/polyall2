"""Maker fills (all wallets) in daily-temperature events whose target day D is complete (endDate 2026-09-20..25), so that
observation-day fills are fully sampled. data-api /trades?eventId=..&takerOnly=false minus takerOnly=true.
Output: data/audit/closed_event_maker_fills.json  (wallet, title, ts, size, price)
Usage: python src/audit/closed_event_fills.py"""
import os, json, time, requests, pandas as pd, concurrent.futures as cf
ROOT = os.path.join(os.path.dirname(__file__), "../.."); S = requests.Session()
e = pd.read_parquet(f"{ROOT}/data/weather/events.parquet")
e["end"] = pd.to_datetime(e.endDate, utc=True, errors="coerce")
E = e[(e.end >= "2026-09-20") & (e.end < "2026-09-26") & e.kind.isin(["highest", "lowest"])]
print("events", len(E))
def get(eid, taker):
    out = []; off = 0
    while off <= 10000:
        for i in range(4):
            try:
                r = S.get("https://data-api.polymarket.com/trades", params={"eventId": eid, "limit": 1000, "offset": off, "takerOnly": taker}, timeout=60)
                d = r.json() if r.status_code == 200 else None
                if d is not None: break
            except Exception: pass
            time.sleep(1 + 2 * i)
        else: d = []
        out += d or []
        if not d or len(d) < 1000: break
        off += 1000
    return out
def one(eid):
    a = get(eid, "false"); t = get(eid, "true")
    tk = set((x["transactionHash"], x["proxyWallet"]) for x in t)
    return [(x["proxyWallet"], x.get("title"), x["timestamp"], x["size"], x["price"]) for x in a if (x["transactionHash"], x["proxyWallet"]) not in tk], len(a) >= 11000
with cf.ThreadPoolExecutor(8) as ex: res = list(ex.map(one, E.event_id.astype(str).tolist()))
rows = [r for x, _ in res for r in x]; trunc = sum(1 for _, t in res if t)
json.dump(rows, open(f"{ROOT}/data/audit/closed_event_maker_fills.json", "w"))
print("maker fills", len(rows), "events truncated at 10k offset:", trunc)
