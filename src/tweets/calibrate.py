"""Calibrate model hyperparameters on synthetic decision points (no markets needed).
For each account, decision times t every 3h, horizons H hours. Record mu(t,h; hl) and actual final count.
Fit NB alpha per (acct, horizon-bin, hl) by ML on the TRAIN period (t+h < CUTOFF) and pick hl per
(acct-group, horizon-bin). Saves data/tweets/calib_points.parquet and model_params.json.
Evaluates OOS (t >= CUTOFF) log score / PIT coverage."""
import json, sys, numpy as np, pandas as pd
from scipy import optimize
from common import D, ACCTS, posts
from model import Acct, nb_logpmf, hbin, HBINS

CUTOFF = pd.Timestamp("2026-06-01", tz="UTC").value // 10**9
HLS = [0.25, 0.5, 1, 2, 4, 7, 14]
HORIZ = [1, 2, 3, 4, 6, 9, 12, 18, 24, 36, 48, 72, 96, 120, 144, 168, 240, 336, 504, 720]
TRACK_START = {"elonmusk": "2025-11-18", "realDonaldTrump": "2026-01-21", "WhiteHouse": "2026-01-15",
               "tedcruz": "2026-03-12", "khamenei_ir": "2026-03-12", "ZelenskyyUa": "2026-03-16",
               "NYCMayor": "2026-03-16", "cz_binance": "2026-03-16", "Cobratate": "2026-02-04"}
NOW = pd.Timestamp("2026-09-26 12:00", tz="UTC").value // 10**9

def points(h, strict=True, step_h=3):
    a = Acct(h, strict)
    t0 = pd.Timestamp(TRACK_START[h], tz="UTC").value // 10**9 + 28 * 86400
    ts = np.arange((t0 // 3600 + 1) * 3600, NOW - 3600, step_h * 3600)
    rows = []
    for t in ts:
        st = {hl: a.state(t, hl) for hl in HLS}
        for H in HORIZ:
            e = t + H * 3600
            if e > NOW: continue
            n = a.final_count(t, e)
            r = dict(acct=h, t=t, H=H, n=n)
            for hl in HLS:
                R, prof = st[hl]
                r[f"mu_{hl}"] = a.expected(t, e, R, prof)
            rows.append(r)
    return pd.DataFrame(rows)

def fit_alpha(n, mu):
    f = lambda la: -nb_logpmf(n, mu, np.exp(la)).sum()
    res = optimize.minimize_scalar(f, bounds=(-9, 3), method="bounded")
    return float(np.exp(res.x)), -res.fun

if __name__ == "__main__":
    import model
    strict = "loose" not in sys.argv[1:]
    if "nodow" in sys.argv[1:]: model.DOW = False
    tag = ("" if strict else "_loose") + ("_nodow" if not model.DOW else "")
    P = pd.concat([points(h, strict) for h in ACCTS if h != "Cobratate"], ignore_index=True)
    P["hb"] = hbin(P.H.values)
    P["train"] = (P.t + P.H * 3600) < CUTOFF
    P.to_parquet(f"{D}/calib_points{tag}.parquet")
    print(P.groupby(["acct", "train"]).size().unstack())
