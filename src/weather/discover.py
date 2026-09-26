"""Discover all Polymarket weather events (open + closed) via gamma-api keyset pagination."""
import json, os, sys, re, collections
sys.path.insert(0, os.path.dirname(__file__))
from nethelp import get_json

OUT = "/home/user/polyall2/data/weather/events_all.json"


def keyset_all(params, ns="gamma_keyset", ttl=3600 * 6):
    out = []
    cursor = None
    while True:
        p = dict(params)
        p["limit"] = 100
        if cursor:
            p["after_cursor"] = cursor
        d = get_json("https://gamma-api.polymarket.com/events/keyset", p, ns=ns, ttl=ttl)
        if "events" not in d:
            print("ERR", d)
            break
        out.extend(d["events"])
        cursor = d.get("next_cursor")
        if not cursor or not d["events"] or len(out) > 200000:
            break
    return out


if __name__ == "__main__":
    allev = {}
    for closed in ["false", "true"]:
        evs = keyset_all({"tag_slug": "weather", "closed": closed})
        print("weather closed=", closed, len(evs))
        for e in evs:
            allev[e["id"]] = e
    json.dump(list(allev.values()), open(OUT, "w"))
    print("total", len(allev))
