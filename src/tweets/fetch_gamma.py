"""Enumerate tweet-count events on Gamma (tag tweets-markets), closed and open.
Saves raw events JSONL (markets trimmed to useful fields) to data/tweets/gamma/."""
import json, time, sys, requests

OUT = "/home/user/polyall2/data/tweets/gamma"
S = requests.Session()
MKT_KEYS = ["id", "question", "conditionId", "slug", "groupItemTitle", "groupItemThreshold", "outcomes",
            "outcomePrices", "clobTokenIds", "closedTime", "umaResolutionStatus", "volume", "volumeNum",
            "startDate", "endDate", "createdAt", "acceptingOrdersTimestamp", "feeSchedule", "feeType",
            "feesEnabled", "negRisk", "negRiskOther", "closed", "active", "orderPriceMinTickSize",
            "orderMinSize", "bestBid", "bestAsk", "lastTradePrice", "resolvedBy", "umaEndDate",
            "description", "eventStartTime", "gameStartTime"]
EV_KEYS = ["id", "slug", "title", "description", "resolutionSource", "startDate", "creationDate", "endDate",
           "closed", "active", "negRisk", "volume", "createdAt", "closedTime", "seriesSlug", "series"]

def run(closed):
    fn = f"{OUT}/events_{'closed' if closed else 'open'}.jsonl"
    cur = None; n = 0
    with open(fn, "w") as f:
        while True:
            p = dict(tag_slug="tweets-markets", closed=str(closed).lower(), limit=100)
            if cur: p["after_cursor"] = cur
            for i in range(6):
                try:
                    r = S.get("https://gamma-api.polymarket.com/events/keyset", params=p, timeout=120)
                    r.raise_for_status(); j = r.json(); break
                except Exception as e:
                    print("retry", e); time.sleep(3 + 5 * i)
            evs = j.get("events", [])
            for e in evs:
                d = {k: e.get(k) for k in EV_KEYS}
                d["tags"] = [t.get("slug") for t in e.get("tags", []) or []]
                d["markets"] = [{k: m.get(k) for k in MKT_KEYS} for m in e.get("markets", []) or []]
                for m in d["markets"]:
                    if d["markets"].index(m) > 0: m["description"] = None  # identical rules; keep one
                f.write(json.dumps(d) + "\n")
            n += len(evs)
            cur = j.get("next_cursor")
            print(closed, n, cur is not None, flush=True)
            if not cur or not evs: break
    return n

if __name__ == "__main__":
    for c in ([True, False] if len(sys.argv) < 2 else [sys.argv[1] == "closed"]):
        run(c)
