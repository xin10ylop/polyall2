"""Walk-forward backtest of the probabilistic weather NOWCAST strategy (observation day, taker).
Model: empirical remaining-rise/drop tables fit on IEM history strictly before TEST_START.
Data at decision time t: IEM obs with valid_time + 10 min <= t (as-of), running extreme & deficit.
Execution evidence: real taker prints (data-api) acquiring the token we want in (t, t+WIN]; our fill price =
that print's price + SLIP, size capped by the print size. One entry per (market, side). Fee = rate*q*(1-q).
Usage: python bt_nowcast.py [margin] [slip]
"""
import os, sys, json, re, glob, math, datetime as dt
import numpy as np, pandas as pd
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
import rise_model as RM
ROOT = os.path.join(os.path.dirname(__file__), "../..")
TEST_START = "2026-07-01"; WIN = 600; STEP = 600
MARGIN = float(sys.argv[1]) if len(sys.argv) > 1 else 0.05
SLIP = float(sys.argv[2]) if len(sys.argv) > 2 else 0.005
MON = {m: i for i, m in enumerate(["january","february","march","april","may","june","july","august","september","october","november","december"], 1)}
rx = re.compile(r"(?:site=|/history/daily/[^\s]*?/)([A-Za-z0-9]{4})\b")

def parse_bucket(t):
    t = t.replace("≤", "<=").replace("≥", ">=").strip()
    for pat, f in [(r"^(-?\d+)\s*°?[FC]?\s*or below$", lambda m: (-999, int(m.group(1)))), (r"^(-?\d+)\s*°?[FC]?\s*or (higher|above)$", lambda m: (int(m.group(1)), 999)),
                   (r"^(-?\d+)\s*-\s*(-?\d+)\s*°?[FC]?$", lambda m: (int(m.group(1)), int(m.group(2)))), (r"^(-?\d+)\s*°?[FC]?$", lambda m: (int(m.group(1)), int(m.group(1))))]:
        mm = re.match(pat, t)
        if mm: return f(mm)
    return None

def p_bucket(model, st, hour, dd, month, R, lo, hi, kind):
    def pge(k):
        if k <= 0: return 1.0
        if k <= 5: return model.p_ge(st, hour, dd, month, k)
        return model.p_ge(st, hour, dd, month, 5) * 0.5 ** (k - 5)
    if kind == "highest":
        if hi < R: return 0.0
        a = 1.0 if lo <= R else pge(lo - R)
        b = pge(hi - R + 1) if hi < 999 else 0.0
        return max(0.0, a - b)
    else:
        if lo > R: return 0.0
        a = 1.0 if hi >= R else pge(R - hi)
        b = pge(R - lo + 1) if lo > -999 else 0.0
        return max(0.0, a - b)

# ---- markets
cids = set(json.loads(l)["conditionId"] for l in open(f"{ROOT}/data/sample_weather_recent.jsonl"))
# add ALL weather temp markets in Jul-Sep that have trades on disk
mk = []
for fn in sorted(glob.glob(f"{ROOT}/data/raw/markets/2026-0[789]-*.jsonl")):
    for l in open(fn):
        m = json.loads(l)
        if m["conditionId"] not in cids: continue
        q = m["question"].lower(); kind = "highest" if "highest temperature" in q else ("lowest" if "lowest temperature" in q else None)
        s = rx.search(m.get("description") or ""); md = re.search(r" on (\w+) (\d+)", q)
        b = parse_bucket(m.get("groupItemTitle") or "")
        if not (kind and s and md and b and md.group(1) in MON): continue
        icao = s.group(1).upper()
        if icao not in RM.ST.index or not os.path.exists(f"{ROOT}/data/weather/obs/{icao}.csv.gz"): continue
        op = [float(x) for x in json.loads(m["outcomePrices"])]
        yr = int(m["endDate"][:4]); day = dt.date(yr, MON[md.group(1)], int(md.group(2)))
        if day.isoformat() < TEST_START: continue
        fs = m.get("feeSchedule") or {}
        mk.append(dict(cid=m["conditionId"], icao=icao, kind=kind, day=day, lo=b[0], hi=b[1], y=int(op[0] > 0.5), rate=fs.get("rate", 0.05) if m.get("feesEnabled") else 0.0, q=m["question"]))
print("test markets", len(mk))
stations = sorted(set(m["icao"] for m in mk))
models = {k: RM.RiseModel([s for s in RM.ST.index if os.path.exists(f"{ROOT}/data/weather/obs/{s}.csv.gz")], end_date=TEST_START, kind=k) for k in ("highest", "lowest")}
obs = {s: RM.load_station(s) for s in stations}
rows = []
for m in mk:
    tr_fn = f"{ROOT}/data/raw/trades/{m['cid']}.csv.gz"
    if not os.path.exists(tr_fn): continue
    tr = pd.read_csv(tr_fn)
    if tr.empty: continue
    buy = tr.side == "B"; tok = np.where(buy, tr.oi, 1 - tr.oi); qq = np.where(buy, tr.price, 1 - tr.price)
    o = np.argsort(tr.ts.values); TT = tr.ts.values[o]; TOK = tok[o]; QQ = qq[o]; SZ = tr["size"].values[o]
    ob = obs[m["icao"]]; od = ob[ob.day == m["day"]].sort_values("ltime")
    if len(od) < 12: continue
    tz = od.ltime.iloc[0].tz
    avail = od.ltime.map(lambda x: x.timestamp()).values + 600
    temps = od.temp.values; hours = od.hour.values
    day0 = dt.datetime.combine(m["day"], dt.time(0, 0), tz).timestamp()
    done = set()
    for t in np.arange(day0 + 10 * 3600, day0 + 20 * 3600, STEP):
        k = np.searchsorted(avail, t, side="right")
        if k == 0: continue
        R = temps[:k].max() if m["kind"] == "highest" else temps[:k].min()
        cur = temps[k - 1]; dd = (R - cur) if m["kind"] == "highest" else (cur - R)
        hour = (t - day0) / 3600
        p = p_bucket(models[m["kind"]], m["icao"], hour, dd, m["day"].month, R, m["lo"], m["hi"], m["kind"])
        j0 = np.searchsorted(TT, t, side="right"); j1 = np.searchsorted(TT, t + WIN, side="right")
        for side, fair in (("NO", 1 - p), ("YES", p)):
            if side in done: continue
            want = 1 if side == "NO" else 0
            for j in range(j0, j1):
                if TOK[j] != want: continue
                px = min(0.999, QQ[j] + SLIP)
                fee = m["rate"] * px * (1 - px)
                if fair - px - fee > MARGIN:
                    win = (1 - m["y"]) if side == "NO" else m["y"]
                    rows.append(dict(cid=m["cid"], icao=m["icao"], kind=m["kind"], day=m["day"], hour=hour, side=side, fair=fair, px=px, fee=fee,
                                     size=SZ[j], win=win, pnl_per_sh=win - px - fee, bucket=(m["lo"], m["hi"]), R=R, q=m["q"]))
                    done.add(side)
                break
R_ = pd.DataFrame(rows)
if R_.empty: print("no trades"); sys.exit()
R_["roi"] = R_.pnl_per_sh / (R_.px + R_.fee)
R_["usd"] = np.minimum(R_["size"] * R_.px, 50.0)
R_["pnl50"] = R_.usd * R_.roi
R_["week"] = pd.to_datetime(R_.day).dt.isocalendar().week
print(f"margin={MARGIN} slip={SLIP}: trades={len(R_)} markets={R_.cid.nunique()} hit={R_.win.mean():.3f} avg_px={R_.px.mean():.3f} ROI/trade={R_.roi.mean():+.4f} "
      f"PnL(<=$50/trade,size-capped)=${R_.pnl50.sum():.0f} on ${R_.usd.sum():.0f}; worst={R_.pnl50.min():.1f}")
for side in ("NO", "YES"):
    s = R_[R_.side == side]
    if len(s): print(f"  {side}: n={len(s)} hit={s.win.mean():.3f} px={s.px.mean():.3f} ROI={s.roi.mean():+.4f} PnL50=${s.pnl50.sum():.0f}")
pb = pd.cut(R_.px, [0, .5, .8, .9, .95, .98, 1])
print(R_.groupby(pb, observed=True).agg(n=("roi", "size"), hit=("win", "mean"), roi=("roi", "mean"), pnl=("pnl50", "sum")).round(4).to_string())
wk = R_.groupby("week").pnl50.sum(); print("weekly PnL:", wk.round(0).to_dict(), "profitable weeks", (wk > 0).mean().round(2))
R_.to_csv(f"{ROOT}/data/nowcast/bt_trades_m{MARGIN}_s{SLIP}.csv", index=False)
