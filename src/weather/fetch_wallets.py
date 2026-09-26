"""Fetch full trade history (maker+taker) for the wallets flagged by leaderboard forensics."""
import json, os, sys, time
import pandas as pd
import requests
from common import D

WALLETS = {"FuuUuUu": "0x2d44274747466c0936c3e01d5a5ad6c260d97023",
           "bhuumi": "0x937bcac3a8a30c07d827ad0550c3fe3a6756bfab",
           "wuxiuming": "0x919698b19427cbe6945b0dc823f2d9e126a4d934",
           "Weatherstappen": "0xb9012e0d9b60d3920286309328b935cdfa609fc4"}
OUT = f"{D}/wallets"
os.makedirs(OUT, exist_ok=True)


def fetch_user(w):
    s = requests.Session()
    allr = []; off = 0
    while True:
        for k in range(6):
            r = s.get("https://data-api.polymarket.com/trades", params=dict(user=w, limit=500, offset=off, takerOnly="false"), timeout=60)
            if r.status_code == 200:
                break
            time.sleep(2 ** k)
        if r.status_code != 200:
            print("stop", r.status_code, r.text[:200]); break
        j = r.json()
        if not j:
            break
        allr.extend(j); off += len(j)
        if len(j) < 500 or off > 200000:
            break
        time.sleep(0.2)
    return allr


if __name__ == "__main__":
    for name, w in WALLETS.items():
        rows = fetch_user(w)
        df = pd.DataFrame(rows)
        keep = [c for c in ["proxyWallet", "side", "asset", "conditionId", "size", "price", "timestamp", "title", "slug", "eventSlug",
                            "outcome", "outcomeIndex", "transactionHash"] if c in df]
        df = df[keep]
        df.to_parquet(f"{OUT}/{name}.parquet")
        print(name, len(df), pd.to_datetime(df.timestamp.min(), unit="s"), pd.to_datetime(df.timestamp.max(), unit="s"), flush=True)
