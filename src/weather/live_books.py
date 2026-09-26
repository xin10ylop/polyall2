"""Snapshot current order books for all open daily temperature markets (CLOB POST /books)."""
import os, sys, json, time
import numpy as np
import pandas as pd
import requests
sys.path.insert(0, os.path.dirname(__file__))
from discover import keyset_all
from common import D, event_date

OUT = f"{D}/live_books"
os.makedirs(OUT, exist_ok=True)


def main():
    now = pd.Timestamp.now(tz="UTC")
    evs = keyset_all({"tag_slug": "weather", "closed": "false"}, ns="gamma_live", ttl=600)
    rows = []
    for e in evs:
        s = e["slug"]
        if "temperature-in-" not in s:
            continue
        for m in e.get("markets", []):
            if not m.get("clobTokenIds") or m.get("closed"):
                continue
            toks = json.loads(m["clobTokenIds"])
            rows.append(dict(event_slug=s, event_id=e["id"], date=str(event_date(s, e.get("endDate"))), bucket=m.get("groupItemTitle"),
                             yes=toks[0], no=toks[1], accepting=m.get("acceptingOrders"), g_bid=m.get("bestBid"), g_ask=m.get("bestAsk"),
                             vol=m.get("volumeNum"), vol24=m.get("volume24hr"), liq=m.get("liquidityNum")))
    T = pd.DataFrame(rows)
    books = {}
    toks = list(T.yes) + list(T.no)
    s = requests.Session()
    for i in range(0, len(toks), 200):
        chunk = toks[i:i + 200]
        for k in range(6):
            r = s.post("https://clob.polymarket.com/books", json=[{"token_id": t} for t in chunk], timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 ** k)
        for b in r.json():
            books[b["asset_id"]] = b
        time.sleep(0.3)
    snap = dict(ts=now.isoformat(), markets=T.to_dict("records"), books=books)
    fn = f"{OUT}/books_{now.strftime('%Y%m%dT%H%M')}.json"
    json.dump(snap, open(fn, "w"))
    print(fn, len(T), len(books))


if __name__ == "__main__":
    main()
