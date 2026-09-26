"""Live paper-trader for the weather 'nowcast' strategy (same-day, observation-settled buckets).

Every CYCLE seconds:
 1. open daily temperature events (gamma, tag=weather) ending within [-36h, +60h]
 2. parse station ICAO / unit / kind / target local date / bucket bounds from rules + groupItemTitle
 3. METARs (aviationweather.gov, incl. SPECI) -> running max (highest) / min (lowest) over the station-local
    target day using ONLY reports with receiptTime <= now  (as-of, no look-ahead)
 4. a bucket is DEAD if it can no longer win: highest: hi <= runmax - margin ; lowest: lo >= runmin + margin
 5. books: NO ask = 1 - best YES bid (mirrored book); log every dead bucket with NO ask < 1
 6. paper-buy NO at the displayed ask for up to min(displayed size, CAP_USD) when NO ask <= MAX_PRICE
    (taker fee = 0.05*p*(1-p) per share). Positions settled later by settle_nowcast.py.
Output: data/nowcast/obs_YYYYMMDD.jsonl (opportunity log), data/nowcast/paper_fills.jsonl
"""
import os, re, sys, json, time, math, datetime as dt, traceback
import requests
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder
ROOT = os.path.join(os.path.dirname(__file__), "../..")
OUT = f"{ROOT}/data/nowcast"; os.makedirs(OUT, exist_ok=True)
CYCLE = int(os.environ.get("CYCLE", 120)); MARGIN = int(os.environ.get("MARGIN", 1))
MAX_PRICE = float(os.environ.get("MAX_PRICE", 0.995)); CAP_USD = float(os.environ.get("CAP_USD", 50))
S = requests.Session(); TF = TimezoneFinder()
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                     "october", "november", "december"], 1)}
_station_cache = {}

def get(url, **kw):
    for i in range(4):
        try:
            r = S.get(url, timeout=30, **kw)
            if r.status_code == 200: return r.json()
        except Exception: pass
        time.sleep(1 + 2 * i)
    return None

def post(url, payload):
    for i in range(4):
        try:
            r = S.post(url, json=payload, timeout=30)
            if r.status_code == 200: return r.json()
        except Exception: pass
        time.sleep(1 + 2 * i)
    return None

def parse_bucket(t):
    t = t.replace("≤", "<=").replace("≥", ">=").strip()
    m = re.match(r"^(-?\d+)\s*°?[FC]?\s*or below$", t) or re.match(r"^<=\s*(-?\d+)", t)
    if m: return (-999, int(m.group(1)))
    m = re.match(r"^(-?\d+)\s*°?[FC]?\s*or (higher|above)$", t) or re.match(r"^>=\s*(-?\d+)", t)
    if m: return (int(m.group(1)), 999)
    m = re.match(r"^(-?\d+)\s*-\s*(-?\d+)\s*°?[FC]?$", t)
    if m: return (int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(-?\d+)\s*°?[FC]?$", t)
    if m: return (int(m.group(1)), int(m.group(1)))
    return None

def station_info(icao):
    if icao in _station_cache: return _station_cache[icao]
    d = get("https://aviationweather.gov/api/data/stationinfo", params={"ids": icao, "format": "json"})
    tz = None
    if d:
        x = d[0]; tz = TF.timezone_at(lat=float(x["lat"]), lng=float(x["lon"]))
    _station_cache[icao] = tz
    return tz

def load_events():
    evs, cur = [], None
    while True:
        p = {"closed": "false", "limit": 100, "tag_slug": "weather"}
        if cur: p["after_cursor"] = cur
        d = get("https://gamma-api.polymarket.com/events/keyset", params=p)
        if not d: break
        evs += d.get("events", []); cur = d.get("next_cursor")
        if not cur or not d.get("events"): break
    now = time.time(); out = []
    for e in evs:
        title = e["title"].lower()
        mk = re.search(r"(highest|lowest) temperature in (.+?) on (\w+) (\d+)", title)
        if not mk: continue
        try: end = dt.datetime.fromisoformat(e["endDate"].replace("Z", "+00:00")).timestamp()
        except Exception: continue
        if not (now - 36 * 3600 <= end <= now + 60 * 3600): continue
        desc = e.get("description") or ""
        st = re.search(r"(?:site=|/history/daily/[^\s]*?/)([A-Za-z0-9]{4})\b", desc)
        if not st: continue
        icao = st.group(1).upper()
        unit = "F" if ("Fahrenheit" in desc and "degrees Fahrenheit" in desc) or "°F" in json.dumps([m.get("groupItemTitle") for m in e["markets"]]) else "C"
        yr = dt.datetime.utcfromtimestamp(end).year
        try: day = dt.date(yr, MONTHS[mk.group(3)], int(mk.group(4)))
        except Exception: continue
        buckets = []
        for m in e["markets"]:
            if m.get("closed") or not m.get("acceptingOrders", True): continue
            b = parse_bucket(m.get("groupItemTitle") or "")
            try: toks = json.loads(m["clobTokenIds"])
            except Exception: continue
            if b: buckets.append({"cid": m["conditionId"], "title": m.get("groupItemTitle"), "lo": b[0], "hi": b[1], "yes": toks[0], "no": toks[1],
                                  "fee": ((m.get("feeSchedule") or {}).get("rate", 0.05) if m.get("feesEnabled", True) else 0.0)})
        if buckets:
            out.append({"slug": e["slug"], "kind": mk.group(1), "icao": icao, "unit": unit, "day": day.isoformat(), "end": end, "buckets": buckets})
    return out

def metars(icaos):
    res = {}
    ids = sorted(set(icaos))
    for i in range(0, len(ids), 4):   # API caps responses at 400 records
        d = get("https://aviationweather.gov/api/data/metar", params={"ids": ",".join(ids[i:i + 4]), "format": "json", "hours": 40})
        for x in d or []:
            res.setdefault(x["icaoId"], []).append(x)
    return res

def to_unit(c, unit):
    if c is None: return None
    if unit == "F":
        f = c * 9 / 5 + 32
        return int(math.floor(f + 0.5))
    return int(math.floor(c + 0.5)) if abs(c - round(c)) > 1e-9 else int(round(c))

def extreme_asof(obs, tz, day, unit, kind, now):
    z = ZoneInfo(tz)
    start = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(0, 0), z).timestamp(); stop = start + 86400
    vals = []
    for x in obs:
        try: rec = dt.datetime.fromisoformat(x["receiptTime"].replace("Z", "+00:00")).timestamp()
        except Exception: continue
        if rec > now or not (start <= x["obsTime"] < stop) or x.get("temp") is None: continue
        vals.append((x["obsTime"], to_unit(float(x["temp"]), unit), rec))
    if not vals: return None, None, start, stop
    v = max(vals, key=lambda z: z[1]) if kind == "highest" else min(vals, key=lambda z: z[1])
    return v[1], v[2], start, stop

def main():
    events = []; last_ev = 0; opened = set()
    fills_fn = f"{OUT}/paper_fills.jsonl"
    if os.path.exists(fills_fn):
        for l in open(fills_fn): opened.add(json.loads(l)["cid"])
    while True:
        t0 = time.time()
        try:
            if t0 - last_ev > 1800 or not events:
                events = load_events(); last_ev = t0
            obs = metars([e["icao"] for e in events])
            dead = []
            for e in events:
                tz = station_info(e["icao"])
                if not tz: continue
                ext, rec, start, stop = extreme_asof(obs.get(e["icao"], []), tz, e["day"], e["unit"], e["kind"], t0)
                if ext is None: continue
                for b in e["buckets"]:
                    isdead = (b["hi"] <= ext - MARGIN) if e["kind"] == "highest" else (b["lo"] >= ext + MARGIN)
                    if isdead: dead.append((e, b, ext, rec, start, stop))
            books = {}
            toks = [b["yes"] for _, b, *_ in dead]
            for i in range(0, len(toks), 400):
                for bk in post("https://clob.polymarket.com/books", [{"token_id": x} for x in toks[i:i + 400]]) or []:
                    books[bk["asset_id"]] = bk
            rows = []
            for e, b, ext, rec, start, stop in dead:
                bk = books.get(b["yes"])
                if not bk: continue
                bids = sorted(((float(x["price"]), float(x["size"])) for x in bk.get("bids", [])), key=lambda z: -z[0])
                if not bids: continue
                yb, ysz = bids[0]; no_ask = round(1 - yb, 4)
                depth = [(round(1 - p, 4), s) for p, s in bids[:5]]
                row = {"ts": t0, "slug": e["slug"], "cid": b["cid"], "bucket": b["title"], "kind": e["kind"], "icao": e["icao"], "ext": ext,
                       "settled_at": rec, "local_hour": (t0 - start) / 3600, "no_ask": no_ask, "no_ask_size": ysz, "depth": depth}
                rows.append(row)
                if no_ask <= MAX_PRICE and b["cid"] not in opened:
                    usd = 0.0; sh = 0.0
                    for p, s in depth:
                        if p > MAX_PRICE or usd >= CAP_USD: break
                        take = min(s, (CAP_USD - usd) / p); usd += take * p; sh += take
                    fee = sum(0 for _ in [0])  # computed below per share at avg price
                    avg = usd / sh if sh else None
                    if sh >= 5:
                        feeusd = b["fee"] * sh * avg * (1 - avg)
                        opened.add(b["cid"])
                        with open(fills_fn, "a") as f:
                            f.write(json.dumps({**row, "shares": sh, "avg_px": avg, "usd": usd, "fee_usd": feeusd}) + "\n")
            with open(f"{OUT}/obs_{dt.datetime.utcnow().strftime('%Y%m%d')}.jsonl", "a") as f:
                f.write(json.dumps({"ts": t0, "n_events": len(events), "n_dead": len(dead), "rows": [r for r in rows if r["no_ask"] < 0.999]}) + "\n")
            print(time.strftime("%H:%M:%S"), "events", len(events), "dead", len(dead), "no_ask<0.999:", sum(1 for r in rows if r["no_ask"] < 0.999),
                  "<=MAX:", sum(1 for r in rows if r["no_ask"] <= MAX_PRICE), flush=True)
        except Exception:
            traceback.print_exc()
        time.sleep(max(5, CYCLE - (time.time() - t0)))

if __name__ == "__main__":
    main()
