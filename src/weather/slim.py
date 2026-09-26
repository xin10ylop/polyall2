"""Slim the raw gamma events dump to the fields we need (keeps data dir small)."""
import json, re, hashlib, sys

RAW = "/home/user/polyall2/data/weather/events_all.json"
OUT = "/home/user/polyall2/data/weather/events_slim.json"
DESC = "/home/user/polyall2/data/weather/descriptions.json"

EV_KEYS = ["id", "slug", "title", "startDate", "creationDate", "createdAt", "endDate", "closed", "closedTime",
           "volume", "liquidity", "openInterest", "negRisk", "negRiskMarketID", "seriesSlug", "resolutionSource",
           "eventDate", "active", "archived"]
MK_KEYS = ["id", "question", "conditionId", "slug", "groupItemTitle", "groupItemThreshold", "outcomes", "outcomePrices",
           "clobTokenIds", "volumeNum", "volumeClob", "liquidityNum", "bestBid", "bestAsk", "spread", "lastTradePrice",
           "feesEnabled", "feeType", "feeSchedule", "makerBaseFee", "takerBaseFee", "umaResolutionStatus", "closedTime",
           "resolutionSource", "startDate", "endDate", "createdAt", "acceptingOrdersTimestamp", "orderPriceMinTickSize",
           "orderMinSize", "closed", "active", "negRiskOther", "rewardsMinSize", "rewardsMaxSpread", "holdingRewardsEnabled"]


def main():
    d = json.load(open(RAW))
    descs = {}
    out = []
    for e in d:
        s = {k: e.get(k) for k in EV_KEYS}
        desc = e.get("description") or ""
        h = hashlib.sha1(desc.encode()).hexdigest()[:16]
        descs[h] = desc
        s["desc_hash"] = h
        s["tags"] = [t.get("slug") for t in (e.get("tags") or [])]
        s["markets"] = []
        for m in e.get("markets") or []:
            mm = {k: m.get(k) for k in MK_KEYS}
            md = m.get("description") or ""
            mh = hashlib.sha1(md.encode()).hexdigest()[:16]
            if mh not in descs:
                descs[mh] = md
            mm["desc_hash"] = mh
            s["markets"].append(mm)
        out.append(s)
    json.dump(out, open(OUT, "w"))
    json.dump(descs, open(DESC, "w"))
    print(len(out), len(descs))


if __name__ == "__main__":
    main()
