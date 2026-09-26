# 06 — Tweet-count ("# of posts") markets: model-based taker edge?

Status: IN PROGRESS (written incrementally). Code: `src/tweets/`. Data cache: `data/tweets/`.
Date of study: 2026-09-26.

## 1. Data sources and what they really contain

### 1.1 xtracker (resolution source)
* `GET https://xtracker.polymarket.com/api/users` → 10 tracked handles (one is an E2E test user):
  elonmusk (X, since 2025-11-18), realDonaldTrump (Truth Social, 2026-01-21), WhiteHouse (2026-01-15),
  tedcruz / khamenei_ir (2026-03-12), ZelenskyyUa / NYCMayor / cz_binance (2026-03-16), Cobratate (2026-02-04).
* `GET /api/users/<handle>/posts` returns **the full post list in one response** (no pagination; query params
  `startDate`/`endDate` filter; `limit/page/offset` are ignored). Each post has `createdAt` (post time) and
  **`importedAt` (when xtracker ingested it)** → as-of-time counts can be reconstructed without look-ahead:
  `C(t) = #{createdAt ∈ [S, t), importedAt ≤ t}`.
* `GET /api/users/<handle>/trackings` → every market window (incl. inactive/historical);
  `GET /api/trackings/<id>?includeStats=true` → current total + hourly counts.
* Posts are *not* removed when deleted on X ("Deleted posts will count as long as they remain available long
  enough to be captured by the tracker (~5 minutes)").
* Import lag: median 2.5–3 min, p90 ≈ 5 min for X accounts; but ~1% of posts are **back-filled days later**
  (p99 lag 1–18 days). Truth Social (Trump): p90 lag **40 h** — frequent outages / back-fills.

### 1.2 Does the current xtracker DB reproduce the resolutions?
Counting posts with `createdAt ∈ [start, end)` in today's DB and mapping to buckets, vs. the resolved winner
(events with a full xtracker history; window from the rules text; `arch-*` events excluded — those are
archived duplicate events "resolved" before their window even ended):

| account | events | final-DB count → winner | as-of window end (+10 min) | as-of end + 1 day |
|---|---:|---:|---:|---:|
| elonmusk | 216 | 100% | 97.2% | 98.1% |
| WhiteHouse | 53 | 100% | 96.2% | 100% |
| tedcruz | 53 | 100% | 96.2% | 100% |
| ZelenskyyUa / NYCMayor / cz_binance / khamenei_ir / Cobratate | 51/51/51/52/7 | 100% | 100% | 100% |
| **realDonaldTrump** | 63 | **71%** | 67% | 70% |

* Non-Trump: the final xtracker count is the resolution truth. ~3% of Elon/WH/Cruz events had late
  back-fills after window end that changed the bucket → a trader who treats the displayed count at the end
  as final is exposed to this.
* **Trump is not reliably tracked**: outages (e.g. 2026-05-17→05-27 with zero posts recorded; 08-15→08-18),
  systematic −1…−4 undercount vs resolution, and huge back-fills (07-21 window: 63 posts visible at the end,
  194 final). Resolution then falls back to Truth Social itself. Trump results below are flagged.
* Detected tracker outages (≥40 h with no post for accounts averaging ≥10/day): WhiteHouse 2026-01-16→03-05
  and 03-12→03-17; tedcruz 03-12→03-17; Trump 01-23→01-28, 02-04→02-06, 05-17→05-27, 08-15→08-18.
  These periods are excluded from calibration and from the backtest.

### 1.3 Polymarket events (Gamma, tag `tweets-markets`)
* 813 closed + 31 open events. Count events used: series `elon-tweets` (7-day, Tue/Fri 12:00 ET starts),
  `elon-tweets-48h`, `elon-tweet-daily` (monthly), `trump-truth-social`, `whitehouse-daily-tweets`,
  `ted-cruz-daily-tweets`, `zelenskyy-tweets`, `nycmayor-tweets`, `cz-tweets`, `khamenei-daily-tweets`,
  `andrew-tate-tweets` (7-day). "elon-tweet-mention" (word markets) excluded.
* Structure: neg-risk multi-outcome, 10–46 buckets (`<40, 40-64, …, 240+` for 48 h; 20-wide for weekly; 5-wide
  for Khamenei). Lower buckets are **resolved NO early** as soon as the count passes them.
* Fees: all 2026 events carry `feeType: culture_fees`, `feeSchedule {rate 0.05, exponent 1, takerOnly}` →
  taker fee/share = 0.05·p·(1−p). Older (2025) events: no fees.
* Volume: Elon events are large (weekly: $1–3M total, $100–250k in the central buckets); all other accounts
  are tiny (typically $0.5–25k per bucket over the whole event).

## 2. Posting model (no look-ahead)

Behaviour (daily counts): strongly over-dispersed (var/mean 6–15 for Elon, Trump, WH, Cruz, Zelenskyy),
autocorrelated rates (Elon lag-1 day autocorr 0.46, WH 0.67), clear hour-of-day cycles and large weekend dips
for institutional accounts (Sat/Sun rate ÷ mean: WH 0.58/0.59, Cruz 0.62/0.63, Zelenskyy 0.67/0.79; Elon 0.89/0.94).
Mean posts/day over the sample: Elon 38 (falling: 69/day in Jan-26 → 29/day in Sep-26), WH 22, Trump 21, Cruz 17,
Zelenskyy 12, NYC Mayor 5.5, CZ 3.3, Khamenei 0.6.

Model (`src/tweets/model.py`), evaluated at decision time t for a window [S, E):
* Known: `C(t)` = posts with createdAt ∈ [S, t) **and importedAt ≤ t** (the xtracker figure at t).
* Rate `R` (posts/day) = profile-adjusted EWMA over the last 56 days of posts visible at t (half-life `hl`),
  intensity(τ) = R × hour-of-day share (last 28 days, shrunk to uniform) × day-of-week factor (last 56 days, shrunk).
* `μ = ∫_{max(t,S)}^{E} intensity`, remaining count `N ~ NegBin(mean μ, var μ + α μ²)`, bucket probs
  `P(C + N ∈ [lo, hi])`.
* `hl ∈ {0.25…14 d}` and `α` are fit per account × horizon bin (0–2, 2–4, 4–8, 8–16, 16–32, 32–64, 64–128, 128–256,
  256+ h) by maximum likelihood on synthetic decision points (every 3 h × 20 horizons, 1 h…30 d) — no market
  data involved. **Walk-forward**: parameters used in month M are fit only on points whose target window ended
  before M. Tracker-outage periods are excluded from fitting.
* Model choice made with some OOS knowledge (disclosed): the day-of-week factor was kept after it improved
  OOS log-likelihood for WH (+0.09 nats/pt), Cruz (+0.03), Zelenskyy (+0.02) and slightly hurt CZ/Khamenei
  (−0.02). No other model variants were tried against OOS data.

Walk-forward OOS calibration (decision points 2026-06-01 → 09-25; `data/tweets/calib_oos_summary.csv`):

| account | horizon | actual/pred mean | 80%-interval coverage | below p10 | above p90 |
|---|---|---:|---:|---:|---:|
| elonmusk | <8h / 8–32h / 32–128h / >128h | 1.04 / 1.02 / 1.00 / 1.00 | 0.78 / 0.80 / 0.80 / 0.91 | .10/.08/.08/.03 | .12/.12/.12/.07 |
| WhiteHouse | same | 1.06 / 1.05 / 1.03 / 1.02 | 0.79 / 0.80 / 0.83 / 0.74 | | .10/.10/.12/.20 |
| tedcruz | same | 1.04 / 1.02 / 1.00 / 1.03 | 0.81 / 0.82 / 0.85 / 0.88 | | |
| ZelenskyyUa | same | 1.07 / 1.04 / 1.01 / 1.02 | 0.79 / 0.76 / 0.77 / **0.64** | | |
| cz_binance | same | 1.09 / 1.06 / 1.05 / 1.13 | 0.78 / 0.78 / 0.77 / 0.74 | | |
| NYCMayor | same | 1.05 / 1.03 / 1.02 / 0.97 | 0.81 / 0.79 / 0.87 / 0.89 | | |
| khamenei_ir | same | 0.82 / 0.79 / 0.77 / 0.76 | 0.79 / 0.77 / 0.81 / 0.81 | | |
| realDonaldTrump | same | 1.05 / 1.03 / 0.99 / 1.04 | 0.81 / 0.78 / 0.81 / 0.84 | | |

The model is roughly calibrated (a well-specified model would show 0.80 / 0.10 / 0.10); it is slightly
over-confident for 1-week+ horizons on Zelenskyy/CZ/WH and has a small upward drift (rates rose over the
sample). It is a reasonable "fair value" engine — the question is whether it beats the market.

