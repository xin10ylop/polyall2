# 06 — Tweet-count ("# of posts") markets: model-based taker edge?

Status: COMPLETE (2026-09-26). Code: `src/tweets/`. Data cache: `data/tweets/`.
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

## 3. Backtest set-up

* Universe: 543 resolved count events (non-`arch-`), window start ≥ tracker start + 28 d → Elon from 2025-12-16,
  WH 2026-03-17, Trump 2026-02-24, the X small accounts from 2026-04-10/14. Walk-forward params exist from
  Jan-2026 (Elon) / May-2026 (others), so 509 events have decision rows (1.36 M bucket×time rows).
* Decision times: hourly from max(window start − 48 h, first price) to end, plus every 10 min in the last 3 h.
* Market data: CLOB `prices-history` at 10-min fidelity (verified against live books to be the **book midpoint**,
  also for wide books: median |history − (bid+ask)/2| = 0.75 c), and **all** taker trades via
  `data-api /v2/trades?condition=…` (cursor pagination, no 10k cap; 8.7 M trades).
* Look-ahead controls:
  * model uses only posts with `importedAt ≤ t`; params walk-forward;
  * the execution mid is the **first sample at/after t + 60 s** (market has ≥ the model's information);
  * events overlapping detected tracker outages are dropped; decision times when xtracker has imported no
    X post for > 120 min (a real-time-observable stall proxy) are skipped;
  * IS = decision times before 2026-06-01, OOS = after (Jun–Sep 2026).
* Fill model A ("mid-based"): YES ask = mid + max(1 c, median lift-print premium over mid in the prior 24 h),
  never below the last lift print of the previous 30 min; NO ask = 1 − (mid − max(1 c, hit premium)); plus the
  exact fee 0.05·p·(1−p). One entry per (event, bucket, side), held to resolution.
* Fill model B ("print-confirmed"): fill only at the price of an actual taker print in the 30 min before t
  (YES buy ← last YES-equivalent lift print; NO buy ← last hit print), only if xtracker imported **no new post
  between that print and t**, size capped at that print's size; plus fee.

## 4. Why the xtracker count is not "known exactly" at decision time

* xtracker imports X posts with a median lag of ~2.7 min (p90 ≈ 5 min); competitors trade off X directly
  (one active wallet advertises a faster alert tool, "xtracker.live"). In the last minutes of a window the
  market therefore knows more than an xtracker-based model.
* **Global X-side stalls** (all X accounts stop importing, then back-fill): 2026-04-30 (≈20 h), 06-01 (up to
  69 h lag), 08-26→08-28 (45–77 h), 09-10→09-11 (≈21 h). During these the displayed count is stale, the market
  is not. Example: WH Sep 4–11 — xtracker showed 197 at the close, the market priced `200+` at 0.996, the final
  (back-filled) count was 228. An xtracker-only model would have sold `200+` at 0.4 % and lost everything.
  Trump/Truth Social stalls are the norm (median time since last import 3.4 h, p90 ≈ 4 days).
* Consequence: near the end of windows the model's log-loss is much worse than the market's for WH, Elon,
  Zelenskyy, Cruz and (dramatically) Trump — the market is faster, not dumber.

### 4.1 Model vs market as forecasters (log-loss of the realised bucket; market = normalised mids at/just before t)

OOS (Jun–Sep), mean log-loss per snapshot (lower is better), model − market:

| account | <6 h | 6–24 h | 24–96 h | >96 h |
|---|---:|---:|---:|---:|
| elonmusk | +0.11 | +0.05 | +0.01 | +0.02 |
| WhiteHouse | +0.52 | +0.30 | +0.13 | +0.02 |
| ZelenskyyUa | +0.12 | +0.13 | +0.19 | +0.23 |
| cz_binance | +0.16 | +0.07 | +0.04 | −0.09 |
| tedcruz | +0.23 | +0.03 | −0.12 | −0.15 |
| NYCMayor | −0.06 | −0.07 | −0.12 | −0.30 |
| khamenei_ir | −0.08 | −0.11 | −0.10 | −0.26 |
| realDonaldTrump | +1.12 | +0.35 | +0.19 | −0.10 |

* **Elon**: model ≈ market at every horizon (RMSE of the forecast bucket index within ±0.03 buckets of the
  market). The market spreads more mass into far tails (0.1–2 c on each of 15–25 far buckets: the usual
  long-shot premium), which is not shortable after spread + fee. No structural mispricing of the central mass.
* The model "beats" the market only on thin accounts (NYC Mayor, Khamenei, Cruz/CZ at long horizons) — where
  mids of 20–70 c-wide books are not prices anyone can trade at (Section 6).

## 5. Trading-rule backtests (taker only, held to resolution)

Rule: buy YES on bucket k if `q_k − (ask + fee) > θ`; buy NO if `(1 − q_k) − (NO ask + fee) > θ`;
first signal per (event, bucket, side) only; optional minimum time-to-end `hmin`. Grid: side ∈ {YES, NO, both} ×
θ ∈ {0.03, 0.05, 0.10} × hmin ∈ {0, 12, 48 h} = 27 configs per account group and fill model. The config was
**selected on IS (event-clustered t)** and then reported OOS. Full grids: `data/tweets/elon_grid.csv` (fill A),
`data/tweets/grid_fillB.csv` (fill B). Trump and outage-affected events are excluded from the headline numbers.

### 5.1 Fill model A (mid + ≥1 c + fee), for reference only
In-sample the Elon rules look excellent (e.g. NO, θ = 0.02–0.05: t ≈ 4, YES θ = 0.05: ROI +43 %), and 89/90
configs stay positive OOS on an equal-weight basis. But (i) the OOS t-stats fall to 0.5–2.4, (ii) when each trade
is capped at 25 % of the prior 6 h lift/hit volume at that price, OOS PnL is ≈ 0 or negative for most configs
(the ROI comes from tiny long-shot fills), and (iii) for thin books the mid is not a tradable price. Fill A
overstates executability; fill B below is the honest number.

### 5.2 Fill model B (print-confirmed, size capped by the confirming print) — headline

| | Elon (IS-best: NO, θ=0.03, hmin 12 h) | Small X accounts (IS-best: both sides, θ=0.10, hmin 12 h) |
|---|---|---|
| IS (≤ May-2026): trades / events | 733 / 114 | 160 / 50 |
| IS size-wt ROI ($200 cap) / week-clustered t | +8.0 % / 1.9 | +59 % / 1.5 |
| **OOS (Jun–Sep 2026): trades / events** | **375 / 87** | **604 / 188** |
| OOS hit rate / avg entry price | 0.79 / 0.77 | 0.51 / 0.41 |
| OOS ROI per trade, equal weight | +1.4 % | +37.6 % |
| OOS $10 target: deployed / PnL | $2.1k / +$133 | $3.3k / +$1,079 |
| OOS $50 target: deployed / PnL | $4.5k / +$265 | $5.5k / +$1,321 |
| OOS $200 target: deployed / PnL (ROI) | $6.2k / +$267 (+4.3 %) | $6.2k / +$1,160 (+18.6 %) |
| OOS max drawdown ($200 target) | $317 | $175 |
| OOS week-clustered t (size-weighted) | **0.5** | **2.3** (equal-wt 3.1) |
| Deployable capital (target $200) | ≈ $55/day | ≈ $54/day |

(Deployed amounts fall short of the $10/$50/$200 targets because each fill is capped at the size of the print
that confirms the price.)

* **Elon: no robust executable edge.** Across the 27 fill-B configs, OOS size-weighted ROI runs from −39 % to
  +20 % with no config reaching t = 2. YES-side rules (buying buckets the model rates above the market) lose
  money OOS when weighted by size. NO-side rules earn +2 to +20 % with t ≈ 1–1.5, which is not distinguishable
  from zero given 27×2 configs. The IS edge (t ≈ 3–5) decays OOS, the classic overfit / regime pattern (Elon's
  rate fell from 69/day to 29/day across the sample).
* **Small X accounts: small, statistically plausible, but economically trivial.** Every one of the 27 fill-B
  configs is positive OOS (size-weighted ROI +6 to +31 %, event-clustered t 2.1–3.7). It holds in each OOS month
  (Jun +11 %, Jul +43 %, Aug +6 %, Sep +16 %). By account (OOS, $200 target): Cruz +54 %, Khamenei +44 %,
  CZ +30 %, NYC Mayor +23 %, Zelenskyy +7 %, **White House −19 %**. It is not a latency effect: most of the PnL
  comes from entries more than 96 h before the end (+23 %) and 12–24 h (+59 %). The 24–96 h entries are ≈ 0.
  Caveats: the fills come from books with 20–70 c spreads; the confirming print may be the same
  liquidity another taker already took (so fill size could be optimistic by up to 2×); and the IS sample
  (50 events) is too small to have selected the config with confidence.
* **Trump** (flagged, not in headline): OOS +12 % size-weighted, t 0.5; tracker failures make the model's
  C(t) unreliable. Not tradable with an xtracker-based model.

### 5.3 Edge vs time-to-end (latency)
* Elon, fill A, every signal: last-hour entries are erratic (IS −32 %, OOS +102 % on 31 trades). 1–3 h is
  negative OOS (−22 %). Nothing consistent inside 24 h.
* With the xtracker count, the model is **worse** than the market in the last 6 h for Elon/WH/Zelenskyy/Cruz
  (Section 4.1). With an own-X-monitor count (createdAt-based, "loose" variant), Elon's last-hour log-loss
  becomes slightly better than the market's (0.183 vs 0.200); all other horizons are unchanged. So the only
  model-vs-market advantage near the end is **pure latency** (seeing posts minutes before xtracker / other
  traders), and at least one competitor already sells a faster alert tool. Flagged, not pursued.

## 6. Executability — live books (snapshot 2026-09-26 14:17 and 14:54 UTC, `data/tweets/books/`)

| account | live buckets (0.02 < price < 0.98) | median spread | median ask depth within 1 c / 5 c |
|---|---:|---:|---|
| elonmusk | 36 | **1.0 c** | $130 / $560 (central buckets $200–1,800 within 2 c) |
| NYCMayor | 6 | 3.5 c | ~$170 / ~$330 |
| cz_binance | 8 | 6.5 c | ~$60 / ~$80 |
| realDonaldTrump | 16 | 5.5 c | ~$40 |
| WhiteHouse | 4 | 22 c | ~$30 |
| khamenei_ir | 1 | 26 c | ~$20 |
| ZelenskyyUa | 8 | 28 c | ~$4 |
| tedcruz | 10 | 35 c | ~$7–11 |

* Elon books are tight and deep enough for $200–1,000 clips in central buckets, but the backtest finds no
  model edge there.
* Small-account books are where the model disagrees with the mid. Live example (14:54 UTC): the model gives
  Cruz 80–99 (Sep 25–Oct 2) q = 0.28 against an ask of 0.17, but only **$3.40** is offered within 2 c. The model
  gives Zelenskyy 120–139 q = 0.13 against an ask of 0.041, with **$0.94** offered. These books cannot absorb
  even a $50 order without walking 10–30 c.
* Live Elon discrepancies exist too (e.g. Sept-monthly 800–839: model 0.34 vs ask 0.18; 48 h Sep 26–28 `<40`:
  model 0.35 vs ask 0.20). Per 5.2, discrepancies of this type did not pay OOS, so they should not be traded
  on this model.

## 7. Conclusions

1. **Data**: xtracker exposes every post with `importedAt`, so no-look-ahead reconstruction is possible. For
   X accounts, the final xtracker count reproduces 100 % of resolutions (excluding archived duplicate events).
   However, ~3 % of Elon/WH/Cruz windows get back-filled after the close, and there are multi-hour to
   multi-day global import stalls. Truth Social (Trump) tracking is unreliable (71 % match).
2. **Model**: a profile-adjusted EWMA + negative-binomial model is roughly calibrated walk-forward, and for
   Elon it matches the market's forecast quality at every horizon beyond 6 h. It is worse than the market near
   the close, because the market sees posts before xtracker does.
3. **Elon (the only liquid market)**: **no exploitable executable edge** after spread, the exact 0.05·p(1−p)
   fee, and print-confirmed fills. IS-selected rules have OOS t ≈ 0.5.
4. **Small accounts (Cruz, Khamenei, CZ, NYC Mayor, Zelenskyy; not WH)**: a consistent OOS edge
   (+19 % size-weighted, t ≈ 2.3). It is available days before the end, so it is not a latency game.
   **Capacity is ~$50/day deployed, ≈ $10/day PnL** across all of them, in books with $1–$80 of depth. This is
   a hobby-scale edge, and the fill model is probably optimistic there.
5. The only other "edge" found is last-minutes latency (own X monitoring vs xtracker lag), which is a speed
   race with existing specialised competitors. Not recommended.

**Verdict: no scalable executable edge in tweet-count markets with this model.**

### Reproduce
```
python3 src/tweets/fetch_xtracker.py ; python3 src/tweets/fetch_gamma.py ; python3 src/tweets/build_events.py
python3 src/tweets/fetch_trades.py 8 ; python3 src/tweets/fetch_prices.py 6
python3 src/tweets/calibrate.py ; python3 src/tweets/walkforward.py ; python3 src/tweets/calib_summary.py
python3 src/tweets/bt_build.py 4 ; python3 src/tweets/bt_prints.py 3      # decision tables (strict) + fill B
BT_MODE=loose python3 src/tweets/bt_build.py 3                             # needs calibrate.py loose + walkforward.py _loose
python3 src/tweets/live_books.py ; python3 src/tweets/live_signals.py      # live books / live model check
# analysis: functions in src/tweets/bt_eval.py (load, trades, summarize, load_pc, trades_b, summarize_b, snapshot_scores)
```
