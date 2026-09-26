"""'Best AI model on <date>' weekly markets (arena.ai text overall, style control off).
Data: HF lmarena-ai/leaderboard-dataset text/full (daily leaderboard versions; version for date D is committed
~D+1 03:00 UTC). Rule: at T = resolution - k days, take the leader of the newest version with
publish_date <= T - 27h (conservative), buy YES on the matching market outcome if ask in [lo, hi]."""
import json, os, sys, re, datetime as dt, difflib
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import pmdata
D = os.path.join(os.path.dirname(__file__), "../../data/datalead")


def tsx(s):
    s = s.replace(" ", "T"); s = s + ":00" if s.endswith("+00") else s
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def run(ks=(1, 2, 3), lo=0.5, hi=0.97, window=3 * 3600):
    lead = pd.read_csv(os.path.join(D, "lmarena/leader_overall.csv"), parse_dates=["date"])
    evs = [e for e in json.load(open(os.path.join(D, "aimodel_markets.json"))) if e["kind"] == "weekly"]
    rows = []
    for e in evs:
        if not e["closed"]:
            continue
        if sum(1 for m in e["markets"] if m["won"]) != 1:
            continue
        # resolution check: 12:00 ET on the date in the title
        mt = re.search(r"on (\w+ \d+)", e["title"])
        day = dt.datetime.strptime(mt.group(1) + " " + e["end"][:4], "%B %d %Y")
        R = day.replace(tzinfo=dt.timezone.utc).timestamp() + 16 * 3600
        for k in ks:
            T = R - k * 86400
            L = lead[lead.date <= pd.Timestamp(T - 27 * 3600, unit="s")]
            if L.empty:
                continue
            ld = L.iloc[-1].model_name
            names = [(m["name"] or "").lower() for m in e["markets"]]
            norm = lambda x: re.sub(r"[^a-z0-9.]", "", x.lower())
            exact = [i for i, n in enumerate(names) if norm(n) == norm(ld)]
            best = exact[0] if exact else None
            if best is None:
                m = [x for x in e["markets"] if (x["name"] or "").lower() == "other"]
                if not m:
                    continue
                m = m[0]
            else:
                m = e["markets"][best]
            f = pmdata.fill(m["conditionId"], T, "Y", window)
            mid = pmdata.mid_at(m["conditionId"], T)
            if f:
                px, avail, src = f[0], f[1], "print"
            elif mid is not None:
                px, avail, src = min(mid + 0.02, 0.999), 0.0, "mid+2c"
            else:
                continue
            fee = m["fee"] * px * (1 - px)
            rows.append(dict(slug=e["slug"], k=k, leader=ld, outcome=m["name"], mid=mid, px=px, avail=avail, src=src,
                             win=int(m["won"]), pnl_sh=int(m["won"]) - px - fee, sel=int(lo <= px <= hi)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    d = run()
    d.to_csv(os.path.join(D, "bt_aimodel.csv"), index=False)
    print(d.groupby("k").agg(n=("win", "size"), leader_hit=("win", "mean"), px=("px", "mean")).round(3))
    t = d[d.sel == 1]
    for k, g in t.groupby("k"):
        se = g.pnl_sh.std() / np.sqrt(len(g))
        cap = lambda S: (np.minimum(S / g.px, g.avail) * g.pnl_sh).sum()
        print(f"k={k}d take ask in [.5,.97]: n={len(g)} px={g.px.mean():.3f} hit={g.win.mean():.3f} pnl/sh={g.pnl_sh.mean():+.4f} se={se:.4f} "
              f"$10={(10 / g.px * g.pnl_sh).sum():+.1f} $50cap={cap(50):+.1f} $200cap={cap(200):+.1f} print={np.mean(g.src == 'print'):.2f}")
    print(t[["slug", "k", "leader", "outcome", "mid", "px", "avail", "win"]].to_string())
