"""Billboard 200 #1 / Hot 100 #1 (#2) weekly markets: parse events -> billboard_markets.json.
NOTE: billboard.com robots.txt disallows the anthropic-ai user agent, so no Billboard articles are fetched;
announcement times are taken from Billboard's fixed publishing schedule (B200 top-10 story Sunday, Hot 100
top-10 story Monday, full charts Tuesday) with conservative (late) assumed times."""
import json, os, re
D = os.path.join(os.path.dirname(__file__), "../../data/datalead")


def parse():
    evs = json.load(open(os.path.join(D, "events_billboard.json")))
    out = []
    for e in evs:
        s = e["slug"]
        if re.match(r"billboard-200-1-album-week-of", s):
            kind = "B200"
        elif re.match(r"billboard-(hot-100-)?1-song-week-of", s):
            kind = "H100_1"
        elif re.match(r"billboard-hot-100-2-song-week-of", s):
            kind = "H100_2"
        else:
            continue
        mk = []
        for x in e["markets"]:
            if not x.get("clobTokenIds"):
                continue
            op = json.loads(x.get("outcomePrices") or "[]")
            toks = json.loads(x["clobTokenIds"])
            mk.append(dict(name=x.get("groupItemTitle"), q=x["question"], conditionId=x["conditionId"], yes=toks[0], no=toks[1],
                           won=(op[0] == "1") if (x.get("closed") and op and op[0] in ("0", "1")) else None,
                           closed=x.get("closed"), fee=((x.get("feeSchedule") or {}).get("rate") or 0.0),
                           volume=x.get("volumeNum") or 0, created=x.get("createdAt"), closedTime=x.get("closedTime")))
        m = re.search(r'dated \W*Week of (\w+ \d+, \d{4})|titled \W*Week of (\w+ \d+, \d{4})', e.get("description", ""))
        out.append(dict(slug=s, kind=kind, chart_date=(m.group(1) or m.group(2)) if m else None, start=e.get("startDate"),
                        end=e.get("endDate"), closedTime=e.get("closedTime"), closed=e.get("closed"), volume=e.get("volume"),
                        markets=mk))
    json.dump(out, open(os.path.join(D, "billboard_markets.json"), "w"))
    return out


if __name__ == "__main__":
    o = parse()
    import collections
    print(len(o), collections.Counter(x["kind"] for x in o), sum(1 for x in o if not x["chart_date"]))
