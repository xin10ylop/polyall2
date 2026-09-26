"""Fetch PM price history + taker trades for a family's markets.
Usage: python fetch_pm_family.py spotify|boxoffice [days_before_anchor]"""
import json, sys, os, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
import pm_fetch
D = os.path.join(os.path.dirname(__file__), "../../data/datalead")


def ts(s):
    s = (s or "").replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


fam = sys.argv[1]
now = dt.datetime.now(dt.timezone.utc).timestamp()
items = []
evs = json.load(open(os.path.join(D, f"{fam}_markets.json")))
for e in evs:
    for m in e["markets"]:
        if not m.get("volume"):
            continue
        t0 = ts(m.get("created") or e["start"]) - 3600
        if fam == "boxoffice":
            if not e.get("friday"):
                continue
            fri = dt.datetime.fromisoformat(e["friday"]).replace(tzinfo=dt.timezone.utc).timestamp()
            t0 = max(t0, fri - 4 * 86400)
        ct = m.get("closedTime") or e.get("closedTime")
        t1 = ts(ct) + 3600 if ct else now
        items.append((m["conditionId"], m["yes"], t0, t1))
print(len(items))
pm_fetch.fetch_all(items, 6)
