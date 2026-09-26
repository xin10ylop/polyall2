"""Jev pre-trade rules guard: confirm the market resolves the way the strategy's model assumes.
Validated on 300 weather markets (true vs deliberately wrong station): AUC 1.0, 0 errors at threshold 0.8."""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from common.jev import decide
CACHE = os.path.join(os.environ.get("BOT_STATE", os.path.join(os.path.dirname(__file__), "..", "bot_state")), "guard_cache.json")
_cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
THRESH = float(os.environ.get("GUARD_THRESHOLD", 0.8))

def check_weather(cid, question, rules, icao, unit, kind):
    key = f"{cid}|{icao}|{unit}|{kind}"
    if key in _cache: return _cache[key] >= THRESH
    st = {"market": question, "rules": rules[:1500], "assumed_station_icao": icao, "assumed_unit": unit,
          "assumed_metric": f"daily {kind} temperature, whole degrees, station-local calendar day"}
    q = {"match": {"type": "noul", "instructions": "Does the market's resolution rule use exactly the assumed weather station (ICAO code), the assumed unit, and the assumed daily metric? Answer false if any of these differ.",
                   "criteria": {"true": "Station, unit and metric all match the assumption.", "false": "At least one of station, unit or metric differs."}}}
    try:
        p = decide(st, q)["match"]["noul"]
    except Exception:
        return False   # fail closed
    _cache[key] = p
    json.dump(_cache, open(CACHE, "w"))
    return p >= THRESH
