"""Do LP wallets that avoid the observation day do better?  For each maker wallet in rewarded weather markets, the share of
its weather maker-fill shares that occurred after local midnight starting the observation day (daily temperature markets),
joined with its 30-day rewards / trading PnL / capital (wallet_ground_truth.py). Usage: python src/audit/discipline_split.py <trades.json> <rows30.json>"""
import sys, os, json, collections, numpy as np, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from sim_lp_audit import obs_start_live, DAILY
T = json.load(open(sys.argv[1])); R = {r["a"]: r for r in json.load(open(sys.argv[2]))}
tk = set((x["transactionHash"], x["proxyWallet"]) for x in T["taker"])
mk = [x for x in T["all"] if (x["transactionHash"], x["proxyWallet"]) not in tk]
end_ts = dt.datetime(2026, 9, 26, tzinfo=dt.timezone.utc).timestamp()
tot = collections.Counter(); obs = collections.Counter(); late = collections.Counter()
for x in mk:
    q = x.get("title") or ""
    if not DAILY.search(q): continue
    o = obs_start_live(q, end_ts)
    if not np.isfinite(o): continue
    tot[x["proxyWallet"]] += x["size"]
    h = (o - x["timestamp"]) / 3600
    if h < 0: obs[x["proxyWallet"]] += x["size"]
    if h < -12: late[x["proxyWallet"]] += x["size"]
rows = []
for a, r in R.items():
    if r["rew"] < 1 or tot[a] < 100 or abs(r["dp"]) > 3 * r["rew"]: continue
    rows.append(dict(a=a, f=obs[a] / tot[a], fl=late[a] / tot[a], cap=max(r["cap"], 1), rew=r["rew"], dp=r["dp"], net=r["net"]))
print(f"LP-dominated wallets with >=100 daily-temp maker shares: {len(rows)}")
for lo, hi in [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)]:
    X = [x for x in rows if lo <= x["f"] < hi]
    if not X: continue
    rew = np.array([x["rew"] for x in X]); dp = np.array([x["dp"] for x in X]); net = np.array([x["net"] for x in X]); cap = np.array([x["cap"] for x in X])
    print(f"obs-day fill share [{lo:.2f},{hi:.2f}): n={len(X):3d} pooled loss/reward={-dp.sum() / rew.sum():5.2f} median loss/reward={np.median(-dp / rew):5.2f} "
          f"median net/cap={np.median(net / cap) * 100:5.2f}%/d  pooled net/cap={net.sum() / cap.sum() * 100:5.2f}%/d  frac net>0={np.mean(net > 0):.2f} "
          f"median cap=${np.median(cap):,.0f}")
S = [x for x in rows if x["cap"] < 5000]
for lo, hi in [(0, 0.5), (0.5, 1.01)]:
    X = [x for x in S if lo <= x["f"] < hi]
    if not X: continue
    rew = np.array([x["rew"] for x in X]); dp = np.array([x["dp"] for x in X]); net = np.array([x["net"] for x in X]); cap = np.array([x["cap"] for x in X])
    print(f"  capital<$5k, obs-day share [{lo},{hi}): n={len(X)} pooled loss/reward={-dp.sum() / rew.sum():.2f} median net/cap={np.median(net / cap) * 100:.2f}%/d "
          f"p25/p75={np.percentile(net / cap, 25) * 100:.2f}/{np.percentile(net / cap, 75) * 100:.2f}%/d frac net>0={np.mean(net > 0):.2f}")
