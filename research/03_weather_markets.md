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

Station-level exceptions matter for any observation-based strategy (`resolution_check.parquet`, walk-forward station
filter in `dead_sim.py`): Shenzhen ZGSZ in the WU era matched only 24 % (the WU page evidently used a different
sensor/station), Seoul RKSI 88.5 % (WU), Moscow UUWW 94 % (NOAA era, resolution 1 °C above METAR in 11 cases),
Taipei RCTP 50 % (short period), Panama MPMG 91 % (NOAA era). Everywhere else ≥ 97–100 %.

## 3. Liquidity, volume timing and live order books

* ~51 "highest temperature" events per day (Aug–Sep 2026), gamma volume ≈ **$2.6M/day** across all cities
  (≈ $1.5M/day taker notional; data-api taker notional ≈ 0.6 x gamma `volume`). Median event: $30–220k gamma volume.
* Timing of trading (share of YES-equivalent notional by hour relative to local midnight of the target day, 3,000
  events since May 2026): D-2/D-1 before noon 5 %, D-1 afternoon/evening 18 %, D0 00–11 h 16 %,
  **D0 11–18 h 45 %**, D0 18–24 h 14 %, after midnight 2 %. The bulk of the money trades on the target day while the
  temperature is being observed.
* Live books (snapshot 2026-09-26 14:11 and 18:02 UTC, 3,100–3,200 open buckets, `live_books/`): for tomorrow /
  the day after, the typical bucket in the 20–50 % range is quoted **2 c wide** with ~$80–110 within 1 c of the best
  ask and $170–260 within 3 c; a $200 market buy moves the average fill by ~2–4 c. Buckets < 5 % have $4–10 at the
  best ask (a $200 sweep would pay 10–14 c for a 1–3 c contract). On the target day (D0) spreads widen to 3–9 c and
  depth collapses to ~$5–25 within 3 c for live buckets; buckets that are effectively decided (YES > 95 % or NO > 99 %)
  hold $500–800 at 0.99–0.999. Sum of best asks over an event: 1.11 (median) one day ahead, 1.41 two days ahead,
  i.e. buying the whole ladder costs 11–41 % over par; sum of best bids 0.97 / 0.91.
* Practical consequence: realistic clip sizes are **$20–200 per bucket per decision**, and a strategy that needs to
  cross the spread pays 1–2 c (D-1) to 2–5 c (D0) plus the taker fee.

## 4. Same-day observation strategy ("dead buckets")

### 4.1 Mechanism and what the flagged wallets do

Once a METAR reports a temperature T at the resolution station, every bucket whose upper bound is < T is dead
(NO wins with certainty up to the ~0.2–0.4 % METAR/resolution mismatch rate), and the top tail ("X or higher") is
decided YES once T ≥ X. `wallet_analysis.py` joins the fills of the four wallets flagged by leaderboard forensics
(data-api `/trades?user=`; the API returns only the latest 10,000 fills per wallet, i.e. May–Sep 2026) with the
METAR state at fill time (`wallet_fills.parquet`). Maker/taker is identified by matching the fill against the
event's taker-only prints.

| Wallet | fills (period) | buys on buckets already dead per METAR | median seconds after the killing METAR's obs time (taker buys) | typical price | taker share |
|---|---|---|---|---|---|
| Weatherstappen | 10,358 (May 13 – Sep 26) | 75 % of buys, 92 % of buy $ | **70 s** (q10 38 s, q90 166 s) | NO 0.985–0.99, exits at 0.999 | 25 % of dead buys (rest are resting NO bids at 0.99 that get hit) |
| bhuumi | 10,327 (May 8 – Sep 25) | 73 % of buys (74 % of $) | 222 s (q10 58 s) | NO 0.99 | 50 % |
| FuuUuUu | 761 (Apr 26 – Sep 26) | 18 % of buys (30 % of $) | 154 s | NO 0.98–0.99 | 39 % |
| wuxiuming | 10,061 (Jun 16 – Sep 23) | 11 % (37 % of $) | 55 s | NO 0.98–0.99 | 34 % |

So the core business of two of them is exactly the deterministic dead-bucket trade, executed **~40–200 s after the
observation time**, both by taking and by resting 0.99 NO bids. Their "alive" trades are different:
FuuUuUu and Weatherstappen mostly buy YES on the bucket that currently contains the running max (gap 0) at
0.70–0.87 (hold-to-resolution PnL +11–15 % per $ on those), wuxiuming buys YES longshots one degree above the running
max at ~0.14 (win 36 %, +9 % per $). bhuumi's non-dead trades are ~break-even.

### 4.2 Backtest with exact prints (all "highest" events May 1 – Sep 25 2026)

Setup (`deadbucket.py`, `dead_latency.py`, `dead_sim.py`): 7,407 events with METARs; 40,228 strict dead-bucket
events (bucket upper bound < running max; 0.14 % of them nevertheless resolved YES), 34,151 with a 1-degree margin
(0.04 % resolved YES), 378 top-tail hits (98.9 % resolved YES). Taker prints (exact second, 2.3M on the relevant
buckets) are expressed relative to the **observation time `valid` of the METAR that killed the bucket**. A NO fill
is any taker purchase of NO or taker sale of YES (NO price = 1 − YES price). The simulation enters at
`valid + delay` and takes, within the next 10 minutes, every print at or below a limit price, capped at **50 % of
the printed shares** (we compete with whoever printed), pays the 5 % × p(1−p) taker fee, holds to resolution.

Executable NO prints on strict dead buckets, by seconds after the killing METAR's observation time:

| window after obs time | deaths with any NO print | deaths with a NO print ≤ 0.99 | median NO print | edge $ available (≤ 0.99) |
|---|---|---|---|---|
| −10 … −2 min | 25 % | 18 % | 0.950 | $140k |
| −60 … 0 s | 13 % | 9.5 % | 0.970 | $54k |
| 0 – 15 s | 8.1 % | 5.2 % | 0.987 | $28k |
| 15 – 60 s (sum of three 15-s bins) | 28 % | 15 % | 0.990 | $102k |
| 60 – 90 s | 19 % | 8.4 % | 0.997 | $89k |
| 90 – 120 s | 11 % | 3.6 % | 0.998 | $28k |
| 2 – 5 min (sum of bins) | 45 % | 9.2 % | 0.999 | $105k |
| 5 – 10 min | 29 % | 2.5 % | 0.999 | $24k |
| 10 – 60 min (sum of bins) | 33 % | 3.3 % | 0.999 | $62k |

(US ASOS stations reach a median NO print of 0.999 after ~2 min; non-US stations after ~90 s.)
**The market reprices dead buckets within 1–2 minutes of the observation time; after ~2 minutes cheap NO liquidity
is rare and what remains is disproportionately the station-mismatch cases.**

Relative to the METAR **receipt time at aviationweather.gov** (AWC `receiptTime`, available for the last 15 days
only: 2,832 deaths, receipt delay median 274 s after obs time, q10 85 s): the median NO print is already 0.998 at
receipt; only 1.4 % of deaths have any print ≤ 0.99 in the first 10 s after AWC receipt ($449 of edge in 15 days),
0.5 % per 10-s bin thereafter. **A bot fed by the public AWC/NWS feed is too late; the winners have feeds that are
~1–4 minutes faster (1-/5-minute ASOS, national met-service feeds, direct METAR distribution).**

Strategy PnL (limit 0.98, 10-minute window, 50 % of prints, fees included; "reliable" = station's walk-forward
METAR-vs-resolution match rate ≥ 99 % in prior months):

| delay after obs time | stations | trades | staked | PnL | ROI | losing trades | worst trade | $/day staked | PnL/day | % days positive |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 s | all | 6,905 | $1.77M | $147k | 8.3 % | 48 | −$3,034 | $12.0k | $996 | 98.6 % |
| 60 s | all | 4,456 | $1.13M | $92k | 8.1 % | 48 | −$2,521 | $7.7k | $623 | 97 % |
| 60 s | reliable | 3,389 | $0.87M | $80k | 9.2 % | 6 | −$1,193 | $5.9k | $541 | 99 % |
| 120 s | reliable | 1,604 | $0.40M | $37k | 9.2 % | 5 | −$1,190 | $2.7k | $249 | 99 % |
| 300 s | reliable | 281 | $68k | $5.7k | 8.4 % | 2 | −$245 | $456 | $38 | 99 % |
| 300 s | all | 625 | $128k | $3.8k | 3.0 % | 43 | −$808 | $862 | $26 | 81 % |
| 600 s | all | 359 | $55k | −$1.7k | −3.0 % | 43 | −$1,512 | $374 | −$11 | 78 % |
| 30 min | all | 185 | $22k | −$4.0k | −18 % | 39 | −$2,906 | $147 | −$27 | 70 % |

Same with a 1-degree safety margin (bucket upper bound ≤ running max − 2): at 60 s, reliable stations: 355 trades,
$75k staked, +$5.3k (7.0 %), 2 losers; top-tail YES at 60 s, reliable: 83 trades, $29k, +$4.4k (15 %), 0 losers.
By month (60 s, reliable): ROI 10.6 % (May), 9.7 %, 8.6 %, 9.4 %, 6.7 % (Sep) — decaying as competition grows.
Average fill 0.96 (q10 0.87); these fills are mostly buckets that died "unexpectedly" (the prior YES price was
still meaningful), i.e. the liquidity exists precisely when the market was surprised.

Caveats / assumptions: (1) 50 % of printed shares assumes we win half the race against the fastest takers; the
wallets above show the race is run in tens of seconds, so a 0–60 s delay is only achievable with a sub-minute data
feed; (2) station mismatch risk is fat-tailed (a single bad day at Seoul/Shenzhen cost more than a week of gains
before the filter); (3) the resolution source switched from WU to NOAA on 2026-08-23, which changed several
stations' mismatch behaviour; (4) the 0.14 % "dead but resolved YES" cases are real losses (included).

### 4.3 Is it a race won in seconds, or do prices lag 10–60 minutes?

It is a race won in **tens of seconds to ~2 minutes after the observation time**, i.e. before the public
aviationweather.gov feed even shows the METAR (median receipt 274 s after obs time). Evidence: (i) the median
executable NO print on a strict dead bucket is 0.987 in the first 15 s, 0.997 at 60–90 s and 0.999 from 2 min on;
(ii) the professional wallets take at a median 55–70 s (Weatherstappen, wuxiuming) and post resting 0.99 NO bids;
(iii) relative to AWC receipt, only 1.4 % of deaths still offer any NO ≤ 0.99 in the first 10 s. Prices do *not*
lag 10–60 minutes in general: after 5 minutes, only ~2 % of deaths still show a NO print ≤ 0.99 per 5-minute bin,
and buying those loses money (−3 % to −18 % ROI at 10–30 min delay) because they are dominated by cases where the
METAR disagrees with the resolution source (the market knows the station quirks). With a 1-degree margin
(no mismatch exposure) the late residual is profitable but tiny (tens of $ per day).

**Capacity** of the deterministic trade across all ~51 cities: with a sub-minute feed ≈ $6–9k/day deployed at an
average fill of ~0.96 → ~$550–850/day theoretical (50 %-of-prints assumption); the realised scale of the leading
wallet is $4.0k/day at 4.1 % hold-to-resolution PnL/$ ≈ **$170/day**; bhuumi $3.9k/day at 2.6 % ≈ $100/day.
With a 2–5 minute feed (public API polling) the opportunity shrinks to ≈ $0.5–0.9k/day staked and **$25–40/day**.
ROI per trade decays month by month (10.6 % → 6.7 % May → Sep). Capital turns over daily (positions can be exited
at 0.998–0.999 within minutes, as the wallets do), so capital needs ≈ one day's stake.

## 5. Forecast model (pre-peak): D-1 12:00 and D0 07:00 local

Model (`wf_model.prepeak`, `prepeak_eval.py`): sources available at the decision time only — ECMWF IFS HRES
daily max of `mx2t3` at the station (latest run with run+8 h ≤ τ, bilinear from 0.25°), NBM TXN for US stations
(latest NBS run with run+2 h ≤ τ), Open-Meteo previous-day runs for NYC; each bias-corrected with the station's
rolling 60-day mean error (strictly before the day, 1–2 day gap), averaged; Student-t(5) error with rolling
per-station scale. Bucket probability = t-mass on the integer interval (±0.5). Walk-forward throughout; stacked
version = monthly expanding logistic regression of the outcome on logit(market last price) and logit(model),
fit only on earlier months.

Point skill (Mar 15 – Sep 25): MAE 1.16 °C / 1.97 °F at D-1 12:00; 1.03 °C / 1.72 °F at D0 07:00 (NBM alone at
KLGA: 2.1 °F). Probabilistic skill vs the market (bucket-level log loss, lower is better; 9,000+ events):

| decision | market last price | model | market recalibrated | market + model stacked |
|---|---|---|---|---|
| D-1 12:00 | **0.2197** | 0.2519 | 0.2198 | 0.2203 |
| D0 07:00 | **0.2240** | 0.2673 | 0.2243 | 0.2245 |

Event-level multinomial log loss for the 9 US cities with NBM (2,475 events): market 1.26 vs model 1.48 (D-1),
1.13 vs 1.40 (D0 07h). **The market is materially sharper than a bias-corrected ECMWF/NBM model, and adding the
model to the market does not improve out-of-sample log loss.** Month by month, the stacked model beat the market
only in Dec 2025 – Mar 2026 (fewer cities, thinner books); from April 2026 (launch of ~40 new cities) onward the
market is at least as good in every month.

Backtest (buy YES or NO when edge vs estimated ask > threshold; fills at the VWAP of actual taker prints on that
side within 30 min after the decision, ≤ 50 % of printed size, fee included; one entry per bucket/side):

| strategy | stake cap | trades | hit | avg price | staked | PnL | ROI | max DD | t |
|---|---|---|---|---|---|---|---|---|---|
| raw model, thr 5 c (Dec–Sep) | $20 | 18,715 | 46.6 % | 0.473 | $134k | −$3.0k | −2.3 % | $3.7k | −2.0 |
| raw model, thr 5 c, Jul–Sep holdout | $20 | 8,371 | 46.4 % | 0.473 | $64k | −$1.8k | −2.8 % | $2.6k | −1.6 |
| raw model, $5 / $100 caps (all) | | 18,715 | | | $61k / $222k | −$1.9k / −$5.4k | −3.0 % / −2.4 % | | |
| stacked, thr 2 c (all walk-fwd) | $20 | 2,708 | 57.6 % | 0.562 | $21.5k | +$0.71k | +3.3 % | $0.4k | 1.4 |
| stacked, thr 2 c, Jul–Sep holdout | $20 | 88 | 70 % | 0.650 | $1.0k | +$29 | +2.9 % | $0.1k | 0.3 |
| stacked, $5 / $100 caps (all) | | 2,708 | | | $9.7k / $34k | +$0.15k / +$2.0k | +1.6 % / +5.8 % | | 0.7 / 1.7 |

The raw model "sees" 10–20 c of edge on thousands of buckets and loses 2–4 % net — every disagreement with the
market is resolved in the market's favour. The stacked version trades rarely, its profit (t ≈ 1.4) comes from
Dec–Mar, and in the Jul–Sep holdout it essentially stops trading because the fitted weight on the model goes to ~0.
**No robust pre-peak forecast edge exists with public global-model data.**

## 6. Intraday probabilistic ("near-dead") model: forecasts + running max + current temperature + hour

Model (`wf_model.intraday_exceed`, `near_dead.py`): for decision hours 10:00–19:00 local, the excess
E = (final max − running max) is modelled with an ordinal logit whose inputs are: ECMWF remaining-day max minus
running max (bias-corrected with the station's 30-day ECMWF error), current temperature minus running max, today's
ECMWF error so far (running max − forecast max so far), NBM remaining max for US stations; one model per hour and
unit, refit monthly on all earlier months (walk-forward). Bucket probabilities follow from the running max floor.
This is exactly the lead's "forecast-conditioned near-dead" model (e.g. Austin 10:00, running max 82 °F,
bucket 98–99 °F: the model uses the ECMWF/NBM remaining-day max, not climatology).

Bucket-level log loss (8,200–8,400 events per hour, Mar–Sep, walk-forward):

| hour | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 |
|---|---|---|---|---|---|---|---|---|---|---|
| market | 0.2315 | 0.2226 | 0.2108 | 0.1893 | 0.1582 | 0.1195 | 0.0764 | 0.0391 | 0.0168 | 0.0081 |
| model | 0.2848 | 0.2741 | 0.2581 | 0.2384 | 0.2181 | 0.1780 | 0.1295 | 0.0891 | 0.0548 | 0.0410 |
| stacked | 0.2317 | 0.2228 | 0.2108 | 0.1893 | 0.1580 | 0.1193 | 0.0758 | 0.0384 | 0.0162 | 0.0081 |

The only improvement over the market after 15:00 comes from recalibrating the market price itself (a mild
favourite–longshot bias: YES priced 7–15 c at 16–18 h wins 5–8 %); the weather model adds nothing on top.

Trading the near-dead NO (NO executable price 0.80–0.99, model edge > threshold, fills at actual NO prints within
30 min, fee included): raw model thr 2 c: 5,885 trades, $93k staked, −$0.8k (−0.9 %); Jul–Sep holdout −0.2 %;
stacked model thr 2 c: 577 trades, −7 % to −10 %. A pure market-bias rule (buy NO when the YES last price is
0.03–0.15 at 14–18 h) loses 0.4–2 % after the fee, because the actual NO prints already sit at the calibrated level
(e.g. 17 h, YES last 0.07–0.15: YES frequency 7.9 %, NO filled at 0.920, ROI −2.1 %).
**The probabilistic near-dead edge is not capturable as a taker with public forecasts + METARs at hourly decision
frequency.** The flagged wallets' profitable "alive" trades (YES on the bucket containing the running max at
0.70–0.87, +11–15 % per $) are consistent with an information/latency advantage (faster sub-hourly observations,
e.g. 1-/5-minute ASOS or national met-service feeds that reveal the day's peak before the next METAR), not with
a better forecast model; we cannot reproduce them with hourly METARs.

