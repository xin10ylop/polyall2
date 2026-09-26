"""Trade-level forensics for a reference wallet in data-lead families: entry price, time-to-close, outcome.
Market metadata via gamma /markets?condition_ids=... cached in data/datalead/wallets/markets_meta.json"""
import json, os, sys, time, re, collections, datetime as dt
import requests, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from wallets import W, family
D = os.path.join(os.path.dirname(__file__), "../../data/datalead/wallets")


def meta(cids):
    fn = os.path.join(D, "markets_meta.json")
    M = json.load(open(fn)) if os.path.exists(fn) else {}
    need = [c for c in cids if c not in M]
    for i in range(0, len(need), 20):
        chunk = need[i:i + 20]
        for closed in ("true", "false"):
            for k in range(5):
                try:
                    r = requests.get("https://gamma-api.polymarket.com/markets", params=[("condition_ids", c) for c in chunk] + [("limit", 50), ("closed", closed)], timeout=30)
                    if r.status_code == 200:
                        for m in r.json():
                            M[m["conditionId"]] = {k2: m.get(k2) for k2 in ["question", "closedTime", "endDate", "outcomePrices", "closed", "feeSchedule", "createdAt"]}
                        break
                except Exception:
                    pass
                time.sleep(2 ** k)
    json.dump(M, open(fn, "w"))
    return M


def ts(s):
    if not s:
        return None
    s = s.replace(" ", "T")
    if s.endswith("+00"):
        s += ":00"
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "KimchiCapital"
    fams = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else {"spotify", "billboard", "album_sales"}
    tr = json.load(open(os.path.join(D, f"{W[name]}_trades.json")))
    tr = [t for t in tr if family(t["title"]) in fams]
    M = meta(sorted({t["conditionId"] for t in tr}))
    rows = []
    for t in tr:
        m = M.get(t["conditionId"])
        if not m or not m.get("closed"):
            continue
        op = json.loads(m["outcomePrices"] or "[]")
        if not op or op[t["outcomeIndex"]] not in ("0", "1"):
            continue
        won = op[t["outcomeIndex"]] == "1"
        ct = ts(m.get("closedTime"))
        rate = (m.get("feeSchedule") or {}).get("rate") or 0
        p = t["price"]; sz = t["size"]
        sgn = 1 if t["side"] == "BUY" else -1
        pnl = sgn * sz * ((1 if won else 0) - p) - (rate * sz * p * (1 - p))  # fee as if taker (upper bound)
        rows.append(dict(fam=family(t["title"]), title=t["title"][:70], side=t["side"], p=p, sz=sz, usd=p * sz, won=won,
                         h_to_close=(ct - t["timestamp"]) / 3600 if ct else None, pnl=pnl, ts=t["timestamp"],
                         wk=time.strftime("%G-W%V", time.gmtime(t["timestamp"]))))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(D, f"forensics_{name}.csv"), index=False)
    b = df[df.side == "BUY"]
    print(name, "trades", len(df), "buys", len(b))
    for f, g in df.groupby("fam"):
        gb = g[g.side == "BUY"]
        print(f"{f:12s} n={len(g)} buys={len(gb)} buy_hit={gb.won.mean():.3f} avg_buy_px={gb.p.mean():.3f} usd={g.usd.sum():.0f} pnl~={g.pnl.sum():.0f} "
              f"med_h_to_close={gb.h_to_close.median():.1f}")
        gb = gb.assign(hb=pd.cut(gb.h_to_close, [-1, 1, 6, 24, 72, 168, 1e5]), pb=pd.cut(gb.p, [0, .5, .8, .9, .95, 1]))
        print(gb.groupby("hb", observed=True).agg(n=("p", "size"), px=("p", "mean"), hit=("won", "mean"), usd=("usd", "sum"), pnl=("pnl", "sum")).round(3).to_string())
        print(gb.groupby("pb", observed=True).agg(n=("p", "size"), px=("p", "mean"), hit=("won", "mean"), usd=("usd", "sum"), pnl=("pnl", "sum")).round(3).to_string())
