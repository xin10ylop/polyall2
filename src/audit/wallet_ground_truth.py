"""Ground truth for LP-reward farming from real wallets (audit, research/audit_lp_rewards.md section 2).

Stages (each caches JSON under data/audit/):
  discover : maker wallets in all currently rewarded weather markets (data-api /trades takerOnly=false minus takerOnly=true)
  profile  : per wallet (>=20 maker fills in >=5 markets): REWARD + MAKER_REBATE activity, /value, on-chain pUSD+USDC.e cash
             (Polygon publicnode RPC), user-pnl-api 1w/1m series
  month    : 30-day REWARD history + 1m PnL series
  report   : reward/day, trading PnL/day (user-pnl-api EXCLUDES rewards -- verified: no jump at the 00:00 UTC payout and the
             per-market realised PnL from /closed-positions tracks it), net, all per $ of capital (cash + positions snapshot)
  perfill  : reward and trading PnL per filled maker share for LP-dominated wallets (7 days)
Usage: python src/audit/wallet_ground_truth.py [discover|profile|month|report|perfill|all]
Caveats: capital is a single snapshot; sample = wallets active now (survivorship); selection on having maker fills in
weather markets (wallets that quote but are rarely filled are under-represented); rewards are wallet-wide (all categories).
"""
import os, sys, json, time, collections, datetime as dt, concurrent.futures as cf
import numpy as np, requests

ROOT = os.path.join(os.path.dirname(__file__), "../..")
OUT = f"{ROOT}/data/audit"; os.makedirs(OUT, exist_ok=True)
S = requests.Session(); NOW = time.time()
RPC = "https://polygon-bor-rpc.publicnode.com"
TOK = {"USDCe": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "pUSD": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"}


def gj(url, params, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=60)
            if r.status_code == 200: return r.json()
        except Exception: pass
        time.sleep(1 + 2 * i)
    return None


def cash(addr):
    tot = 0.0
    for t in TOK.values():
        try:
            j = S.post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                  "params": [{"to": t, "data": "0x70a08231" + addr[2:].lower().rjust(64, "0")}, "latest"]}, timeout=20).json()
            tot += int(j["result"], 16) / 1e6
        except Exception: return None
    return tot


def activity(addr, typ, days):
    out = []; off = 0
    while off < 3000:
        d = gj("https://data-api.polymarket.com/activity", {"user": addr, "type": typ, "limit": 500, "offset": off, "start": int(NOW - days * 86400)})
        if not d: break
        out += d; off += 500
        if len(d) < 500: break
    return out


def discover():
    cids, cur = [], None
    while True:
        p = {"tag_slug": "weather", "limit": 500}
        if cur: p["next_cursor"] = cur
        d = gj("https://clob.polymarket.com/rewards/markets/multi", p)
        if not d: break
        cids += [m["condition_id"] for m in d.get("data", []) if m.get("rewards_config")]
        cur = d.get("next_cursor")
        if not cur or cur == "LTE=" or not d.get("data"): break

    def pull(batch, taker):
        out = []; off = 0
        while off <= 3000:
            d = gj("https://data-api.polymarket.com/trades", {"market": ",".join(batch), "limit": 500, "offset": off, "takerOnly": taker}) or []
            out += d
            if len(d) < 500: break
            off += 500
        return out
    batches = [cids[i:i + 10] for i in range(0, len(cids), 10)]
    with cf.ThreadPoolExecutor(6) as ex:
        allf = [x for b in ex.map(lambda b: pull(b, "false"), batches) for x in b]
        allt = [x for b in ex.map(lambda b: pull(b, "true"), batches) for x in b]
    tk = set((x["transactionHash"], x["proxyWallet"]) for x in allt)
    mk = [x for x in allf if (x["transactionHash"], x["proxyWallet"]) not in tk]
    vol = collections.defaultdict(float); n = collections.Counter(); mk_s = collections.defaultdict(set)
    for x in mk:
        vol[x["proxyWallet"]] += x["size"] * x["price"]; n[x["proxyWallet"]] += 1; mk_s[x["proxyWallet"]].add(x["conditionId"])
    w = sorted(vol, key=lambda k: -vol[k])
    json.dump([(k, vol[k], n[k], len(mk_s[k])) for k in w], open(f"{OUT}/maker_wallets.json", "w"))
    print("rewarded weather markets", len(cids), "maker rows", len(mk), "wallets", len(w))


def profile():
    W = [w for w in json.load(open(f"{OUT}/maker_wallets.json")) if w[2] >= 20 and w[3] >= 5]

    def prof(w):
        a = w[0]; r = {"addr": a, "wx_maker_vol": w[1], "wx_maker_n": w[2], "wx_mkts": w[3]}
        days = collections.defaultdict(float)
        for x in activity(a, "REWARD", 15): days[dt.datetime.utcfromtimestamp(x["timestamp"]).strftime("%Y-%m-%d")] += x["usdcSize"] or 0
        r["rew_days"] = dict(days); r["rew_7d"] = sum(v for k, v in days.items() if k >= dt.datetime.utcfromtimestamp(NOW - 6 * 86400).strftime("%Y-%m-%d"))
        r["rebate_7d"] = sum(x["usdcSize"] or 0 for x in activity(a, "MAKER_REBATE", 8))
        v = gj("https://data-api.polymarket.com/value", {"user": a}); r["pos_value"] = v[0]["value"] if v else None
        r["cash"] = cash(a)
        for iv in ["1w", "1m"]:
            p = gj("https://user-pnl-api.polymarket.com/user-pnl", {"user_address": a, "interval": iv, "fidelity": "1d" if iv == "1m" else "1h"})
            if p: r[f"pnl_{iv}"] = [(q["t"], q["p"]) for q in p]
        return r
    with cf.ThreadPoolExecutor(8) as ex: res = list(ex.map(prof, W))
    json.dump(res, open(f"{OUT}/profiles.json", "w")); print("profiled", len(res))


def month():
    P = json.load(open(f"{OUT}/profiles.json"))

    def run(r):
        days = collections.defaultdict(float)
        for x in activity(r["addr"], "REWARD", 31): days[dt.datetime.utcfromtimestamp(x["timestamp"]).strftime("%Y-%m-%d")] += x["usdcSize"] or 0
        return dict(r, rew_days30=dict(days))
    with cf.ThreadPoolExecutor(8) as ex: res = list(ex.map(run, P))
    json.dump(res, open(f"{OUT}/profiles30.json", "w")); print("month", len(res))


def rows30():
    out = []
    for r in json.load(open(f"{OUT}/profiles30.json")):
        p = r.get("pnl_1m") or []
        if len(p) < 20: continue
        (t0, p0), (t1, p1) = p[0], p[-1]; days = (t1 - t0) / 86400
        if days < 20: continue
        d0 = dt.datetime.utcfromtimestamp(t0).strftime("%Y-%m-%d")
        rew = sum(v for k, v in r["rew_days30"].items() if k > d0)
        cap = (r.get("pos_value") or 0) + (r.get("cash") or 0)
        out.append(dict(a=r["addr"], cap=cap, rew=rew / days, dp=(p1 - p0) / days, net=(rew + p1 - p0) / days))
    return out


def report():
    A = [x for x in rows30() if x["rew"] >= 1]

    def summ(X, label):
        if not X: return
        rew = np.array([x["rew"] for x in X]); dp = np.array([x["dp"] for x in X]); net = np.array([x["net"] for x in X])
        cap = np.maximum(np.array([x["cap"] for x in X]), 1)
        print(f"{label:34s} n={len(X):3d} sumRew/d={rew.sum():7.0f} sumPnL/d={dp.sum():8.0f} sumNet/d={net.sum():8.0f} | "
              f"rew/cap p50={np.median(rew / cap) * 100:5.2f}%/d | net/cap p10/p50/p90={np.percentile(net / cap, 10) * 100:6.2f}/"
              f"{np.median(net / cap) * 100:5.2f}/{np.percentile(net / cap, 90) * 100:5.2f}%/d | frac net>0={np.mean(net > 0):.2f} | "
              f"loss/reward p50={np.median(-dp / rew):.2f}")
    summ(A, "all wallets with rewards>=$1/d")
    for lo, hi in [(0, 500), (500, 1500), (1500, 5000), (5000, 20000), (20000, 1e12)]:
        summ([x for x in A if lo <= x["cap"] < hi], f"capital ${lo:,}-{hi:,.0f}")
    L = [x for x in A if abs(x["dp"]) <= 3 * x["rew"]]
    summ(L, "LP-dominated (|PnL|<=3x rewards)"); summ([x for x in L if x["cap"] < 1500], "LP-dominated, capital<$1.5k")


def perfill():
    A = {x["a"]: x for x in rows30()}

    def trades(u, taker):
        out = []; off = 0
        while off <= 3000:
            d = gj("https://data-api.polymarket.com/trades", {"user": u, "limit": 500, "offset": off, "takerOnly": taker}) or []
            out += d; off += 500
            if len(d) < 500 or (d and d[-1]["timestamp"] < NOW - 7 * 86400): break
        return [x for x in out if x["timestamp"] >= NOW - 7 * 86400], len(out) >= 3000

    ws = sorted([a for a, r in A.items() if r["rew"] >= 5 and abs(r["dp"]) <= 3 * r["rew"] and r["cap"] < 20000], key=lambda a: A[a]["cap"])[:40]

    def run(u):
        (allt, trunc), (tk, _) = trades(u, "false"), trades(u, "true")
        keys = set((x["transactionHash"], x["asset"], x["size"]) for x in tk)
        mk = [x for x in allt if (x["transactionHash"], x["asset"], x["size"]) not in keys]
        return u, sum(x["size"] for x in mk), sum(x["size"] * x["price"] for x in mk), sum(x["size"] * x["price"] for x in tk), trunc
    with cf.ThreadPoolExecutor(6) as ex: res = list(ex.map(run, ws))
    tot = collections.defaultdict(float)
    for u, sh, usd, tku, trunc in res:
        if trunc: continue
        r = A[u]; tot["rew"] += r["rew"]; tot["dp"] += r["dp"]; tot["sh"] += sh / 7; tot["usd"] += usd / 7; tot["tk"] += tku / 7
    print(f"LP-dominated wallets (n={sum(1 for x in res if not x[4])}): reward/filled maker share={tot['rew'] / tot['sh']:.4f}, "
          f"trading PnL/filled maker share={tot['dp'] / tot['sh']:.4f}, PnL per maker $={tot['dp'] / tot['usd']:.4f}, "
          f"taker share of $ volume={tot['tk'] / (tot['tk'] + tot['usd']):.2f}")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "report"
    for st, fn in [("discover", discover), ("profile", profile), ("month", month), ("report", report), ("perfill", perfill)]:
        if stage in (st, "all"): fn()
