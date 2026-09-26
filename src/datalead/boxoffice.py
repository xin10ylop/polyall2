"""Weekend box-office bracket markets.
Data: Box Office Mojo weekend *estimates* pages (https://www.boxofficemojo.com/weekend/<YYYY>W<ww>/estimates/)
list the Sunday studio estimate AND the Monday actual for every film -> look-ahead-free signal (estimate, public
Sunday ~9-11am PT) and the resolution proxy (actual; Polymarket resolves on The Numbers finals).
Also BOM release pages give daily grosses (Thu previews / Fri) for the earlier (Saturday) decision.

Cache: data/datalead/bom/est_<YYYY>W<ww>.csv
Output: data/datalead/boxoffice_markets.json
"""
import os, re, json, time, csv, datetime as dt, difflib, unicodedata
import requests

D = os.path.join(os.path.dirname(__file__), "../../data/datalead")
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) research"


def get(url, tries=5):
    for i in range(tries):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 * 2 ** i)
    return None


def money(s):
    s = s.replace("$", "").replace(",", "").strip()
    return float(s) if re.match(r"^-?\d+(\.\d+)?$", s) else None


def bom_week(year, week):
    fn = os.path.join(D, "bom", f"est_{year}W{week:02d}.csv")
    if os.path.exists(fn):
        with open(fn) as f:
            return list(csv.DictReader(f))
    h = get(f"https://www.boxofficemojo.com/weekend/{year}W{week:02d}/estimates/")
    rows = []
    if h:
        t = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
        tab = re.search(r"<table.*?</table>", t, flags=re.S)
        if tab:
            trs = re.findall(r"<tr.*?</tr>", tab.group(0), flags=re.S)
            hdr = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", trs[0], flags=re.S)]
            for r in trs[1:]:
                cells = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, flags=re.S)]
                rel = re.search(r'href="(/release/rl\d+)', r)
                if len(cells) < 12:
                    continue
                rows.append(dict(release=cells[3], est=money(cells[4]), actual=money(cells[5]), theaters=cells[8],
                                 weekend=cells[11], distributor=cells[12] if len(cells) > 12 else "",
                                 rl=rel.group(1) if rel else ""))
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    with open(fn, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["release", "est", "actual", "theaters", "weekend", "distributor", "rl"])
        w.writeheader(); w.writerows(rows)
    time.sleep(0.5)
    return [{k: str(v) for k, v in r.items()} for r in rows]


def parse_bracket(q):
    q = q.replace("–", "-").replace("—", "-")
    q = re.sub(r'"[^"]*"|\'[^\']*\'|“[^”]*”', "", q)          # drop the quoted film name
    q = re.sub(r"\b\d-day\b", "", q)                            # '3-day opening weekend'
    ql = q.lower()
    nums = [float(x) for x in re.findall(r"\$?(\d+(?:\.\d+)?)\s*[mM]?(?=[^a-z0-9]|$)", q)]
    nums = [n for n in nums if n < 2000]
    if (re.search(r"\bbetween\b|but less than", ql) or re.search(r"\d\s*m?\s*-\s*\$?\d", ql)) and len(nums) >= 2:
        return (nums[-2], nums[-1])
    if re.search(r"\bless than\b|\bunder\b|\bbelow\b|<", ql) and nums:
        return (0.0, nums[-1])
    if re.search(r"greater than|more than|at least|or more|\bover\b|\babove\b|\+", ql) and nums:
        return (nums[-1], 1e9)
    if len(nums) >= 2:
        return (nums[-2], nums[-1])
    return None


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_events():
    evs = json.load(open(os.path.join(D, "events_boxoffice.json")))
    out = []
    for e in evs:
        title = e.get("title") or ""
        m = re.search(r'"([^"]+)"', title) or re.search(r"'([^']+)'", title)
        film = m.group(1) if m else re.sub(r"(opening|\d+(st|nd|rd|th)|second|third).*", "", title, flags=re.I).strip()
        wk = 1
        mw = re.search(r"(\d+)(st|nd|rd|th) weekend", title, re.I)
        if mw:
            wk = int(mw.group(1))
        elif re.search(r"second weekend", title, re.I):
            wk = 2
        elif re.search(r"third weekend", title, re.I):
            wk = 3
        mk = []
        for x in e["markets"]:
            if not x.get("clobTokenIds"):
                continue
            b = parse_bracket(x["question"])
            op = json.loads(x.get("outcomePrices") or "[]")
            toks = json.loads(x["clobTokenIds"])
            mk.append(dict(q=x["question"], lo=b[0] if b else None, hi=b[1] if b else None, conditionId=x["conditionId"],
                           yes=toks[0], no=toks[1], won=(op[0] == "1") if (x.get("closed") and op and op[0] in ("0", "1")) else None,
                           closed=x.get("closed"), fee=((x.get("feeSchedule") or {}).get("rate") or 0.0),
                           volume=x.get("volumeNum") or 0, created=x.get("createdAt"), closedTime=x.get("closedTime")))
        out.append(dict(slug=e["slug"], title=title, film=film, wknum=wk, end=e.get("endDate"), start=e.get("startDate"),
                        closedTime=e.get("closedTime"), closed=e.get("closed"), volume=e.get("volume"),
                        description=e.get("description", "")[:1500], markets=mk))
    return out


def weekend_friday(ev):
    """Friday of the resolving weekend: from description '(September 25 - 27)' else endDate's Friday."""
    end = dt.datetime.fromisoformat(ev["end"].replace("Z", "+00:00")) if ev.get("end") else None
    m = re.search(r"\((\w+) (\d+)\s*[-–]\s*(?:(\w+) )?(\d+)\)", ev["description"])
    if m and end:
        try:
            d = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {end.year}", "%B %d %Y").date()
            if (d - end.date()).days > 200:
                d = d.replace(year=d.year - 1)
            return d
        except ValueError:
            pass
    if end is None:
        return None
    d = end.date()
    # endDate is usually Sunday/Monday of the weekend (or a few days later)
    while d.weekday() != 4:
        d -= dt.timedelta(days=1)
    return d


def match_bom(ev, fri):
    y, w, _ = fri.isocalendar()
    rows = bom_week(y, w)
    if not rows:
        return None, (y, w)
    names = [norm(r["release"]) for r in rows]
    f = norm(ev["film"])
    best, bs = None, 0
    for r, n in zip(rows, names):
        s = difflib.SequenceMatcher(None, f, n).ratio()
        if f and (f == n or n.startswith(f) or f.startswith(n)):
            s = max(s, 0.95)
        if s > bs:
            best, bs = r, s
    return (best if bs >= 0.75 else None), (y, w)


if __name__ == "__main__":
    evs = parse_events()
    nm = 0
    for ev in evs:
        fri = weekend_friday(ev)
        ev["friday"] = fri.isoformat() if fri else None
        if not fri or fri > dt.date(2026, 9, 25):
            continue
        r, yw = match_bom(ev, fri)
        ev["bom"] = r; ev["bomweek"] = yw
        if r:
            nm += 1
        else:
            print("no match", ev["slug"], ev["film"], fri, yw)
    json.dump(evs, open(os.path.join(D, "boxoffice_markets.json"), "w"), default=str)
    print("events", len(evs), "matched", nm)
