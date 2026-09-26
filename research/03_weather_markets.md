# 03 — Polymarket weather markets: is there an executable forecast edge?

Status: IN PROGRESS (written incrementally). Date of study: 2026-09-26.
Code: `src/weather/`. Raw/cached data: `data/weather/` (not committed).

---

## 1. Market discovery (gamma-api)

Method: `GET https://gamma-api.polymarket.com/events/keyset?tag_slug=weather&closed={true,false}&limit=100&after_cursor=...`
(the plain `/events` endpoint refuses offsets > ~2,100, keyset pagination is required). Result: **14,718 events**
under the `weather` tag (386 open, 14,332 closed). Script: `src/weather/discover.py`, flattened into
`data/weather/{events,markets}.parquet` by `build_markets_table.py`.

### 1.1 What exists

| Family | Events | Notes |
|---|---|---|
| "Highest temperature in <city> on <date>?" | 11,074 | the dominant product; ~$880M gamma volume lifetime |
| "Lowest temperature in <city> on <date>?" | 2,897 | 8 cities since 2026-04, ~46 cities since 2026-08-21; ~10x smaller per event |
| Monthly global temp anomaly (GISTEMP), hottest-year, "hottest on record" | ~40 | $1–8M each, monthly/annual resolution |
| Monthly precipitation NYC/Seattle, snow, hurricanes, tornado counts, earthquakes etc. | ~200 | small N, not suitable for a statistical backtest |

Daily temperature markets by month (gamma `volume`, which counts both sides; taker notional from data-api is ~0.6x):

| Month | highest: $ vol | # events | lowest: $ vol | # events |
|---|---|---|---|---|
| 2025-01..2025-10 | 1–9.5M / month | ~60 / month (NYC + London only) | – | – |
| 2025-11 | 18.3M | 60 | – | – |
| 2025-12 | 19.6M | 232 | – | – |
| 2026-01 | 27.1M | 287 | – | – |
| 2026-02 | 52.0M | 366 | – | – |
| 2026-03 | 44.2M | 388 | – | – |
| 2026-04 | 180.6M | 1,426 | 3.0M | 74 |
| 2026-05 | 122.8M | 1,599 | 5.6M | 221 |
| 2026-06 | 120.5M | 1,452 | 7.3M | 241 |
| 2026-07 | 121.1M | 1,517 | 7.9M | 248 |
| 2026-08 | 92.6M | 1,569 | 7.1M | 721 |
| 2026-09 (to 26th) | 62.2M | 1,421 | 4.8M | 1,369 |

Cities with "highest temperature" markets (57 slugs; ~50 active daily): London, NYC (since 2025-01), Seoul, Atlanta,
Dallas, Toronto, Seattle, Buenos Aires, Miami, Chicago, LA, Denver (since 2025-12), Wellington, Ankara (2026-01),
Paris, Sao Paulo (2026-02), Munich, Lucknow, Tokyo, Tel Aviv, Hong Kong, Shanghai, Singapore, Madrid, Milan, Warsaw,
Taipei, Beijing, Shenzhen, Wuhan, Chengdu, Chongqing, Austin, Houston, San Francisco, Moscow, Istanbul, Mexico City,
Amsterdam, Helsinki, Busan, Kuala Lumpur, Panama City, Jakarta (ended 2026-05), Cape Town, Jeddah, Lagos (ended 2026-05),
Guangzhou, Manila, Karachi, Qingdao, Jinan, Zhengzhou.
Median event volume: $30k (Panama City) – $224k (Hong Kong); London $116k, NYC $95k, Seoul $175k.

### 1.2 Contract structure

* One neg-risk event per city-day with **11 mutually exclusive buckets** (7 or 9 in older events):
  * US cities, °F: two tails + nine **2°F buckets**, e.g. NYC 2026-09-25: `57°F or below`, `58-59°F`, …, `74-75°F`, `76°F or higher`.
  * All others, °C: two tails + nine **1°C buckets** (e.g. `21°C`, `22°C`, … `≤17°C`, `≥27°C`).
  * London was quoted in °F until 2025-12-10 and in °C since.
* Resolution = the **maximum of the whole-degree reported temperatures** during the local calendar day at one specific
  station (almost always an airport METAR station):
  * until 2026-08-22/23: Weather Underground daily history page for the station (e.g. `wunderground.com/history/daily/us/ny/new-york-city/KLGA`);
  * since 2026-08-23/24: NOAA `weather.gov/wrh/timeseries?site=<ICAO>` ("Show Hourly Data", highest value in the Temp column),
    with Weather Underground as fallback;
  * Hong Kong: Hong Kong Observatory HQ daily max (not the airport); Taipei: CWA station 466920 for a week, then RCTP, then RCSS (Songshan);
    Paris switched from LFPG (CDG) to LFPB (Le Bourget) on 2026-04-19; Denver = KBKF (Buckley SFB, not KDEN); Dallas = KDAL (Love Field);
    Houston = KHOU (Hobby); London = EGLC (London City); Seoul = RKSI (Incheon); Karachi = OPKC; Moscow = UUWW (Vnukovo).
  * Revisions after the first data point of the following day are ignored; "clearly erroneous" data can delay resolution by up to 7 days.
* Station table with coordinates (aviationweather.gov): `data/weather/stations.csv`; per-event station: `data/weather/event_station.parquet`.
* Timing: events are created **~55 h before `endDate`** (endDate = 12:00 UTC of the target day), i.e. about 2 days ahead
  (e.g. NYC 2026-09-25 created 2026-09-23 06:56 UTC). Earlier (2025) ~43–50 h. Markets are resolved (UMA) a median
  **~10–12 h after endDate** in 2026 (i.e. the morning after the local day ends).
* Tick size 0.001 (a few 0.01), minimum order 5 shares.
* **Fees**: since ~2026-03-30 all weather markets have `feesEnabled=true`, `feeType=weather_fees`,
  `feeSchedule={rate:0.05, exponent:1, takerOnly:true, rebateRate:0.25}`. Per Polymarket docs, taker fee
  = `C x 0.05 x p x (1-p)` USDC (C = shares, p = price); makers pay nothing and receive a 25% rebate pool.
  E.g. buying at 20c costs 0.8c/share = 4% of notional; at 50c 1.25c/share = 2.5%; at 90c 0.45c = 0.5%.
  Markets ending before 2026-03-30 had no fees.

## 2. Data collected

| Data | Source | Coverage | Script |
|---|---|---|---|
| Event/market metadata, bucket bounds, winners, fees | gamma-api keyset | 14,718 weather events; 13,971 temperature events (11,074 highest / 2,897 lowest) | `discover.py`, `slim.py`, `build_markets_table.py`, `build_events.py` |
| Executed trades | `data-api.polymarket.com/trades?eventId=<id>&limit=10000` (taker-side prints, incl. both YES and NO tokens) | every closed temperature event since 2025-01 (~2,000 taker prints per event; 1 call/event, per-market fallback if 10k cap hit) | `fetch_trades.py` |
| Price history (cross-check) | `clob.polymarket.com/prices-history?market=<token>&startTs&endTs&fidelity=1` | works for closed markets (1-min fidelity); used only to validate the trade-derived prices | ad hoc |
| Observations | IEM ASOS/METAR archive (`mesonet.agron.iastate.edu/cgi-bin/request/asos.py`, routine + specials) | 2024-12 → 2026-09-26, every resolution station | `fetch_obs.py`, `obs.py` |
| NBM MOS (US) | IEM MOS archive, model `NBS` (NBM text: 3-hourly T, TXN daytime max + XND spread), exact run times 01/07/13/19Z | 11 US stations, 2024-12 → 2026-09 | `fetch_nbs.py` |
| Open-Meteo Previous Runs (`temperature_2m_previous_dayN`, ECMWF IFS/GFS/ICON/best_match) | previous-runs-api.open-meteo.com | **only KLGA** was obtained before the shared-IP daily quota was exhausted (HTTP 429 "Daily API request limit exceeded"); the main forecast API does not serve previous_dayN history | `fetch_forecasts.py` |
| ECMWF IFS HRES open data, `mx2t3` (3-h max 2 m T), 0.25° | AWS `ecmwf-forecasts` bucket, byte-range GRIB2 of one field per step, decoded with pygrib, bilinear to station | runs 00Z/12Z, steps 3–57 h, 2026-02-15 → 2026-09-26, all stations | `fetch_ecmwf.py`, `ecmwf_features.py` |
| Live order books | `POST clob.polymarket.com/books` | snapshots of all ~3,200 open temperature buckets (2026-09-26) | `live_books.py`, `analyze_books.py` |

Trades are stored as 10-minute **YES-equivalent** bars per bucket (`trade_bars/`): a taker BUY of YES at p and a taker SELL of NO
at 1-p are both "lifts of the YES ask at p"; a taker SELL of YES at p / BUY of NO at 1-p are "hits of the YES bid at p".
Per bar: VWAP, min, max, shares, #prints, #distinct wallets. Trade-derived last prices match CLOB `prices-history` to ~1c
(checked on NYC 2026-09-24 at three decision times).

### 2.1 How deterministic is the resolution? (METAR vs winning bucket)

The daily max of the whole-degree METAR temperatures (routine + special reports, station local calendar day; for °F
stations IEM `tmpf` rounded half-up, for °C stations the METAR integer °C) falls inside the winning bucket in
**99.6–99.8 % of resolved events** (WU-era and NOAA-era alike; `check_resolution.py`, `data/weather/resolution_check.parquet`).
The rare misses are 1-degree boundary cases (late corrections, 5-min data, or the "max at 23:5x" edge). Consequences:
* the outcome is effectively a public, real-time observable: once the day's peak has passed the answer is known from
  METARs (published every 30–60 min) hours before resolution;
* model training can use METAR daily max as the target with negligible label noise.

