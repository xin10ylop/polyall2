"""Discipline split using maker fills in CLOSED daily-temperature events (target day complete): share of each wallet's maker
fill shares on/after local midnight of the observation day, joined with 30-day rewards/PnL/capital of LP wallets.
Usage: python src/audit/discipline_split2.py [rows30.json (default data/audit/rows30.json, from wallet_ground_truth.rows30)]"""
import sys, os, json, collections, numpy as np, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from sim_lp_audit import obs_start_live, DAILY
ROOT = os.path.join(os.path.dirname(__file__), "../..")
F = json.load(open(f"{ROOT}/data/audit/closed_event_maker_fills.json"))
R = {r["a"]: r for r in json.load(open(sys.argv[1] if len(sys.argv) > 1 else f"{ROOT}/data/audit/rows30.json"))}
end_ts = dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc).timestamp()
cache = {}; tot = collections.Counter(); obs = collections.Counter(); usd = collections.Counter()
for w, title, ts, sz, pr in F:
    if title not in cache: cache[title] = obs_start_live(title or "", end_ts) if DAILY.search(title or "") else np.nan
    o = cache[title]
    if not np.isfinite(o): continue
    tot[w] += sz; usd[w] += sz * pr
    if ts >= o: obs[w] += sz
print(f"maker fills parsed; wallets={len(tot)}; overall obs-day share of maker shares={sum(obs.values()) / sum(tot.values()):.2f}")
rows = []
for a, r in R.items():
    if r["rew"] < 1 or tot[a] < 200 or abs(r["dp"]) > 3 * r["rew"]: continue
    rows.append(dict(a=a, f=obs[a] / tot[a], cap=max(r["cap"], 1), rew=r["rew"], dp=r["dp"], net=r["net"]))
print(f"LP-dominated wallets with >=200 maker shares in closed temperature events: {len(rows)}")
def summ(X, lab):
    if not X: return
    rew = np.array([x["rew"] for x in X]); dp = np.array([x["dp"] for x in X]); net = np.array([x["net"] for x in X]); cap = np.array([x["cap"] for x in X])
    print(f"{lab:36s} n={len(X):3d} pooled loss/reward={-dp.sum() / rew.sum():5.2f} median loss/reward={np.median(-dp / rew):5.2f} "
          f"net/cap p25/p50/p75={np.percentile(net / cap, 25) * 100:5.2f}/{np.median(net / cap) * 100:5.2f}/{np.percentile(net / cap, 75) * 100:5.2f}%/d "
          f"rew/cap p50={np.median(rew / cap) * 100:5.2f}%/d frac net>0={np.mean(net > 0):.2f} median cap=${np.median(cap):,.0f}")
for lo, hi in [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.01)]:
    summ([x for x in rows if lo <= x["f"] < hi], f"obs-day share [{lo:.1f},{hi:.1f})")
for lo, hi in [(0, 0.3), (0.3, 1.01)]:
    summ([x for x in rows if lo <= x["f"] < hi and x["cap"] < 5000], f"cap<$5k, obs-day share [{lo:.1f},{hi:.1f})")
summ([x for x in rows if x["f"] < 0.3 and x["cap"] < 1500], "cap<$1.5k, obs-day share <0.3")
json.dump(rows, open(f"{ROOT}/data/audit/discipline_rows.json", "w"))
