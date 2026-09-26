"""AUDIT of src/live/sim_lp.py + lp_report.py (reward-share paper simulator on recorded live books).

Re-implements the same scoring as sim_lp.simulate but emits one record per (market, snapshot) so the claimed
reward can be decomposed by the optimism biases found in the audit (research/audit_lp_rewards.md, section 1a):
  B1  one-sided / empty books: sim_lp invents a mid (abb = aba - 2v) and quotes around it;
  B2  'sole scorer': our quote is the only order within v of the (new) mid because we quote inside a wide book;
  B3  observation already running: local observation day started (temperature markets, by city time zone) or
      the question's date is today/past for other same-day markets (earthquake, rain...) -- hte>=12h does not exclude these;
  B4  non-daily markets (hurricane, river level, disease counts, yearly climate) mixed into 'weather';
  B5  in-sample top-30 selection evaluated on the same minutes (winner's curse) -> split-sample test;
  B6  extrapolation of a short window to 24 h.
Also reports a 'realistic' variant: exclude B1/B3/B4, cap share when we would be the sole scorer (a competing farmer
joins at the same distance with the same size -> share 0.5), and evaluate top-30 out-of-sample.

Usage: python src/audit/sim_lp_audit.py [tag]
"""
import os, sys, math, re, json, datetime as dt, collections
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../live"))
sys.path.insert(0, os.path.dirname(__file__))
import sim_lp as S
from hist_as_audit import TZ, MONTHS

DAILY = re.compile(r"(highest|lowest) temperature in")


def obs_start_live(q, end):
    """UTC ts of local midnight starting the observation date (temperature markets); for other dated markets use the
    earliest time zone (UTC+14) as a conservative start; nan if the question has no date."""
    md = re.search(r"on (" + "|".join(MONTHS) + r") (\d{1,2})", q)
    if not md: return np.nan
    y = dt.datetime.utcfromtimestamp(end).year if np.isfinite(end) else 2026
    d0 = dt.datetime(y, MONTHS[md.group(1)], int(md.group(2)), tzinfo=dt.timezone.utc).timestamp()
    mc = re.search(r"temperature in (.+?) (?:be|on|have)", q)
    off = TZ.get(mc.group(1), 14) if mc else 14
    return d0 - off * 3600


def records(snaps, cfg, d=0.01):
    out = []
    last_ts = {}
    for snap in snaps:
        ts = snap["ts"]
        for cid, bk in snap["books"].items():
            m = cfg.get(cid)
            if not m or (not bk.get("b") and not bk.get("a")): continue
            try: end = dt.datetime.fromisoformat(m["end"].replace(" ", "T").replace("+00", "+00:00")).timestamp()
            except Exception: continue
            v = (m["v"] or 4.5) / 100.0; mn = m["min"] or 20; n = mn
            bids = sorted(bk["b"], key=lambda x: -x[0]); asks = sorted(bk["a"], key=lambda x: x[0])
            abb = S.adj_levels(bids, mn, "b"); aba = S.adj_levels(asks, mn, "a")
            if abb is None and aba is None: continue
            one_sided = abb is None or aba is None
            if abb is None: abb = max(0.0, aba - 2 * v)
            if aba is None: aba = min(1.0, abb + 2 * v)
            m0 = (abb + aba) / 2; tk = S.tick_for(m0)
            our_b = max(abb, math.floor((m0 - d) / tk + 1e-9) * tk); our_a = min(aba, math.ceil((m0 + d) / tk - 1e-9) * tk)
            our_b = round(max(tk, our_b), 4); our_a = round(min(1 - tk, our_a), 4)
            if our_b >= our_a: continue
            m1 = (our_b + our_a) / 2
            sb = (m1 - our_b) * 100; sa = (our_a - m1) * 100; vv = v * 100
            if sb >= vv or sa >= vv: continue
            q_ours = min(S.S(vv, sb) * n, S.S(vv, sa) * n)
            q1 = sum(S.S(vv, (m1 - p) * 100) * s for p, s in bids if (m1 - p) * 100 < vv)
            q2 = sum(S.S(vv, (p - m1) * 100) * s for p, s in asks if (p - m1) * 100 < vv)
            qc = max(q1, q2)
            share = q_ours / (q_ours + qc) if q_ours > 0 else 0.0
            dt_min = 1.0 if cid not in last_ts else min(5.0, max(0.0, (ts - last_ts[cid]) / 60.0)); last_ts[cid] = ts
            q = m["q"] or ""
            obs = obs_start_live(q, end)
            out.append(dict(cid=cid, ts=ts, rate=m["rate"], share=share, dt=dt_min, rew=share * m["rate"] / 1440 * dt_min,
                            one_sided=one_sided, sole=qc <= 1e-9, adj_spread=aba - abb, m1=m1, hte=(end - ts) / 3600,
                            hobs=(obs - ts) / 3600 if np.isfinite(obs) else np.nan, daily_temp=bool(DAILY.search(q)),
                            dated=bool(re.search(r"on (" + "|".join(MONTHS) + r") \d", q)), cap=n * (our_b + 1 - our_a),
                            cap_inv=n * (min(our_b, 1 - our_b) + min(1 - our_a, our_a)), q=q[:70]))
    return pd.DataFrame(out)


def per_day(df, span_h):
    return df.groupby("cid").rew.sum() / span_h * 24


def top30(df, span_h, k=30):
    r = per_day(df, span_h).sort_values(ascending=False)
    top = r.index[:k]
    cap = df[df.cid.isin(top)].groupby("cid").cap.last().sum()
    return r.iloc[:k].sum(), cap, list(top)


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "weather"
    snaps, cfg, trades = S.load(tag)
    t0, t1 = snaps[0]["ts"], snaps[-1]["ts"]; span = (t1 - t0) / 3600
    print(f"snapshots={len(snaps)} span_h={span:.2f} ({dt.datetime.utcfromtimestamp(t0):%H:%M}-{dt.datetime.utcfromtimestamp(t1):%H:%M} UTC)")
    for d in [0.01, 0.02]:
        df = records(snaps, cfg, d=d)
        base = df[df.hte >= 12]
        tot, cap, top = top30(base, span)
        print(f"\n=== d={d}: REPRODUCTION (hte>=12, in-sample top-30): reward/day=${tot:.0f} capital=${cap:.0f}")
        T = base[base.cid.isin(top)]
        rtot = T.rew.sum()
        for flag, lab in [("one_sided", "B1 one-sided book, invented mid"), ("sole", "B2 sole scorer (no competitor within v)")]:
            print(f"   share of top-30 reward from {lab}: {T[T[flag]].rew.sum() / rtot:.0%}")
        inobs = T.hobs < 0
        print(f"   share of top-30 reward from B3 observation day already started: {T[inobs].rew.sum() / rtot:.0%}")
        print(f"   share of top-30 reward from B4 non-daily-temperature markets: {T[~T.daily_temp].rew.sum() / rtot:.0%}")
        print(f"   top-30 median share={T.groupby('cid').share.mean().median():.2f}, sum of pools=${T.groupby('cid').rate.last().sum():.0f}/day "
              f"-> claims {tot / T.groupby('cid').rate.last().sum():.0%} of those pools")
        # progressive corrections
        c1 = base[~base.one_sided]
        c2 = c1[c1.daily_temp & (c1.hobs >= 12)]
        c3 = c2.copy(); c3.loc[c3.sole, "share"] = 0.5; c3["rew"] = c3.share * c3.rate / 1440 * c3.dt
        for lab, x in [("drop one-sided books", c1), ("+ only daily-temperature, >=12h before LOCAL obs day", c2),
                       ("+ a rival farmer matches us when we'd be sole scorer (share<=0.5)", c3)]:
            a, b, _ = top30(x, span)
            print(f"   {lab:70s}: top-30 reward/day=${a:6.0f} capital=${b:5.0f}  (all eligible mkts: ${per_day(x, span).sum():.0f}/day, n={x.cid.nunique()})")
        # split-sample: select top-30 on first half, evaluate on second half
        mid_t = t0 + (t1 - t0) / 2
        for lab, x in [("reproduction universe", base), ("corrected universe c3", c3)]:
            A = x[x.ts < mid_t]; B = x[x.ts >= mid_t]
            ha = (mid_t - t0) / 3600; hb = (t1 - mid_t) / 3600
            ra, _, topA = top30(A, ha)
            rb_same = (B[B.cid.isin(topA)].groupby("cid").rew.sum() / hb * 24).sum()
            rb_best, _, _ = top30(B, hb)
            print(f"   split-sample [{lab}]: top-30 chosen on 1st half: in-sample ${ra:.0f}/day -> out-of-sample ${rb_same:.0f}/day "
                  f"(2nd-half in-sample best ${rb_best:.0f}/day)")
        # time-of-day profile of total competition (only meaningful with >= several hours of data)
        base = base.assign(hour=pd.to_datetime(base.ts, unit="s").dt.hour)
        prof = base[base.cid.isin(top)].groupby("hour").agg(share=("share", "mean"), n=("cid", "nunique"))
        print("   top-30 mean share by UTC hour:", {int(h): round(r.share, 2) for h, r in prof.iterrows()})
