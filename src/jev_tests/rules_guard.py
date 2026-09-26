"""Jev as a rules-verification guardrail. Given a weather market's rules text and the bot's ASSUMED spec
(station ICAO code + unit), Jev must confirm (true spec) or reject (deliberately wrong spec).
Ground truth: ICAO parsed by regex from resolution URLs in the rules."""
import os, sys, json, random, re, glob
import numpy as np
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.jev import decide, cost
ROOT = os.path.join(os.path.dirname(__file__), "../..")
rx = re.compile(r"(?:site=|/history/daily/[^\s]*?/)([A-Z]{4})\b")
cases = []
seen_ev = set()
for fn in sorted(glob.glob(f"{ROOT}/data/raw/markets/2026-0[6789]-*.jsonl")):
    for l in open(fn):
        m = json.loads(l)
        if m.get("feeType") != "weather_fees" or "temperature" not in m["question"].lower(): continue
        if m.get("eventId") in seen_ev: continue
        d = m.get("description") or ""
        mm = rx.search(d)
        if not mm: continue
        unit = "F" if "°F" in m["question"] else "C"
        seen_ev.add(m.get("eventId")); cases.append((m["question"], d, mm.group(1), unit))
random.seed(3); random.shuffle(cases); cases = cases[:300]
icaos = sorted(set(c[2] for c in cases))
tests = []
for i, (q, d, ic, u) in enumerate(cases):
    if i % 2 == 0: tests.append((q, d, ic, u, 1))
    else:
        wrong = random.choice([x for x in icaos if x != ic])
        tests.append((q, d, wrong, u, 0))
Q = {"match": {"type": "noul", "instructions": "Does the market's resolution rule use exactly the weather station identified by the given ICAO code (the bot's assumption)? Answer false if the rules point to a different station/airport.",
               "criteria": {"true": "The rules' resolution station is the assumed ICAO station.", "false": "The rules specify a different station than the assumed one."}}}
def run(t):
    q, d, ic, u, y = t
    st = {"market": q, "rules": d, "assumed_station_icao": ic, "assumed_unit": u}
    try: return (y, decide(st, Q)["match"]["noul"])
    except Exception as e: return (y, None)
with ThreadPoolExecutor(8) as ex:
    R = [r for r in ex.map(run, tests) if r[1] is not None]
y = np.array([r[0] for r in R]); p = np.array([r[1] for r in R])
from sklearn.metrics import roc_auc_score
print("n", len(R), "AUC", round(roc_auc_score(y, p), 4))
for th in [0.5, 0.8, 0.9]:
    fa = ((p >= th) & (y == 0)).sum() / max(1, (y == 0).sum()); fr = ((p < th) & (y == 1)).sum() / max(1, (y == 1).sum())
    print(f"threshold {th}: false-accept(wrong spec passed)={fa:.3f} false-reject(true spec blocked)={fr:.3f}")
print("cost", cost())
