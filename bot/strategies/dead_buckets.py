"""Observation-day 'dead bucket' harvester (weather temperature markets).

A bucket is DEAD when the as-of METAR running extreme has passed it by >= MARGIN whole degrees
(highest: hi <= runmax - MARGIN; lowest: lo >= runmin + MARGIN). Default MARGIN=2 because METAR and the
resolution source (Wunderground / NOAA timeseries) disagree by 1 degree in ~0.2-0.4% of days
(e.g. Shenzhen 2026-07-20: METAR max 30C, Wunderground 29C -> the 29C bucket won).
Action: taker-buy NO (FAK, never rests) while NO ask <= MAX_PRICE and the edge after the taker fee
(rate*p*(1-p)) is >= MIN_EDGE. Every market passes the Jev rules guard (station/unit/metric) first.
Hong Kong (HKO) markets are skipped (non-METAR source).
"""
import os, sys, time, json, logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "nowcast"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import live_nowcast as LN
from execution import Executor, book
from guard import check_weather
log = logging.getLogger("dead")
MARGIN = int(os.environ.get("DB_MARGIN", 2)); MAX_PRICE = float(os.environ.get("DB_MAX_PRICE", 0.99))
MIN_EDGE = float(os.environ.get("DB_MIN_EDGE", 0.005)); CAP_USD = float(os.environ.get("DB_CAP_USD", 25))
CITY_DAY_CAP = float(os.environ.get("DB_CITY_DAY_CAP", 60)); CYCLE = int(os.environ.get("DB_CYCLE", 60))

def _state_file(ex):
    return os.path.join(os.path.dirname(ex.ledger), "dead_spent.json")

def _load_spent(ex):
    try: return json.load(open(_state_file(ex)))
    except Exception: return {}

def _save_spent(ex, spent):
    json.dump(spent, open(_state_file(ex), "w"))

def run():
    ex = Executor(); spent = _load_spent(ex); last_ev = 0; events = []
    while True:
        t0 = time.time()
        if os.path.exists(os.path.join(os.path.dirname(ex.ledger), "KILL")):
            log.warning("KILL file present; stopping"); ex.cancel_all(); return
        try:
            if t0 - last_ev > 1800 or not events:
                events = LN.load_events(); last_ev = t0
            obs = LN.metars([e["icao"] for e in events])
            for e in events:
                tz = LN.station_info(e["icao"])
                if not tz: continue
                ext, rec, start, stop = LN.extreme_asof(obs.get(e["icao"], []), tz, e["day"], e["unit"], e["kind"], t0)
                if ext is None: continue
                ck = f"{e['slug']}"
                for b in e["buckets"]:
                    dead = (b["hi"] <= ext - MARGIN) if e["kind"] == "highest" else (b["lo"] >= ext + MARGIN)
                    if not dead or spent.get(b["cid"], 0) >= CAP_USD or spent.get(ck, 0) >= CITY_DAY_CAP: continue
                    bids, asks, _ = book(b["no"])
                    if not asks: continue
                    ask = asks[0][0]
                    edge = 1 - ask - b["fee"] * ask * (1 - ask)
                    if ask > MAX_PRICE or edge < MIN_EDGE: continue
                    if not check_weather(b["cid"], e["title"], e["desc"], e["icao"], e["unit"], e["kind"]):
                        log.warning("guard rejected %s", e["slug"]); continue
                    usd = min(CAP_USD - spent.get(b["cid"], 0), CITY_DAY_CAP - spent.get(ck, 0))
                    sh, avg = ex.buy_taker(b["no"], MAX_PRICE, usd, b["fee"], tag=f"dead {e['slug']} {b['title']} ext={ext}")
                    if sh:
                        spent[b["cid"]] = spent.get(b["cid"], 0) + sh * avg; spent[ck] = spent.get(ck, 0) + sh * avg
                        log.info("BUY NO %s %s ext=%s %.1f sh @ %.3f", e["slug"], b["title"], ext, sh, avg)
            n_dead = sum(1 for _ in spent)
            log.info("cycle ok: events=%d positions=%d", len(events), len([k for k in spent if k.startswith("0x")]))
            _save_spent(ex, spent)
        except Exception as exn:
            log.exception("cycle error: %s", exn)
        time.sleep(max(5, CYCLE - (time.time() - t0)))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run()
