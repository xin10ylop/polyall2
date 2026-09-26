"""Live order-book + trade recorder for rewarded markets in chosen categories (default: weather).
Every ~60s: YES-token books for all rewarded markets (levels within +-0.15 of mid, plus best bid/ask).
Every ~120s: taker trades for those markets (data-api, multi-market query), deduped.
Every 30 min: refresh reward configs (rate_per_day, max_spread, min_size) and market list.
Output: data/live/<tag>/books_YYYYMMDDHH.jsonl.gz, trades_YYYYMMDD.jsonl.gz, configs_YYYYMMDD.jsonl.gz
"""
import os, sys, time, json, gzip, datetime as dt, traceback
import requests
ROOT = os.path.join(os.path.dirname(__file__), "../..")
TAG = sys.argv[1] if len(sys.argv) > 1 else "weather"
OUT = f"{ROOT}/data/live/{TAG}"; os.makedirs(OUT, exist_ok=True)
S = requests.Session()

def now(): return time.time()
def stamp(fmt): return dt.datetime.utcnow().strftime(fmt)

def get_json(method, url, **kw):
    for i in range(4):
        try:
            r = S.request(method, url, timeout=30, **kw)
            if r.status_code == 200: return r.json()
        except Exception: pass
        time.sleep(1 + 2 * i)
    return None

def load_markets_current(min_rate=10.0):
    allm, cur = [], None
    while True:
        p = {"next_cursor": cur} if cur else {}
        d = get_json("GET", "https://clob.polymarket.com/rewards/markets/current", params=p)
        if not d: break
        allm += d.get("data", []); cur = d.get("next_cursor")
        if not cur or cur == "LTE=" or not d.get("data"): break
    rich = [m for m in allm if (m.get("total_daily_rate") or 0) >= min_rate]
    out = {}
    # need token ids + question: fetch from clob-markets compact endpoint in batches via gamma
    cids = [m["condition_id"] for m in rich]
    for i in range(0, len(cids), 50):
        g = get_json("GET", "https://gamma-api.polymarket.com/markets", params=[("condition_ids", c) for c in cids[i:i + 50]] + [("limit", 50)])
        for gm in g or []:
            try: toks = json.loads(gm["clobTokenIds"])
            except Exception: continue
            if (gm.get("feeType") or "").startswith("sports") or not gm.get("acceptingOrders", True) or gm.get("closed"): continue
            rm = next((x for x in rich if x["condition_id"] == gm["conditionId"]), None)
            if not rm: continue
            out[gm["conditionId"]] = {"cid": gm["conditionId"], "yes": toks[0], "no": toks[1], "rate": rm.get("total_daily_rate"),
                                      "v": rm.get("rewards_max_spread"), "min": rm.get("rewards_min_size"), "q": gm.get("question"),
                                      "end": (gm.get("endDate") or "").replace("T", " ").replace("Z", "+00"), "event": None, "feeType": gm.get("feeType")}
    return out

def load_markets():
    if TAG == "all10": return load_markets_current(10.0)
    allm, cur = [], None
    while True:
        p = {"tag_slug": TAG, "limit": 500}
        if cur: p["next_cursor"] = cur
        d = get_json("GET", "https://clob.polymarket.com/rewards/markets/multi", params=p)
        if not d: break
        allm += d.get("data", []); cur = d.get("next_cursor")
        if not cur or cur == "LTE=" or not d.get("data"): break
    out = {}
    for m in allm:
        rc = m.get("rewards_config") or []
        if not rc: continue
        ed = m.get("end_date") or ""
        out[m["condition_id"]] = {"cid": m["condition_id"], "yes": m["tokens"][0]["token_id"], "no": m["tokens"][1]["token_id"],
                                 "rate": sum(x.get("rate_per_day", 0) for x in rc), "v": m.get("rewards_max_spread"),
                                 "min": m.get("rewards_min_size"), "q": m.get("question"), "end": ed, "event": m.get("event_slug")}
    return out

def compact_book(b):
    bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
    asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
    bb = max((p for p, _ in bids), default=None); ba = min((p for p, _ in asks), default=None)
    mid = (bb + ba) / 2 if bb is not None and ba is not None else (bb if ba is None else ba)
    if mid is None: return {"bb": None, "ba": None, "b": [], "a": []}
    keep_b = sorted([x for x in bids if x[0] >= mid - 0.15], key=lambda x: -x[0])
    keep_a = sorted([x for x in asks if x[0] <= mid + 0.15], key=lambda x: x[0])
    return {"bb": bb, "ba": ba, "b": keep_b, "a": keep_a, "ltp": b.get("last_trade_price")}

def main():
    markets = {}; last_cfg = 0; last_tr = 0; seen = set(); seen_day = stamp("%Y%m%d")
    while True:
        t0 = now()
        try:
            if t0 - last_cfg > 1800 or not markets:
                markets = load_markets(); last_cfg = t0
                with gzip.open(f"{OUT}/configs_{stamp('%Y%m%d')}.jsonl.gz", "at") as f:
                    f.write(json.dumps({"ts": t0, "markets": list(markets.values())}) + "\n")
            toks = [m["yes"] for m in markets.values()]; by_tok = {m["yes"]: m["cid"] for m in markets.values()}
            snap = {}
            for i in range(0, len(toks), 400):
                d = get_json("POST", "https://clob.polymarket.com/books", json=[{"token_id": x} for x in toks[i:i + 400]])
                for b in d or []:
                    snap[by_tok.get(b.get("asset_id"), b.get("market"))] = compact_book(b)
            with gzip.open(f"{OUT}/books_{stamp('%Y%m%d%H')}.jsonl.gz", "at") as f:
                f.write(json.dumps({"ts": t0, "books": snap}) + "\n")
            if t0 - last_tr > 120:
                last_tr = t0
                if stamp("%Y%m%d") != seen_day: seen = set(); seen_day = stamp("%Y%m%d")
                cids = list(markets.keys()); rows = []
                for i in range(0, len(cids), 40):
                    d = get_json("GET", "https://data-api.polymarket.com/trades", params={"market": ",".join(cids[i:i + 40]), "limit": 500})
                    for t in d or []:
                        k = (t.get("transactionHash"), t.get("asset"), t.get("size"), t.get("price"))
                        if k in seen: continue
                        seen.add(k)
                        rows.append({"ts": t["timestamp"], "cid": t["conditionId"], "asset": t["asset"], "side": t["side"], "oi": t.get("outcomeIndex"),
                                     "price": t["price"], "size": t["size"], "w": (t.get("proxyWallet") or "")[:12], "tx": (t.get("transactionHash") or "")[:18]})
                if rows:
                    with gzip.open(f"{OUT}/trades_{stamp('%Y%m%d')}.jsonl.gz", "at") as f:
                        for r in rows: f.write(json.dumps(r) + "\n")
        except Exception:
            traceback.print_exc()
        time.sleep(max(1, 60 - (now() - t0)))

if __name__ == "__main__":
    main()
