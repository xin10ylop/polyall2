"""Discover closed (and open) Polymarket events for data-lead families via gamma public-search.
Writes data/datalead/events_<family>.json  (list of full event objects incl. markets)
Usage: python discover.py spotify|boxoffice|aimodel|...
"""
import json, os, re, sys, time
import requests

OUT = os.path.join(os.path.dirname(__file__), "../../data/datalead")
S = requests.Session()

FAM = {
    "spotify": dict(queries=["spotify song this week", "#1 song on spotify this week", "#1 song on US spotify",
                             "#2 spotify song this week", "#1 spotify song in the US", "song on spotify this week",
                             "#2 song this week", "#1 song this week"],
                    pat=r"^[12]-(spotify-)?song-(on-(us-)?spotify-)?(in-the-us-)?this-week|^[12]-spotify-song|^[12]-song-this-week|^[12]-song-on-(us-)?spotify|^1-spotify-song-in-the-us"),
    "boxoffice": dict(queries=["opening weekend box office", "2nd weekend box office", "weekend box office",
                               "3rd weekend box office", "box office"],
                      pat=r"weekend-box-office"),
    "billboard": dict(queries=["Billboard 200 #1 Album Week of", "Billboard Hot 100 #1 Song Week of", "billboard #1 song week of",
                               "billboard 200 number 1", "hot 100 #1", "#1 album week of", "#1 song week of"],
                      pat=r"billboard"),
    "aimodel": dict(queries=["best ai model on", "best ai model end of", "which company has best ai model",
                             "top ai model"], pat=r"best-ai-model|ai-model"),
}


def get(url, params, tries=6):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1.5 * 2 ** i)
    return None


def search(q, status):
    slugs = []
    page = 1
    while True:
        d = get("https://gamma-api.polymarket.com/public-search",
                {"q": q, "events_status": status, "limit_per_type": 50, "page": page})
        if not d:
            break
        evs = d.get("events") or []
        slugs += [e["slug"] for e in evs]
        if not (d.get("pagination") or {}).get("hasMore") or not evs or page > 40:
            break
        page += 1
    return slugs


def main(fam):
    cfg = FAM[fam]
    fn = os.path.join(OUT, f"events_{fam}.json")
    old = {e["slug"]: e for e in json.load(open(fn))} if os.path.exists(fn) else {}
    slugs = set()
    for q in cfg["queries"]:
        for st in ["closed", "active"]:
            s = search(q, st)
            slugs |= {x for x in s if re.search(cfg["pat"], x)}
            print(q, st, len(s), len(slugs), flush=True)
    evs = []
    for s in sorted(slugs):
        if s in old and old[s].get("closed"):
            evs.append(old[s]); continue
        d = get("https://gamma-api.polymarket.com/events", {"slug": s})
        if d:
            evs.append(d[0])
    json.dump(evs, open(fn, "w"))
    print("saved", len(evs))


if __name__ == "__main__":
    main(sys.argv[1])
