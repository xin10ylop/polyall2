"""Build tidy events / buckets tables for tweet-count markets.
events.parquet : one row per count event (acct, window start/end from xtracker tracking, fee rate, winner idx,...)
buckets.parquet: one row per bucket market (event_id, k, lo, hi, conditionId, yes/no token, won, closedTime, volume)
"""
import json, re, glob
import numpy as np, pandas as pd
from dateutil import parser as dparser

D = "/home/user/polyall2/data/tweets"
SERIES_ACCT = {"elon-tweets-48h": "elonmusk", "elon-tweets": "elonmusk", "elon-tweet-daily": "elonmusk",
               "trump-truth-social": "realDonaldTrump", "whitehouse-daily-tweets": "WhiteHouse",
               "khamenei-daily-tweets": "khamenei_ir", "ted-cruz-daily-tweets": "tedcruz",
               "zelenskyy-tweets": "ZelenskyyUa", "nycmayor-tweets": "NYCMayor", "cz-tweets": "cz_binance",
               "andrew-tate-tweets": "Cobratate"}

def parse_bucket(lbl):
    s = (lbl or "").replace("–", "-").replace(",", "").strip()
    m = re.fullmatch(r"<\s*(\d+)", s)
    if m: return 0, int(m.group(1)) - 1
    m = re.fullmatch(r"≤\s*(\d+)", s)
    if m: return 0, int(m.group(1))
    m = re.fullmatch(r"(\d+)\s*\+", s)
    if m: return int(m.group(1)), 10**9
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", s)
    if m: return int(m.group(1)), int(m.group(2))
    return None

from zoneinfo import ZoneInfo
NY = ZoneInfo("America/New_York")
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}

def _mk(mon, day, year, hm):
    mon = MONTHS[mon.lower()] if mon.lower() in MONTHS else MONTHS[[k for k in MONTHS if k.startswith(mon.lower()[:3])][0]]
    t = pd.Timestamp(f"{year}-{mon:02d}-{int(day):02d} {hm}")
    return t.tz_localize(NY).tz_convert("UTC")

def parse_window(desc, ev_end):
    """Window [start, end) in UTC from the rules text. Returns (start, end) or (None, None)."""
    d = (desc or "").replace("\n", " ")
    y_end = pd.Timestamp(ev_end).year if ev_end else None
    m = re.search(r"during the month of (\w+),? (\d{4})", d)
    if m:
        s = _mk(m.group(1), 1, int(m.group(2)), "00:00")
        e = (pd.Timestamp(s.tz_convert(NY).tz_localize(None)) + pd.offsets.MonthBegin(1)).tz_localize(NY).tz_convert("UTC")
        return s, e
    m = re.search(r"(?:from|between) (\w+) (\d+),? (?:(\d{4}),? )?(\d+:\d+ [AP]M) ET (?:to|and) (\w+) (\d+),? (?:(\d{4}),? )?(\d+:\d+ [AP]M) ET", d)
    if m:
        y2 = int(m.group(7)) if m.group(7) else y_end
        y1 = int(m.group(3)) if m.group(3) else y2
        hm1 = pd.Timestamp("2000-01-01 " + m.group(4)).strftime("%H:%M"); hm2 = pd.Timestamp("2000-01-01 " + m.group(8)).strftime("%H:%M")
        s = _mk(m.group(1), m.group(2), y1, hm1); e = _mk(m.group(5), m.group(6), y2, hm2)
        if s > e: s = _mk(m.group(1), m.group(2), y1 - 1, hm1)
        return s, e
    return None, None

def load_trackings():
    tr = []
    for fn in glob.glob(f"{D}/xt/trackings_*.json"):
        if re.search(r"trackings_\d{8}T", fn): continue
        h = fn.split("trackings_")[1][:-5]
        for t in json.load(open(fn)):
            t["handle"] = h; tr.append(t)
    return pd.DataFrame(tr)

def main():
    evs = [json.loads(l) for l in open(f"{D}/gamma/events_closed.jsonl")] + \
          [json.loads(l) for l in open(f"{D}/gamma/events_open.jsonl")]
    tr = load_trackings()
    tr["slug"] = tr.marketLink.fillna("").str.rstrip("/").str.split("/").str[-1]
    tr["startDate"] = pd.to_datetime(tr.startDate, utc=True); tr["endDate"] = pd.to_datetime(tr.endDate, utc=True)
    E, B = [], []
    for e in evs:
        acct = SERIES_ACCT.get(e.get("seriesSlug") or "")
        if acct is None: continue
        mk = []
        for m in e["markets"]:
            pb = parse_bucket(m.get("groupItemTitle"))
            if pb is None: mk = None; break
            mk.append((pb, m))
        if not mk: continue
        mk.sort(key=lambda x: x[0][0])
        # window: tracking by slug, else by (handle,title), else description
        t = tr[(tr.slug == e["slug"]) & (tr.handle == acct)]
        src = "slug"
        if t.empty:
            t = tr[(tr.handle == acct) & (tr.title.str.strip() == e["title"].strip())]; src = "title"
        if t.empty and e.get("endDate"):
            ee = pd.Timestamp(e["endDate"])
            c = tr[(tr.handle == acct) & ((tr.endDate - ee).abs() < pd.Timedelta("2h"))].copy()
            if not c.empty:
                tw = set(re.findall(r"[a-z0-9]+", e["title"].lower()))
                c["sc"] = c.title.map(lambda x: len(tw & set(re.findall(r"[a-z0-9]+", x.lower()))))
                # duration must agree with the title type (month vs 48h vs week)
                c["dur"] = (c.endDate - c.startDate).dt.total_seconds() / 3600
                t = c.sort_values("sc").iloc[[-1]]; src = "fuzzy"
        if len(t) > 1:
            t = t.sort_values("updatedAt").iloc[[-1]]
        if t.empty:
            ws = we = None; src = "none"; tid = None
        else:
            ws, we, tid = t.startDate.iloc[0], t.endDate.iloc[0], t.id.iloc[0]
        ds, de = parse_window(mk[0][1].get("description") or e.get("description"), e.get("endDate"))
        prices = [json.loads(m["outcomePrices"]) if m.get("outcomePrices") else None for _, m in mk]
        won = [p is not None and p[0] == "1" for p in prices]
        resolved = all(m.get("umaResolutionStatus") == "resolved" for _, m in mk) and sum(won) == 1
        fs = mk[0][1].get("feeSchedule") or {}
        E.append(dict(event_id=e["id"], slug=e["slug"], title=e["title"], acct=acct, series=e.get("seriesSlug"),
                      closed=bool(e.get("closed")), resolved=resolved, win_k=(won.index(True) if resolved else -1),
                      nb=len(mk), ws=ws, we=we, win_src=src, ds=ds, de=de, tracking_id=tid,
                      ev_start=e.get("startDate"), ev_end=e.get("endDate"), created=e.get("createdAt"),
                      fee_rate=float(fs.get("rate", 0) or 0), fee_type=mk[0][1].get("feeType"),
                      volume=float(e.get("volume") or 0), neg_risk=bool(e.get("negRisk"))))
        for k, ((lo, hi), m) in enumerate(mk):
            toks = json.loads(m["clobTokenIds"]) if m.get("clobTokenIds") else [None, None]
            B.append(dict(event_id=e["id"], k=k, label=m["groupItemTitle"], lo=lo, hi=hi,
                          conditionId=m["conditionId"], yes_tok=toks[0], no_tok=toks[1], won=won[k],
                          closedTime=m.get("closedTime"), volume=float(m.get("volume") or 0),
                          created=m.get("createdAt"), accepting_ts=m.get("acceptingOrdersTimestamp"),
                          tick=m.get("orderPriceMinTickSize"),
                          fee_rate=float((m.get("feeSchedule") or {}).get("rate", 0) or 0)))
    E = pd.DataFrame(E); B = pd.DataFrame(B)
    # canonical window = rules text; tracking window kept as cross-check
    E["tw_start"], E["tw_end"] = E.ws, E.we
    E["start"] = E.ds.where(E.ds.notna(), E.ws); E["end"] = E.de.where(E.de.notna(), E.we)
    E["tw_mismatch_min"] = ((E.tw_start - E.start).dt.total_seconds().abs() / 60).round(1)
    for c in ["ev_start", "ev_end", "created"]:
        E[c] = pd.to_datetime(E[c], utc=True, format="ISO8601")
    for c in ["closedTime", "created", "accepting_ts"]:
        B[c] = pd.to_datetime(B[c].str.replace(" ", "T").str.replace(r"\+00$", "+00:00", regex=True), utc=True, format="ISO8601", errors="coerce")
    E.to_parquet(f"{D}/events.parquet"); B.to_parquet(f"{D}/buckets.parquet")
    print(E.groupby(["acct", "win_src"]).size().unstack(fill_value=0))
    print(E[E.start.isna()][["title", "ev_end"]].to_string())
    print(E[E.tw_mismatch_min > 5][["title", "start", "end", "tw_start", "tw_end"]].to_string())
    print("resolved", E.resolved.sum(), "of", len(E), "closed", E.closed.sum())

if __name__ == "__main__":
    main()
