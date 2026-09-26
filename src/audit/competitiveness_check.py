"""Is clob /rewards/markets/multi `market_competitiveness` on the same scale as the aggregate reward score Q_min of the
resting book (so that share = Q_ours / (Q_ours + competitiveness))?  Undocumented field ("Competitiveness score").

Takes near-simultaneous snapshots of market_competitiveness (weather tag) and of the YES books, computes several candidate
score definitions from the book and reports correlation, the median ratio comp/Q and its dispersion, per definition and by
book shape (balanced two-sided vs one-sided). Repeats N times to check how fast `market_competitiveness` updates.
Usage: python src/audit/competitiveness_check.py [n_rounds=2] [gap_s=120]
"""
import sys, time, json, math, requests, numpy as np, pandas as pd

S = requests.Session()


def multi():
    out, cur = [], None
    while True:
        p = {"tag_slug": "weather", "limit": 500}
        if cur: p["next_cursor"] = cur
        d = S.get("https://clob.polymarket.com/rewards/markets/multi", params=p, timeout=60).json()
        out += d.get("data", []); cur = d.get("next_cursor")
        if not cur or cur == "LTE=" or not d.get("data"): break
    return {m["condition_id"]: m for m in out if m.get("rewards_config")}


def books(toks):
    out = {}
    for i in range(0, len(toks), 400):
        for b in S.post("https://clob.polymarket.com/books", json=[{"token_id": t} for t in toks[i:i + 400]], timeout=60).json() or []:
            out[b["asset_id"]] = b
    return out


def sc(v, s): return ((v - s) / v) ** 2 if s < v else 0.0


def scores(b, v, mn):
    bids = sorted([(float(x["price"]), float(x["size"])) for x in b["bids"]], key=lambda x: -x[0])
    asks = sorted([(float(x["price"]), float(x["size"])) for x in b["asks"]], key=lambda x: x[0])
    if not bids or not asks: return None

    def adj(lv):
        c = 0
        for p, s in lv:
            c += s
            if c >= mn: return p
        return None
    ab, aa = adj(bids), adj(asks)
    if ab is None or aa is None: return None
    out = {}
    for mname, mid in [("adjmid", (ab + aa) / 2), ("rawmid", (bids[0][0] + asks[0][0]) / 2)]:
        for filt in ["all", "lvl>=min"]:
            B = [(p, s) for p, s in bids if filt == "all" or s >= mn]; A = [(p, s) for p, s in asks if filt == "all" or s >= mn]
            q1 = sum(sc(v, (mid - p) * 100) * s for p, s in B); q2 = sum(sc(v, (p - mid) * 100) * s for p, s in A)
            q1d = sum(sc(v, (mid - p) * 100) * s * p for p, s in B); q2d = sum(sc(v, (p - mid) * 100) * s * (1 - p) for p, s in A)
            agg = max(min(q1, q2), max(q1, q2) / 3) if 0.1 <= mid <= 0.9 else min(q1, q2)
            out[f"{mname}|{filt}|aggQmin"] = agg
            out[f"{mname}|{filt}|max(q1,q2)"] = max(q1, q2)
            out[f"{mname}|{filt}|q1+q2"] = q1 + q2
            out[f"{mname}|{filt}|dollarQmin"] = max(min(q1d, q2d), max(q1d, q2d) / 3)
            if mname == "adjmid" and filt == "all": out["balance"] = min(q1, q2) / max(q1, q2) if max(q1, q2) > 0 else np.nan
    out["mid"] = (ab + aa) / 2; out["spread"] = aa - ab
    return out


def snapshot():
    M = multi()
    t0 = time.time()
    B = books([m["tokens"][0]["token_id"] for m in M.values()])
    rows = []
    for cid, m in M.items():
        b = B.get(m["tokens"][0]["token_id"])
        if not b: continue
        s = scores(b, m["rewards_max_spread"] or 4.5, m["rewards_min_size"] or 20)
        if s is None: continue
        rate = sum(x.get("rate_per_day", 0) for x in m["rewards_config"])
        rows.append(dict(cid=cid, comp=m["market_competitiveness"], rate=rate, **s))
    return pd.DataFrame(rows), t0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2; gap = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    snaps = []
    for i in range(n):
        D, t0 = snapshot(); snaps.append(D)
        print(f"round {i}: {len(D)} two-sided rewarded weather markets")
        if i < n - 1: time.sleep(gap)
    D = snaps[0]
    cols = [c for c in D.columns if "|" in c]
    ok = (D.comp > 0)
    print(f"\nmarkets={len(D)}  comp==0: {np.mean(D.comp == 0):.2f}  comp median={D.comp.median():.2f}")
    print(f"{'definition':32s} {'pearson(log)':>12s} {'spearman':>9s} {'median comp/Q':>13s} {'IQR comp/Q':>18s}")
    for c in cols:
        x = D[ok & (D[c] > 0)]
        r = x.comp / x[c]
        print(f"{c:32s} {np.corrcoef(np.log(x.comp), np.log(x[c]))[0, 1]:12.3f} {x.comp.corr(x[c], method='spearman'):9.3f} "
              f"{r.median():13.4f} ({r.quantile(.25):.4f},{r.quantile(.75):.4f})")
    c = "adjmid|all|aggQmin"; x = D[ok & (D[c] > 0)].copy(); x["r"] = x.comp / x[c]
    x["shape"] = pd.cut(x.balance, [-0.01, 0.05, 0.33, 0.7, 1.01], labels=["one-sided", "lopsided", "mixed", "balanced"])
    print("\nmedian comp/aggQmin by book shape:", x.groupby("shape", observed=True).r.median().round(4).to_dict())
    x["pb"] = pd.cut(x.mid, [0, 0.1, 0.3, 0.7, 0.9, 1]); print("by mid:", x.groupby("pb", observed=True).r.median().round(4).to_dict())
    if n > 1:
        E = snaps[0].merge(snaps[-1], on="cid", suffixes=("_0", "_1"))
        print(f"\ncomp changed between rounds ({gap * (n - 1)} s apart) in {np.mean(E.comp_0 != E.comp_1):.2f} of markets; "
              f"book Q changed in {np.mean(np.abs(E['adjmid|all|aggQmin_0'] - E['adjmid|all|aggQmin_1']) > 1e-6):.2f}")
    # implied share of a 20-share quote 1c from mid (S=(3.5/4.5)^2) under each denominator, markets with rate 10-20
    q_ours = 20 * sc(4.5, 1.0)
    y = D[(D.rate >= 10) & (D.rate <= 20)]
    print(f"\n20-share quote at 1c (Q={q_ours:.1f}), pools $10-20/day (n={len(y)}): median share using comp as denominator = "
          f"{np.median(q_ours / (q_ours + y.comp)):.2f}; using book aggQmin = {np.median(q_ours / (q_ours + y['adjmid|all|aggQmin'])):.2f}; "
          f"using max(q1,q2) (sim_lp) = {np.median(q_ours / (q_ours + y['adjmid|all|max(q1,q2)'])):.2f}")
    pd.concat(snaps).to_csv("/tmp/competitiveness_check.csv", index=False)
