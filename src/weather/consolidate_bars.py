"""Merge per-event trade bar files into one parquet (much smaller on disk)."""
import os, glob
import pandas as pd
from common import D

fs = glob.glob(f"{D}/trade_bars/*.parquet")
parts = []
for f in fs:
    b = pd.read_parquet(f)
    if len(b):
        b.insert(0, "event_id", os.path.basename(f)[:-8])
        parts.append(b)
X = pd.concat(parts, ignore_index=True)
X["event_id"] = X.event_id.astype("category")
X.to_parquet(f"{D}/trade_bars_all.parquet", compression="zstd")
print(X.shape, os.path.getsize(f"{D}/trade_bars_all.parquet") / 1e6, "MB")
