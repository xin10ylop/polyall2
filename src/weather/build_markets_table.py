"""Flatten slim events into a per-market table (parquet) + per-event table for temperature markets."""
import json, re
import pandas as pd

SLIM = "/home/user/polyall2/data/weather/events_slim.json"
OUTM = "/home/user/polyall2/data/weather/markets.parquet"
OUTE = "/home/user/polyall2/data/weather/events.parquet"


def parse_bucket(title):
    """Parse groupItemTitle like '68-69°F', '57°F or below', '76°F or higher', '21°C', '-2°C or below'.
    Returns (lo, hi, unit) inclusive integer bounds; None for open ends."""
    if not title:
        return None, None, None
    t = title.replace("º", "°").replace(" ", " ").strip()
    unit = "F" if "F" in t else ("C" if "C" in t else None)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", t.replace("–", "-"))]
    tl = t.lower()
    if "or below" in tl or "or lower" in tl or "or less" in tl:
        return None, nums[0], unit
    if "or higher" in tl or "or above" in tl or "or more" in tl:
        return nums[0], None, unit
    m = re.match(r"^\s*(-?\d+)\s*-\s*(-?\d+)", t)
    if m:
        return float(m.group(1)), float(m.group(2)), unit
    if len(nums) == 1:
        return nums[0], nums[0], unit
    return None, None, unit


def main():
    d = json.load(open(SLIM))
    rows = []
    evrows = []
    for e in d:
        mt = re.match(r"^(?:arch-)?(highest|lowest)-temperature-in-(.+?)-on-(.+)$", e["slug"])
        kind = mt.group(1) if mt else "other"
        city = mt.group(2) if mt else None
        evrows.append(dict(event_id=e["id"], slug=e["slug"], title=e["title"], kind=kind, city=city,
                           startDate=e["startDate"], creationDate=e["creationDate"], endDate=e["endDate"],
                           closed=e["closed"], closedTime=e["closedTime"], volume=e["volume"],
                           liquidity=e["liquidity"], negRisk=e["negRisk"], desc_hash=e["desc_hash"],
                           resolutionSource=e["resolutionSource"], n_markets=len(e["markets"]),
                           tags=",".join(t for t in e["tags"] if t)))
        for m in e["markets"]:
            lo, hi, unit = parse_bucket(m.get("groupItemTitle"))
            toks = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else [None, None]
            op = json.loads(m["outcomePrices"]) if m.get("outcomePrices") else [None, None]
            fs = m.get("feeSchedule") or {}
            rows.append(dict(event_id=e["id"], event_slug=e["slug"], kind=kind, city=city,
                             market_id=m["id"], question=m["question"], conditionId=m["conditionId"],
                             bucket=m.get("groupItemTitle"), lo=lo, hi=hi, unit=unit,
                             yes_token=toks[0], no_token=toks[1] if len(toks) > 1 else None,
                             yes_final=float(op[0]) if op and op[0] is not None else None,
                             volume=m.get("volumeNum"), liquidity=m.get("liquidityNum"),
                             bestBid=m.get("bestBid"), bestAsk=m.get("bestAsk"), spread=m.get("spread"),
                             lastTradePrice=m.get("lastTradePrice"), feesEnabled=m.get("feesEnabled"),
                             feeType=m.get("feeType"), fee_rate=fs.get("rate"), fee_exp=fs.get("exponent"),
                             fee_takerOnly=fs.get("takerOnly"), fee_rebate=fs.get("rebateRate"),
                             takerBaseFee=m.get("takerBaseFee"), makerBaseFee=m.get("makerBaseFee"),
                             uma=m.get("umaResolutionStatus"), m_closedTime=m.get("closedTime"),
                             resolutionSource=m.get("resolutionSource"), m_startDate=m.get("startDate"),
                             m_endDate=m.get("endDate"), m_createdAt=m.get("createdAt"),
                             acceptingOrdersTimestamp=m.get("acceptingOrdersTimestamp"),
                             tick=m.get("orderPriceMinTickSize"), minSize=m.get("orderMinSize"),
                             closed=m.get("closed"), desc_hash=m.get("desc_hash"),
                             rewardsMinSize=m.get("rewardsMinSize"), rewardsMaxSpread=m.get("rewardsMaxSpread")))
    M = pd.DataFrame(rows)
    E = pd.DataFrame(evrows)
    M.to_parquet(OUTM)
    E.to_parquet(OUTE)
    print(M.shape, E.shape)


if __name__ == "__main__":
    main()
