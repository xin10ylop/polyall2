"""Sell daily crypto barrier longshots (research/04 §4): in "What price will Bitcoin hit on <day>?" events,
with <= 12 h left in the ET-day window, for strikes whose YES mid is 0.5–3 c, taker-buy NO when the NO ask is
<= 1 - mid + 0.3 c (fee included in the edge check). OOS: +0.7% per trade, 4 losses in 1,460 (0.27%)
vs a 0.8–0.9% break-even loss rate. Tail risk: one crash day can hit several strikes -> per-event cap.
"""
import os, sys, time, json, logging, datetime as dt, re
import requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from execution import Executor, book
log = logging.getLogger("barrier")
ASSETS = os.environ.get("BAR_ASSETS", "bitcoin").split(",")
MID_LO = float(os.environ.get("BAR_MID_LO", 0.005)); MID_HI = float(os.environ.get("BAR_MID_HI", 0.03))
H_MAX = float(os.environ.get("BAR_H_MAX", 12)); SLIP = float(os.environ.get("BAR_SLIP", 0.003))
CAP_USD = float(os.environ.get("BAR_CAP_USD", 100)); EVENT_CAP = float(os.environ.get("BAR_EVENT_CAP", 250))
CYCLE = int(os.environ.get("BAR_CYCLE", 600))

def open_events(asset):
    out = []
    today = dt.datetime.utcnow().date()
    for d in (today - dt.timedelta(days=1), today, today + dt.timedelta(days=1)):
        slug = f"what-price-will-{asset}-hit-on-{d.strftime('%B').lower()}-{d.day}-{d.year}"
        try:
            ev = requests.get("https://gamma-api.polymarket.com/events", params={"slug": slug}, timeout=20).json()
        except Exception:
            continue
        if ev and not ev[0].get("closed"): out.append(ev[0])
    return out

def _state_file(ex):
    return os.path.join(os.path.dirname(ex.ledger), "barrier_spent.json")

def _load_spent(ex):
    try: return json.load(open(_state_file(ex)))
    except Exception: return {}

def _save_spent(ex, spent):
    json.dump(spent, open(_state_file(ex), "w"))

def run():
    ex = Executor(); spent = _load_spent(ex)
    while True:
        t0 = time.time()
        if os.path.exists(os.path.join(os.path.dirname(ex.ledger), "KILL")):
            log.warning("KILL file present; stopping"); return
        try:
            for asset in ASSETS:
                for ev in open_events(asset):
                    end = dt.datetime.fromisoformat(ev["endDate"].replace("Z", "+00:00")).timestamp()
                    h_left = (end - t0) / 3600
                    if not (0.25 < h_left <= H_MAX): continue
                    for m in ev["markets"]:
                        if m.get("closed") or not m.get("acceptingOrders", True): continue
                        yes, no = json.loads(m["clobTokenIds"])
                        bids, asks, _ = book(yes)
                        if not bids or not asks: continue
                        mid = (bids[0][0] + asks[0][0]) / 2
                        if not (MID_LO <= mid <= MID_HI): continue
                        no_ask = round(1 - bids[0][0], 4)
                        fs = m.get("feeSchedule") or {}; rate = fs.get("rate", 0.07) if m.get("feesEnabled", True) else 0.0
                        if no_ask > 1 - mid + SLIP: continue
                        cid = no  # per-strike exposure key = NO token id
                        room = min(CAP_USD - spent.get(cid, 0), EVENT_CAP - spent.get(ev["slug"], 0))
                        if room < 5: continue
                        sh, avg = ex.buy_taker(no, 1 - mid + SLIP, room, rate, tag=f"barrier {ev['slug']} {m.get('groupItemTitle')} mid={mid:.4f} h={h_left:.1f}")
                        if sh:
                            spent[cid] = spent.get(cid, 0) + sh * avg; spent[ev["slug"]] = spent.get(ev["slug"], 0) + sh * avg
                            log.info("BUY NO %s %s %.1f sh @ %.4f (mid %.4f, %.1f h left)", ev["slug"], m.get("groupItemTitle"), sh, avg, mid, h_left)
            log.info("cycle ok")
            _save_spent(ex, spent)
        except Exception as exn:
            log.exception("cycle error: %s", exn)
        time.sleep(max(10, CYCLE - (time.time() - t0)))

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run()
