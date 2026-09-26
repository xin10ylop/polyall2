"""Build the Spotify weekly #1/#2 panel.
1. parse events_spotify.json -> markets (song name, token ids, winner)
2. map song names to kworb track ids, fetch kworb daily Global/US series for listed songs + all tracks with
   daily peak <= 2 (to catch unlisted 'Other' leaders)
Output: data/datalead/spotify_markets.json
"""
import json, os, re, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
import kworb

D = os.path.join(os.path.dirname(__file__), "../../data/datalead")


def parse_events():
    evs = json.load(open(os.path.join(D, "events_spotify.json")))
    out = []
    for e in evs:
        d = e["description"]
        scope = "us" if re.search(r"in the U\.?S|USA", d) else "global"
        rank = 2 if e["slug"].startswith("2-") else 1
        # chart week label = Friday of publication; week = label-7 (Fri) .. label-1 (Thu)
        m = re.search(r"week labeled (\w+ \d+)", d)
        mk = []
        for x in e["markets"]:
            name = (x.get("groupItemTitle") or "").strip()
            if re.match(r"^Song [A-Z0-9]+$", name) or not x.get("clobTokenIds"):
                continue
            op = json.loads(x.get("outcomePrices") or "[]")
            toks = json.loads(x["clobTokenIds"])
            mk.append(dict(name=name, conditionId=x["conditionId"], yes=toks[0], no=toks[1],
                           won=(op[0] == "1") if op and x.get("closed") and op[0] in ("0", "1") else None,
                           closed=x.get("closed"), fee=(x.get("feeSchedule") or {}).get("rate", 0.0) if x.get("feeSchedule") else 0.0,
                           volume=x.get("volumeNum") or 0, created=x.get("createdAt"), start=x.get("startDate"),
                           closedTime=x.get("closedTime"), endDate=x.get("endDate")))
        out.append(dict(slug=e["slug"], scope=scope, rank=rank, label=m.group(1) if m else None,
                        start=e.get("startDate"), end=e.get("endDate"), closedTime=e.get("closedTime"),
                        closed=e.get("closed"), volume=e.get("volume"), markets=mk))
    return out


def split_name(name):
    parts = name.split(" - ")
    cands = []
    if len(parts) == 1 and " by " in name:
        t, a = name.rsplit(" by ", 1)
        return [(t, a)]
    for k in range(1, len(parts)):
        cands.append((" - ".join(parts[:k]), " - ".join(parts[k:])))
    return cands


ALIAS = {"LA CANCIÓN - Bad Bunny": ["0fea68AdmYNygeTGI4RC18"]}


def match(name, idx):
    if name in ALIAS:
        return ALIAS[name]
    for title, artists in split_name(name):
        nt = kworb.norm(title)
        arts = [kworb.norm(a) for a in re.split(r",|&| and | x ", artists) if a.strip()]
        hits = [r for r in idx.get(nt, []) if any(a and (a == kworb.norm(r["artist"]) or a in kworb.norm(r["artist"])
                                                         or kworb.norm(r["artist"]) in a) for a in arts)]
        if not hits:  # tolerate artist typos (e.g. 'Malcom Todd')
            import difflib
            hits = [r for r in idx.get(nt, []) if any(difflib.SequenceMatcher(None, a, kworb.norm(r["artist"])).ratio() > 0.85
                                                      for a in arts)]
        if hits:
            return sorted({h["id"] for h in hits})
    return []


if __name__ == "__main__":
    evs = parse_events()
    tot = kworb.totals_index()
    idx = collections.defaultdict(list)
    for r in tot:
        idx[kworb.norm(r["title"])].append(r)
    miss = []
    ids = set()
    for e in evs:
        for m in e["markets"]:
            if m["name"].lower() == "other":
                continue
            m["tids"] = match(m["name"], idx)
            if not m["tids"]:
                miss.append(m["name"])
            ids |= set(m["tids"])
    print("listed ids", len(ids), "unmatched", len(set(miss)), sorted(set(miss))[:80])
    top = {r["id"] for r in tot if r["peak"] <= 2}
    print("peak<=2 ids", len(top))
    json.dump(evs, open(os.path.join(D, "spotify_markets.json"), "w"))
    if "--fetch" in sys.argv:
        kworb.fetch_many(sorted(ids) + sorted(top - ids))
