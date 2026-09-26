"""Live monitor for Hong Kong temperature markets (resolve on HKO 'Absolute Daily Max/Min', 0.1 C precision).
Every 60 s: HKO since-midnight max/min at 'HK Observatory' (public CSV, ~8 min publication lag) + Polymarket books.
Bucket 'N°C' = [N.0, N.9]; 'N°C or below' = <= N.9; 'N°C or higher' >= N.0.
Dead (highest): bucket hi_edge < running max - MARGIN; (lowest): bucket lo_edge > running min + MARGIN.
Logs every dead bucket's NO ask (1 - YES best bid) with HKO file Last-Modified -> measures how long cheap NO persists
after the public data shows the bucket dead. Output: data/nowcast/hk_log.jsonl"""
import os, re, json, time, datetime as dt, requests
from zoneinfo import ZoneInfo
OUT = os.path.join(os.path.dirname(__file__), "../../data/nowcast"); os.makedirs(OUT, exist_ok=True)
MARGIN = float(os.environ.get("HK_MARGIN", 0.2)); HKT = ZoneInfo("Asia/Hong_Kong")
S = requests.Session()
def hko():
    r = S.get("https://data.weather.gov.hk/weatherAPI/hko_data/regional-weather/latest_since_midnight_maxmin.csv", timeout=20)
    lm = r.headers.get("last-modified")
    for line in r.text.splitlines():
        p = line.split(",")
        if len(p) >= 4 and p[1].strip() == "HK Observatory":
            return p[0], float(p[2]), float(p[3]), lm
    return None
def bucket(t):
    t = t.strip()
    m = re.match(r"^(-?\d+)°C or below$", t)
    if m: return (-99, int(m.group(1)) + 0.99)
    m = re.match(r"^(-?\d+)°C or higher$", t)
    if m: return (int(m.group(1)), 99)
    m = re.match(r"^(-?\d+)°C$", t)
    if m: return (int(m.group(1)), int(m.group(1)) + 0.99)
def events(day):
    out = []
    for kind in ("highest", "lowest"):
        slug = f"{kind}-temperature-in-hong-kong-on-{day.strftime('%B').lower()}-{day.day}-{day.year}"
        e = S.get("https://gamma-api.polymarket.com/events", params={"slug": slug}, timeout=20).json()
        if e: out.append((kind, e[0]))
    return out
last_ev = 0; evs = []
while True:
    t0 = time.time()
    try:
        day = dt.datetime.now(HKT).date()
        if t0 - last_ev > 900 or not evs:
            evs = events(day); last_ev = t0
        h = hko()
        if h:
            stamp, mx, mn, lm = h
            rows = []
            for kind, e in evs:
                for m in e["markets"]:
                    b = bucket(m.get("groupItemTitle") or "")
                    if not b or m.get("closed"): continue
                    dead = (b[1] < mx - MARGIN) if kind == "highest" else (b[0] > mn + MARGIN)
                    if not dead: continue
                    yes = json.loads(m["clobTokenIds"])[0]
                    bk = S.get("https://clob.polymarket.com/book", params={"token_id": yes}, timeout=15).json()
                    bids = sorted(((float(x["price"]), float(x["size"])) for x in bk.get("bids", [])), key=lambda z: -z[0])
                    no_ask = round(1 - bids[0][0], 4) if bids else 1.0
                    rows.append({"kind": kind, "bucket": m["groupItemTitle"], "no_ask": no_ask, "size": bids[0][1] if bids else 0})
            rec = {"ts": t0, "hko_stamp": stamp, "hko_last_modified": lm, "max": mx, "min": mn, "dead": rows}
            with open(f"{OUT}/hk_log.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")
            cheap = [r for r in rows if r["no_ask"] < 0.99]
            print(time.strftime("%H:%M:%S"), stamp, "max", mx, "min", mn, "dead", len(rows), "cheap", cheap, flush=True)
    except Exception as ex:
        print("err", repr(ex)[:200], flush=True)
    time.sleep(max(5, 60 - (time.time() - t0)))
