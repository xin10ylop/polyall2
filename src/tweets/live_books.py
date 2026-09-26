"""Snapshot live CLOB order books for every bucket of open tweet-count events.
Saves data/tweets/books/books_<ts>.parquet with per-bucket best bid/ask, depth within 1c/2c/5c of best, and
the raw top-10 levels (json). Usage: python live_books.py"""
import json, time, datetime as dt, os, sys
import numpy as np, pandas as pd, requests
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from common import D
from build_events import SERIES_ACCT, parse_bucket

S = requests.Session()
def book(tok):
    for i in range(5):
        try:
            r = S.get("https://clob.polymarket.com/book", params=dict(token_id=tok), timeout=30)
            if r.status_code == 200: return r.json()
            if r.status_code == 404: return None
        except Exception: pass
        time.sleep(1 + i)
    return None

def depth(levels, best, side, width):
    if best is None: return 0.0
    tot = 0.0
    for l in levels:
        p = float(l["price"]); s = float(l["size"])
        if (side == "ask" and p <= best + width + 1e-9) or (side == "bid" and p >= best - width - 1e-9):
            tot += p * s
    return tot

def main():
    evs = [json.loads(l) for l in open(f"{D}/gamma/events_open.jsonl")]
    rows = []; jobs = []
    for e in evs:
        acct = SERIES_ACCT.get(e.get("seriesSlug") or "")
        if not acct: continue
        for m in e["markets"]:
            pb = parse_bucket(m.get("groupItemTitle"))
            if pb is None or m.get("closed"): continue
            toks = json.loads(m["clobTokenIds"])
            jobs.append((e, acct, pb, m, toks[0]))
    with ThreadPoolExecutor(8) as ex:
        books = list(ex.map(lambda j: book(j[4]), jobs))
    now = dt.datetime.utcnow()
    for (e, acct, pb, m, tok), bk in zip(jobs, books):
        if not bk: continue
        bids = sorted(bk.get("bids", []), key=lambda l: -float(l["price"]))
        asks = sorted(bk.get("asks", []), key=lambda l: float(l["price"]))
        bb = float(bids[0]["price"]) if bids else None; ba = float(asks[0]["price"]) if asks else None
        rows.append(dict(ts=now, acct=acct, event=e["title"], slug=e["slug"], end=e.get("endDate"), label=m["groupItemTitle"],
                         lo=pb[0], hi=pb[1], yes_tok=tok, best_bid=bb, best_ask=ba,
                         spread=(ba - bb) if (bb is not None and ba is not None) else None,
                         ask_usd_1c=depth(asks, ba, "ask", 0.01), ask_usd_2c=depth(asks, ba, "ask", 0.02),
                         ask_usd_5c=depth(asks, ba, "ask", 0.05), bid_usd_1c=depth(bids, bb, "bid", 0.01),
                         bid_usd_2c=depth(bids, bb, "bid", 0.02), bid_usd_5c=depth(bids, bb, "bid", 0.05),
                         tick=bk.get("tick_size"), min_size=bk.get("min_order_size"),
                         asks_top=json.dumps(asks[:10]), bids_top=json.dumps(bids[:10]),
                         fee_rate=(m.get("feeSchedule") or {}).get("rate")))
    df = pd.DataFrame(rows)
    os.makedirs(f"{D}/books", exist_ok=True)
    fn = f"{D}/books/books_{now.strftime('%Y%m%dT%H%M%S')}.parquet"
    df.to_parquet(fn, index=False)
    print(fn, len(df))
    return df

if __name__ == "__main__":
    main()
