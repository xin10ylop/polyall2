"""METAR receipt times at aviationweather.gov (AWC) for the last ~15 days (API limit), all resolution stations.
receiptTime - obsTime = publication delay on the AWC feed."""
import json, time
import pandas as pd
import requests
from common import D

S = pd.read_csv(f"{D}/stations.csv")
ids = [i for i in S.icao if len(i) == 4]
rows = []
for k in range(0, len(ids), 1):
    chunk = ids[k:k + 1]
    for t in range(5):
        r = requests.get("https://aviationweather.gov/api/data/metar", params=dict(ids=",".join(chunk), format="json", hours=360), timeout=120)
        if r.status_code == 200:
            break
        time.sleep(2 ** t)
    try:
        js = r.json() if r.status_code == 200 and r.text.strip() else []
    except ValueError:
        js = []
    for x in js:
        rows.append(dict(icao=x["icaoId"], obs=pd.Timestamp(x["obsTime"], unit="s", tz="UTC"), receipt=pd.Timestamp(x["receiptTime"]),
                         temp=x.get("temp"), type=x.get("metarType"), raw=x.get("rawOb")))
    time.sleep(1)
R = pd.DataFrame(rows)
R["delay_s"] = (R.receipt - R.obs).dt.total_seconds()
R.to_parquet(f"{D}/metar_receipts.parquet")
print(R.shape, R.obs.min(), R.obs.max())
print(R.groupby("icao").delay_s.median().describe())
print(R.delay_s.quantile([.05, .1, .25, .5, .75, .9, .95]))
