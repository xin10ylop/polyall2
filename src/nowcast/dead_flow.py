"""How much taker flow hits NO-bids on DETERMINISTICALLY dead weather buckets (after the as-of METAR running max
has passed the bucket)? A resting NO bid at price b is GUARANTEED filled by any later taker print that acquires YES
at a YES price > 1-b (trade-through). Measures fillable shares/$ and profit at b in {0.97,0.98,0.99,0.995}."""
import os, sys, json, re, glob, datetime as dt
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
import rise_model as RM
from bt_nowcast import parse_bucket, MON, rx   # reuse parsers (module runs a backtest on import otherwise)
