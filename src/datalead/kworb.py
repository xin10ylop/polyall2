"""kworb.net Spotify data: name->track index (from daily totals pages) and per-track DAILY Global/US
positions+streams (the 'daily' table on kworb track pages).

Look-ahead note: kworb/Spotify publish the daily chart for day D on D+1 (evening UTC) - D+2.  The backtest
assumes day D is usable only from D+2 00:00 UTC (conservative; checked live on 2026-09-26 14:45 UTC when the
latest published daily chart was 2026-09-24).

Cache: data/datalead/kworb/tracks/<id>.csv  (date,scope,pos,streams)
"""
import os, re, time, csv, json, unicodedata
from concurrent.futures import ThreadPoolExecutor
import requests

D = os.path.join(os.path.dirname(__file__), "../../data/datalead/kworb")
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (research; low-rate)"


def get(url, tries=5):
    for i in range(tries):
        try:
            r = S.get(url, timeout=40)
            if r.status_code == 200:
                r.encoding = "utf-8"
                return r.text
            if r.status_code == 404:
                return None
        except Exception:
            pass
        time.sleep(2 * 2 ** i)
    return None


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = s.replace("&amp;", "&").replace("&#39;", "'").replace("’", "'")
    s = re.sub(r"\(feat[^)]*\)|\(with[^)]*\)|feat\..*$", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def totals_index():
    """list of dicts: id, artist, title, scope, days, peak"""
    out = []
    for scope in ["global", "us"]:
        fn = os.path.join(D, f"{scope}_daily_totals.html")
        h = open(fn, encoding="utf-8").read()
        for r in re.findall(r"<tr>(.*?)</tr>", h, flags=re.S)[1:]:
            m = re.search(r'artist/([A-Za-z0-9]+)\.html">(.*?)</a> - <a href="../track/([A-Za-z0-9]+)\.html">(.*?)</a>', r)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.S)
            if not m:
                # tracks with several artists: take all artist names
                m2 = re.search(r'<div>(.*?)</div>', r)
                tid = re.search(r'track/([A-Za-z0-9]+)\.html">(.*?)</a>', r)
                if not (m2 and tid):
                    continue
                arts = re.sub(r"<[^>]+>", "", m2.group(1)).split(" - ")[0]
                out.append(dict(id=tid.group(1), artist=arts, title=tid.group(2), scope=scope,
                                days=int(tds[1]), peak=int(tds[3]) if tds[3].isdigit() else 999))
                continue
            out.append(dict(id=m.group(3), artist=re.sub(r"<[^>]+>", "", m.group(2)), title=m.group(4), scope=scope,
                            days=int(tds[1]), peak=int(tds[3]) if tds[3].isdigit() else 999))
    return out


def parse_track(html):
    rows = []
    i = html.find('<div class="daily">')
    if i >= 0:
        rows += _parse_tab(html[i:html.find("</table>", i)], "")
    j = html.find("<table")
    if 0 <= j < (i if i >= 0 else len(html)):
        rows += _parse_tab(html[j:html.find("</table>", j)], "_w")   # weekly table (weeks ending Thursday)
    return rows


def _parse_tab(tab, suffix):
    hdr = re.findall(r"<th>(.*?)</th>", tab)
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", tab, flags=re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S)
        if not tds or not re.match(r"\d{4}/\d\d/\d\d", tds[0]):
            continue
        date = tds[0].replace("/", "-")
        for col in ("Global", "US"):
            if col not in hdr:
                continue
            c = tds[hdr.index(col)] if hdr.index(col) < len(tds) else ""
            m = re.search(r'class="p">(\d+)</span>.*?class="s">([\d,]+)<', c)
            if m:
                rows.append((date, col.lower() + suffix, int(m.group(1)), int(m.group(2).replace(",", ""))))
    return rows


def fetch_track(tid):
    fn = os.path.join(D, "tracks", f"{tid}.csv")
    if os.path.exists(fn):
        return tid, -1
    h = get(f"https://kworb.net/spotify/track/{tid}.html")
    if h is None:
        return tid, -2
    rows = parse_track(h)
    title = re.search(r"<title>(.*?)</title>", h)
    os.makedirs(os.path.dirname(fn), exist_ok=True)
    with open(fn + ".tmp", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "scope", "pos", "streams", title.group(1) if title else ""])
        w.writerows(rows)
    os.replace(fn + ".tmp", fn)
    time.sleep(0.3)
    return tid, len(rows)


def fetch_many(ids, threads=3):
    n = 0
    with ThreadPoolExecutor(threads) as ex:
        for tid, k in ex.map(fetch_track, ids):
            n += 1
            if n % 50 == 0:
                print(time.strftime("%H:%M:%S"), n, len(ids), flush=True)


def load_track(tid):
    fn = os.path.join(D, "tracks", f"{tid}.csv")
    if not os.path.exists(fn):
        return []
    with open(fn) as f:
        r = csv.reader(f)
        next(r)
        return [(a, b, int(c), int(d)) for a, b, c, d in r]
