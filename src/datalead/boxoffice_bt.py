"""Backtest: weekend box-office bracket markets, taker entry after the Sunday studio estimate is public.

Signal at decision time T (default Sunday 18:00 UTC = 2pm ET / 11am PT; studio estimates are out Sunday
~9-11am PT, Deadline often earlier): E = BOM Sunday estimate for the film.
Model: P(bracket) = share of historical log(actual/estimate) errors (BOM, all films with est >= $1M, from
weekends STRICTLY BEFORE this one) that put E*exp(err) inside the bracket; capped to [0.01, 0.99] for model /
resolution-source risk (market resolves on The Numbers finals, not BOM).
Entry: taker only, price = actual taker prints of the same direction in [T, T+3h] (size-capped by those
prints); fallback (flagged) = price-history value at T + 2c. Fee = shares*rate*p*(1-p).
"""
import os, re, sys, json, datetime as dt, collections
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import pmdata

D = os.path.join(os.path.dirname(__file__), "../../data/datalead")
MULTI = re.compile(r"4-day|5-day|five-day|four-day|6-day", re.I)


def load():
    evs = json.load(open(os.path.join(D, "boxoffice_markets.json")))
    bom = pd.read_parquet(os.path.join(D, "bom_est_all.parquet"))
    bom["fri"] = [dt.date.fromisocalendar(int(y), int(w), 5) for y, w in zip(bom.year, bom.week)]
    return evs, bom


def usable(ev):
    if not ev.get("closed") or not ev.get("bom") or not ev.get("friday"):
        return False, "not closed/matched"
    if MULTI.search(ev["slug"] + " " + ev["title"] + " " + ev["description"][:400]):
        return False, "multi-day window"
    mk = [m for m in ev["markets"] if m["lo"] is not None]
    if len(mk) != len(ev["markets"]) or len(mk) < 2:
        return False, "bracket parse"
    if sum(1 for m in mk if m["won"]) != 1:
        return False, "no unique winner"
    try:
        float(ev["bom"]["est"]); float(ev["bom"]["actual"])
    except (TypeError, ValueError):
        return False, "no estimate"
    return True, ""


def p_bracket(E, lo, hi, errs):
    x = E * np.exp(errs)
    p = np.mean((x >= lo) & (x < hi))
    return float(np.clip(p, 0.01, 0.99))


def run(dec_offset_h=18 + 48, theta=0.03, window=3 * 3600, stake=None, side_filter=None, min_train=150):
    """dec_offset_h: hours after Friday 00:00 UTC (66 = Sunday 18:00 UTC)."""
    evs, bom = load()
    rows, skipped = [], collections.Counter()
    for ev in evs:
        ok, why = usable(ev)
        if not ok:
            skipped[why] += 1; continue
        fri = dt.date.fromisoformat(ev["friday"])
        T = dt.datetime.combine(fri, dt.time(0), tzinfo=dt.timezone.utc).timestamp() + dec_offset_h * 3600
        hist = bom[(bom.fri < fri) & (bom.est >= 1e6)]
        if len(hist) < min_train:
            skipped["train<min"] += 1; continue
        errs = hist.lr.clip(-0.5, 0.5).values
        E = float(ev["bom"]["est"]) / 1e6
        A = float(ev["bom"]["actual"]) / 1e6
        for m in ev["markets"]:
            ct = m.get("closedTime")
            if ct:
                cts = dt.datetime.fromisoformat(ct.replace(" ", "T").replace("+00", "+00:00")).timestamp()
                if cts <= T:
                    skipped["closed before T"] += 1; continue
            P = p_bracket(E, m["lo"], m["hi"], errs)
            rate = m["fee"] or 0.0
            for side in ("Y", "N"):
                if side_filter and side != side_filter:
                    continue
                pw = P if side == "Y" else 1 - P
                f = pmdata.fill(m["conditionId"], T, side, window)
                src = "print"
                if f is None:
                    mid = pmdata.mid_at(m["conditionId"], T)
                    if mid is None:
                        continue
                    px = (mid if side == "Y" else 1 - mid) + 0.02
                    if px >= 0.995:
                        continue
                    f = (px, None, T); src = "mid+2c"
                px, avail, t_fill = f
                fee = rate * px * (1 - px)
                edge = pw - px - fee
                if edge < theta:
                    continue
                win = m["won"] if side == "Y" else (not m["won"])
                rows.append(dict(slug=ev["slug"], film=ev["film"], wknum=ev["wknum"], fri=ev["friday"], lo=m["lo"], hi=m["hi"],
                                 E=E, A=A, side=side, P=pw, px=px, fee=fee, edge=edge, win=int(win), src=src, avail=avail,
                                 lag_h=(t_fill - T) / 3600 if t_fill else None, rate=rate, cid=m["conditionId"]))
    return pd.DataFrame(rows), skipped


def summarize(df, label=""):
    if df.empty:
        print(label, "no trades"); return {}
    df = df.copy()
    df["pnl_sh"] = df.win - df.px - df.fee          # per share
    df["roi"] = df.pnl_sh / df.px
    out = dict(label=label, trades=len(df), events=df.slug.nunique(), hit=df.win.mean(), avg_px=df.px.mean(),
               avg_edge_model=df.edge.mean(), roi=df.pnl_sh.sum() / df.px.sum(), roi_eq=df.roi.mean(),
               share_print=(df.src == "print").mean())
    for S in (10, 50, 200):
        sh = S / df.px
        if "avail" in df:
            cap = df.avail.fillna(0).where(df.src == "print", 0)
            sh_c = np.minimum(sh, cap)
        pnl = (sh * df.pnl_sh).sum()
        pnl_c = (sh_c * df.pnl_sh).sum()
        out[f"pnl_{S}"] = pnl
        out[f"pnl_{S}_printcap"] = pnl_c
        out[f"fill_{S}"] = (sh_c * df.px).sum() / (S * len(df))
    return out


def favorite_calib(dec_offset_h, window=3 * 3600):
    """At T: buy YES of the bracket with the highest mid (market favourite) at the printed ask; also the bracket
    containing the Sunday estimate E ('estimate bracket'). Returns per-event rows."""
    evs, bom = load()
    rows = []
    for ev in evs:
        ok, why = usable(ev)
        if not ok:
            continue
        fri = dt.date.fromisoformat(ev["friday"])
        T = dt.datetime.combine(fri, dt.time(0), tzinfo=dt.timezone.utc).timestamp() + dec_offset_h * 3600
        E = float(ev["bom"]["est"]) / 1e6
        mids = []
        for m in ev["markets"]:
            ct = m.get("closedTime")
            if ct and dt.datetime.fromisoformat(ct.replace(" ", "T").replace("+00", "+00:00")).timestamp() <= T:
                mids = []; break
            mids.append((pmdata.mid_at(m["conditionId"], T), m))
        if not mids or any(x is None for x, _ in mids):
            continue
        fav = max(mids, key=lambda x: x[0])
        estm = [m for _, m in mids if m["lo"] <= E < m["hi"]]
        for tag, m in (("fav", fav[1]), ("est", estm[0] if estm else None)):
            if m is None:
                continue
            f = pmdata.fill(m["conditionId"], T, "Y", window)
            mid = pmdata.mid_at(m["conditionId"], T)
            px, src = (f[0], "print") if f else (min(mid + 0.02, 0.999), "mid+2c")
            rows.append(dict(slug=ev["slug"], tag=tag, mid=mid, px=px, src=src, win=int(m["won"]), fee=(m["fee"] or 0) * px * (1 - px),
                             same=int(m is fav[1])))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    res = []
    for h, lab in [(64, "Sun16"), (66, "Sun18"), (68, "Sun20"), (71, "Sun23"), (76, "Mon04"), (84, "Mon12"), (88, "Mon16")]:
        for th in (0.03, 0.08):
            df, sk = run(h, theta=th)
            r = summarize(df, f"{lab} th{th}")
            res.append(r)
            if h == 66 and th == 0.03:
                df.to_csv(os.path.join(D, "bt_boxoffice_sun18.csv"), index=False)
                print("skipped", dict(sk))
        fc = favorite_calib(h)
        for tag, g in fc.groupby("tag"):
            print(f"{lab} {tag}: n={len(g)} mid={g.mid.mean():.3f} px={g.px.mean():.3f} hit={g.win.mean():.3f} "
                  f"pnl/sh={(g.win - g.px - g.fee).mean():+.4f} fav==estBracket={g.same.mean():.2f}")
    R = pd.DataFrame(res)
    print(R[["label", "trades", "events", "hit", "avg_px", "avg_edge_model", "roi", "pnl_10", "pnl_50_printcap", "pnl_200_printcap", "share_print"]].round(3).to_string())
    R.to_csv(os.path.join(D, "bt_boxoffice_summary.csv"), index=False)


def overnight_rule(hours=(52, 54, 56, 58), lo=0.55, hi=0.95, window=3 * 3600, all_events=False):
    """Price-only proxy for 'Saturday-night projection is public but US is asleep': at T (hours after Fri 00 UTC;
    54 = Sun 06:00 UTC) buy YES of the market-favourite bracket if its executable ask is in [lo, hi].
    One entry per event (first T that qualifies)."""
    evs, bom = load()
    rows = []
    for ev in evs:
        if all_events:
            if not ev.get("closed") or not ev.get("friday") or sum(1 for m in ev["markets"] if m["won"]) != 1:
                continue
        else:
            ok, _ = usable(ev)
            if not ok:
                continue
        fri = dt.date.fromisoformat(ev["friday"])
        for h in hours:
            T = dt.datetime.combine(fri, dt.time(0), tzinfo=dt.timezone.utc).timestamp() + h * 3600
            mids = []
            for m in ev["markets"]:
                ct = m.get("closedTime")
                if ct and dt.datetime.fromisoformat(ct.replace(" ", "T").replace("+00", "+00:00")).timestamp() <= T:
                    mids = []; break
                mids.append((pmdata.mid_at(m["conditionId"], T), m))
            if not mids or any(x is None for x, _ in mids):
                continue
            mid, m = max(mids, key=lambda x: x[0])
            f = pmdata.fill(m["conditionId"], T, "Y", window)
            px, avail, src = (f[0], f[1], "print") if f else (mid + 0.02, 0.0, "mid+2c")
            if not (lo <= px <= hi):
                continue
            fee = (m["fee"] or 0) * px * (1 - px)
            rows.append(dict(slug=ev["slug"], fri=ev["friday"], year=ev["friday"][:4], h=h, mid=mid, px=px, avail=avail, src=src,
                             win=int(m["won"]), fee=fee, pnl_sh=int(m["won"]) - px - fee,
                             vol_24h=pmdata.volume_between(m["conditionId"], T, T + 86400)))
            break
    return pd.DataFrame(rows)
