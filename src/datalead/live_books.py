"""Snapshot current order books (clob /book) for open markets of the data-lead families.
Prints best bid/ask and depth within 3c of the ask for each outcome."""
import json, os, sys, requests, time
D = os.path.join(os.path.dirname(__file__), "../../data/datalead")


def book(tok):
    for i in range(4):
        try:
            r = requests.get("https://clob.polymarket.com/book", params={"token_id": tok}, timeout=20)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def summarize(b):
    asks = sorted([(float(a["price"]), float(a["size"])) for a in b.get("asks", [])])
    bids = sorted([(float(a["price"]), float(a["size"])) for a in b.get("bids", [])], reverse=True)
    ba = asks[0][0] if asks else None
    bb = bids[0][0] if bids else None
    depth = sum(p * s for p, s in asks if ba is not None and p <= ba + 0.03)
    return bb, ba, depth


def slug_events(slugs):
    out = []
    for s in slugs:
        r = requests.get("https://gamma-api.polymarket.com/events", params={"slug": s}, timeout=30).json()
        if r:
            out.append(r[0])
    return out


if __name__ == "__main__":
    fams = {"aimodel": "aimodel_markets.json", "boxoffice": "boxoffice_markets.json", "spotify": "spotify_markets.json",
            "billboard": "billboard_markets.json"}
    snap = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "events": []}
    for fam, fn in fams.items():
        evs = [e for e in json.load(open(os.path.join(D, fn))) if not e.get("closed")]
        for ev in slug_events([e["slug"] for e in evs]):
            if ev.get("closed"):
                continue
            print(f"== [{fam}] {ev['slug']}  end={ev.get('endDate')}")
            rows = []
            for m in ev["markets"]:
                if not m.get("clobTokenIds") or m.get("closed"):
                    continue
                tok = json.loads(m["clobTokenIds"])[0]
                b = book(tok)
                if not b:
                    continue
                bb, ba, dep = summarize(b)
                rows.append(dict(name=m.get("groupItemTitle"), bid=bb, ask=ba, depth3c=round(dep, 1)))
                if ba is not None and ba < 0.995 or (bb or 0) > 0.05:
                    print(f"   {str(m.get('groupItemTitle'))[:45]:45s} bid={bb} ask={ba} $depth(ask..+3c)={dep:.0f}")
            snap["events"].append(dict(fam=fam, slug=ev["slug"], end=ev.get("endDate"), rows=rows))
    json.dump(snap, open(os.path.join(D, "live_books_%s.json" % snap["ts"].replace(":", "")), "w"))
