"""Spotify weekly #1/#2: data-leader vs market, using kworb daily streams (only the last ~31 days of daily
history are published per track, so only chart weeks labelled 2026-09-04 .. 2026-10-02 are testable).
Availability: daily chart for day D usable from D+2 00:00 UTC (conservative; live check 2026-09-26 14:45 UTC
showed 09-24 as the newest chart). Decision times: 12:00 UTC each day of the chart week."""
import json, os, sys, datetime as dt, collections
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import pmdata

D = os.path.join(os.path.dirname(__file__), "../../data/datalead")
MON = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                   "October", "November", "December"], 1)}


def tsx(s):
    s = s.replace(" ", "T"); s = s + ":00" if s.endswith("+00") else s
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def main(avail_days=2):
    k = pd.read_parquet(os.path.join(D, "kworb_all.parquet"))
    k = k[k.scope.isin(["global", "us"])]
    first = k.date.min()
    evs = json.load(open(os.path.join(D, "spotify_markets.json")))
    rows = []
    for e in evs:
        if not e["label"]:
            continue
        mo, dd = e["label"].split(); yr = int(e["end"][:4])
        L = dt.date(yr, MON[mo], int(dd)); wk0 = L - dt.timedelta(days=7)          # chart week Fri wk0 .. Thu L-1
        if pd.Timestamp(wk0) < pd.Timestamp("2026-08-28"):
            continue
        sc = k[(k.scope == e["scope"]) & (k.date >= pd.Timestamp(wk0)) & (k.date <= pd.Timestamp(L - dt.timedelta(days=1)))]
        ct = tsx(e["closedTime"]) if e.get("closedTime") else 1e12
        tid2m = {}
        for m in e["markets"]:
            for t in m.get("tids", []):
                tid2m[t] = m
        other = [m for m in e["markets"] if m["name"].lower() == "other"]
        for d in range(1, 8):
            T = dt.datetime.combine(wk0 + dt.timedelta(days=d), dt.time(12), tzinfo=dt.timezone.utc)
            if T.timestamp() >= ct:
                break
            known = sc[sc.date <= pd.Timestamp(T.date() - dt.timedelta(days=avail_days))]
            nk = known.date.nunique()
            if nk == 0:
                continue
            cum = known.groupby("tid").streams.sum().sort_values(ascending=False)
            last = known[known.date == known.date.max()].set_index("tid").streams
            proj = (cum + last.reindex(cum.index).fillna(0) * (7 - nk)).sort_values(ascending=False)
            r = e["rank"] - 1
            lead_tid = proj.index[r]
            margin = (proj.iloc[r] - proj.iloc[r + 1]) / proj.iloc[r] if len(proj) > r + 1 else 1
            lm = tid2m.get(lead_tid) or (other[0] if other else None)
            mids = [(pmdata.mid_at(m["conditionId"], T.timestamp()), m) for m in e["markets"]]
            mids = [x for x in mids if x[0] is not None]
            fav = max(mids, key=lambda x: x[0])[1] if mids else None
            if lm is None:
                continue
            f = pmdata.fill(lm["conditionId"], T.timestamp(), "Y", 3 * 3600)
            mid = pmdata.mid_at(lm["conditionId"], T.timestamp())
            px = f[0] if f else (mid + 0.02 if mid is not None else None)
            rows.append(dict(slug=e["slug"], scope=e["scope"], rank=e["rank"], day=d, known_days=nk, leader=lm["name"],
                             margin=margin, mid=mid, px=px, avail=f[1] if f else 0, src="print" if f else "mid+2c",
                             fav=fav["name"] if fav else None, leader_is_fav=int(fav is lm), won=lm["won"],
                             fee=lm["fee"]))
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(D, "bt_spotify_recent.csv"), index=False)
    return df


if __name__ == "__main__":
    pd.set_option("display.width", 250)
    df = main()
    c = df[df.won.notna()].copy()
    c["won"] = c.won.astype(int)
    print(c.groupby("known_days").agg(n=("won", "size"), leader_hit=("won", "mean"), mid=("mid", "mean"), px=("px", "mean"),
                                      leader_is_fav=("leader_is_fav", "mean")).round(3).to_string())
    c["pnl"] = c.won - c.px - c.fee * c.px * (1 - c.px)
    s = c[(c.px < 0.97)]
    print("buy data-leader when ask<0.97: n=%d events=%d hit=%.3f px=%.3f pnl/sh=%+.3f" % (len(s), s.slug.nunique(), s.won.mean(), s.px.mean(), s.pnl.mean()))
    print(c[["slug", "day", "known_days", "leader", "margin", "mid", "px", "fav", "won"]].to_string())
