"""Fetch NBM text (NBS) MOS archive from IEM for US resolution stations. Exact runtimes -> no look-ahead.
Columns kept: runtime, ftime, tmp (F, 3-hourly), txn (F; at 00Z ftime = daytime max), xnd (TXN std dev, F)."""
import os, sys, io, time
import pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from nethelp import get_text

D = "/home/user/polyall2/data/weather"
OUT = f"{D}/nbs"
os.makedirs(OUT, exist_ok=True)
US = ["KLGA", "KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KMIA", "KORD", "KSEA", "KSFO"]


def fetch(icao, start="2024-12-01", end="2026-09-27"):
    fp = f"{OUT}/{icao}.parquet"
    if os.path.exists(fp):
        return None
    frames = []
    cur = pd.Timestamp(start)
    e = pd.Timestamp(end)
    while cur < e:
        nxt = min(cur + pd.DateOffset(months=2), e)
        txt = get_text("https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py",
                       {"station": icao, "model": "NBS", "sts": cur.strftime("%Y-%m-%dT00:00Z"),
                        "ets": nxt.strftime("%Y-%m-%dT00:00Z"), "format": "csv"}, ns="iem_nbs", timeout=300)
        if txt:
            df = pd.read_csv(io.StringIO(txt), usecols=["runtime", "ftime", "tmp", "txn", "xnd"])
            frames.append(df)
        cur = nxt
        time.sleep(1)
    df = pd.concat(frames, ignore_index=True)
    df["runtime"] = pd.to_datetime(df.runtime, utc=True)
    df["ftime"] = pd.to_datetime(df.ftime, utc=True)
    df.to_parquet(fp, compression="zstd")
    return len(df)


if __name__ == "__main__":
    for s in US:
        try:
            print(s, fetch(s), flush=True)
        except Exception as ex:
            print(s, "ERR", ex, flush=True)
