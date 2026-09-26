"""Reward estimate restricted to temperature markets, quoting only until `lh` hours before station-local midnight of the target day."""
import sys, os, re, json, datetime as dt, numpy as np, collections
from zoneinfo import ZoneInfo
from timezonefinder import TimezoneFinder
sys.path.insert(0, os.path.dirname(__file__))
import sim_lp as S
ROOT = os.path.join(os.path.dirname(__file__), "../..")
import pandas as pd, requests
tag = sys.argv[1] if len(sys.argv) > 1 else "weather"
snaps, cfg, trades = S.load(tag)
span = (snaps[-1]["ts"] - snaps[0]["ts"]) / 3600
st = pd.read_csv(f"{ROOT}/data/weather/stations.csv").set_index("icao")
TF = TimezoneFinder()
MON = {m: i for i, m in enumerate(["january","february","march","april","may","june","july","august","september","october","november","december"], 1)}
# station per event slug from gamma (cache)
cache_fn = f"{ROOT}/data/live/event_station_cache.json"
cache = json.load(open(cache_fn)) if os.path.exists(cache_fn) else {}
local0 = {}
for cid, m in cfg.items():
    q = (m["q"] or "").lower()
    if "temperature" not in q: continue
    ev = m.get("event")
    if ev not in cache:
        try:
            e = requests.get("https://gamma-api.polymarket.com/events", params={"slug": ev}, timeout=20).json()[0]
            s_ = re.search(r"(?:site=|/history/daily/[^\s]*?/)([A-Za-z0-9]{4})\b", e.get("description") or "")
            cache[ev] = s_.group(1).upper() if s_ else None
        except Exception:
            cache[ev] = None
    icao = cache.get(ev)
    md = re.search(r" on (\w+) (\d+)", q)
    if not icao or icao not in st.index or not md or md.group(1) not in MON: continue
    tz = TF.timezone_at(lat=float(st.loc[icao, "lat"]), lng=float(st.loc[icao, "lon"]))
    yr = int(m["end"][:4])
    local0[cid] = dt.datetime.combine(dt.date(yr, MON[md.group(1)], int(md.group(2))), dt.time(0, 0), ZoneInfo(tz)).timestamp()
json.dump(cache, open(cache_fn, "w"))
print(f"snapshots={len(snaps)} span_h={span:.2f} temp markets with local tz={len(local0)}")
for d in [0.01, 0.02, 0.03]:
    for lh in [0, 6]:
        res = S.simulate(snaps, cfg, trades, d=d, local0=local0, lhmin=lh, only_temp=True)
        rows = [(r["reward"] / span * 24, r.get("cap", 0), r["share_sum"] / max(1, r["q_samples"]), cid) for cid, r in res.items() if r["q_samples"] > 0]
        # normalize per market-day of quoting: reward accrues only while quoting; per_mkt_day = reward / (q_samples minutes/1440)
        qd = sum(r["q_samples"] for r in res.values()) / 1440 * (span * 60 / max(1, len(snaps))) if snaps else 1
        tot = sum(x[0] for x in rows)
        rew_in_span = sum(r["reward"] for r in res.values()); qdays = sum(r["q_samples"] * (span * 60 / len(snaps)) for r in res.values()) / 1440
        print(f"d={d} quote until {lh}h before local midnight: markets={len(rows)} reward_per_quoted_market_day=${rew_in_span / max(qdays, 1e-9):.2f} "
              f"median_share={np.median([x[2] for x in rows]) if rows else 0:.2f} capital=${sum(x[1] for x in rows):.0f}")
