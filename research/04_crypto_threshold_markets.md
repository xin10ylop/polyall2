# 04 — Polymarket crypto price-threshold markets: model vs market, non-latency edge?

*Status: COMPLETE. Date of analysis: 2026-09-26.*
Code: `src/crypto/`. Cached data: `data/crypto/` (not committed).

## 0. Scope and data inventory

### 0.1 Market families (discovered via gamma-api `/series` + `/events/keyset?series_id=`)

| Family | Gamma series (BTC) | Other assets | Cadence / history | Resolution rule (verified) |
|---|---|---|---|---|
| (a) "Bitcoin above ___ on <date>?" | `btc-multi-strikes-weekly` (id 45) | ETH 42, SOL 10022, XRP 10024 | one event per day, listed 7d ahead, ~11 strikes; daily format since 2025-08-13 (391 BTC events) | Binance BTC/USDT **1m candle opened 12:00 ET**, "Close" > strike. Verified: 4217/4218 closed BTC markets reproduce from Binance klines (the 1 miss was a parse artefact). |
| (a') hourly "above ___ on <date>, <h> ET" | `bitcoin-multi-strikes-hourly` (11372) | ETH 11373 | since 2026-03-20, 4353 events / 70,920 markets | close of the Binance **1h candle ending** at the stated time (= 1m candle opened at T−60s). 70,880/70,880 verified. Median event volume only ≈ $2k. |
| (b) "What price will Bitcoin hit in <month> / <week> / on <day>?" | monthly 10016, weekly 10151, daily 10200 | ETH/SOL/XRP equivalents | monthly since 2024-10, weekly since 2025-07, daily since 2025-08 | any Binance BTC/USDT 1m candle **High ≥ strike** (↑) or Low ≤ strike (↓) within the window (ET). After a strike is hit, a re-listed copy "…-from-<date>" is often created. |
| (c) "Bitcoin price on <date>" range buckets (neg-risk) | `bitcoin-neg-risk-weekly` (10041) | ETH 10065, SOL 10107, XRP 10247 | daily since 2025-02, 417 events | same noon-ET 1m close as (a); boundary goes to upper bucket |
| (d) Up/Down | daily 41, 4h 10331, hourly 10114, 15m 10192, 5m 10684 | ETH etc. | hourly since 2025-05, 15m since 2025-09 | close vs open of the Binance candle for the period |

### 0.2 Fees (exact)
All these crypto markets now carry `feeType=crypto_fees_v2`, `feeSchedule={rate:0.07, exponent:1, takerOnly:true, rebateRate:0.2}`.
Per docs.polymarket.com/trading/fees: **taker fee (USDC) = shares × 0.07 × p × (1−p)**; makers pay nothing (and get a 20 % rebate share).
Examples: at p=0.50 → 1.75 ¢/share (3.5 % of notional); p=0.90 → 0.63 ¢/share (0.7 %); p=0.97 → 0.20 ¢/share; p=0.05 → 0.33 ¢/share (6.65 % of notional).
Fees were switched on for the daily "above" family during **March 2026** (0 % of markets with fees before 2026-03, 100 % from 2026-04). All backtests below charge the current fee on every taker fill, including in the pre-fee period (conservative, and it is what applies going forward). The Taker Rebate Program (since 2026-05-28) is ignored.

### 0.3 Data sources
* Polymarket: gamma-api (events/markets metadata, outcomes), `clob.polymarket.com/prices-history` (YES-token **midpoint** series; fetched at 15-min fidelity for the market life + 1-min fidelity for the last 26 h), `data-api.polymarket.com/v2/trades` (all taker fills per market, cursor-paginated, no 10k cap), live `/book`.
* Underlying: **Binance BTCUSDT/ETHUSDT/SOLUSDT/XRPUSDT 1m klines** — the actual resolution source — from `data.binance.vision` (archive) and `data-api.binance.vision` (the market-data-only endpoint is not geo-blocked, unlike api.binance.com). 2024-09-01 → 2026-09-26.
* Deribit DVOL (BTC, ETH) hourly 2024-09 → 2026-09.

## 1. Fair-value model (shared by all families) — no look-ahead

* **Price convention.** Price "at" decision time t = close of the last completed Binance 1m candle (opened t−60 s). Daily "above"/range markets settle on the close of the candle opened at T (12:00 ET); hourly on the candle opened T−60 s.
* **Vol inputs available at t:** Deribit DVOL (close of the last *completed* hourly candle; BTC/ETH only), EWMA vol of de-seasonalised 5-min Binance returns (half-lives 6 h / 24 h / 168 h), and a minute-of-week seasonal variance profile estimated on the trailing 365 days *before the decision month* (captures the US-hours vol bulge: e.g. the hour before noon ET carries ~1.8× average variance, weekends ~0.5×).
* **Distribution:** r = ln(S_T/S_t) ~ Student-t(ν) with scale s = exp(β·[1, ln DVOL, ln RV6h, ln RV24h, ln RV168h]) · √(τ·seasonal-fraction(t,T)). Three specs: `dvol` (DVOL only), `rv` (realised only), `combo`. Fitted by MLE separately for 14 horizons (15 min … 30 d) on **all hourly (t,T) pairs** of Binance history (2024-10 → ), not just market times (~8–17k samples per horizon).
* **Walk-forward:** for a decision in calendar month M the model is refitted using only samples whose outcome time T+2 min ≤ first day of M (expanding window). Fitted ν ≈ 3.7–6 (fat tails), DVOL coefficient ≈ 1.1–1.4 at short horizons.
* P(S_T > K) = t_ν.sf(ln(K/S_t)/s); Gaussian variant with matched variance also computed (it is uniformly worse in log-loss). Range bucket = difference of two such probabilities; touch = empirical survival of the standardised running extreme (§3).

## 2. Family (a): "Bitcoin above ___ on <date>?" (daily, noon ET)

### 2.1 Sample
* 373 BTC events / 4,134 strikes with usable history, decision times 2025-09-03 → 2026-09-25 (events are listed 7 days ahead with ~11 strikes spaced $2k apart). Panel = each strike at h ∈ {120, 72, 48, 24, 12, 6, 3, 1, 0.5} hours before expiry: 36,950 rows. Market price = CLOB mid at t (last point ≤ t, ≤30 min stale; 1-min fidelity for h ≤ 25h).
* Liquidity: median taker notional ≈ $240k per event in the 24 h before T−24 h (all strikes), concentrated in the 2–3 strikes around the money. 1.4 M taker fills were matched to the prevailing mid: **effective half-spread** median 0.5 c (tails) – 0.75 c (mid-range), mean 0.55–0.85 c; larger at >24 h to expiry and in the last hour (mean 1.1 c).
* Live books (snapshot 2026-09-26 14:09 UTC): next-day event: near-ATM spread 1 c, ~$400 within 1 c of the ask and ~$7.5k within 5 c; events 2–6 days out: 3–4 c spreads, ~$1–7k within 5 c per strike. ETH similar but thinner; **SOL/XRP spreads 7–10 c** in the mid range.
* Outcomes: all 36,950 rows reproduce exactly from Binance data (0 mismatches).

### 2.2 Model vs market (out-of-sample, BTC)
Log-loss (LL) / Brier (BS) of the market mid vs the walk-forward model:

| h (hours to expiry) | n | LL market | LL model (combo) | LL model (rv) | BS market | BS model (combo) |
|---:|---:|---:|---:|---:|---:|---:|
| 120 | 4033 | 0.3196 | 0.3112 | **0.3095** | 0.0967 | 0.0952 |
| 72 | 4070 | 0.2429 | 0.2403 | **0.2399** | 0.0741 | 0.0740 |
| 48 | 4082 | 0.1971 | 0.1956 | **0.1955** | 0.0606 | 0.0604 |
| 24 | 4102 | 0.1327 | **0.1320** | 0.1322 | 0.0404 | 0.0402 |
| 12 | 4131 | 0.0995 | 0.0997 | **0.0994** | 0.0298 | 0.0299 |
| 6 | 4134 | 0.0840 | 0.0831 | **0.0829** | 0.0248 | 0.0246 |
| 3 | 4130 | **0.0726** | 0.0735 | 0.0733 | 0.0215 | 0.0217 |
| 1 | 4134 | 0.0388 | 0.0373 | 0.0373 | 0.0112 | 0.0109 |
| 0.5 | 4134 | 0.0241 | 0.0228 | 0.0228 | 0.0068 | 0.0065 |

The spot-only model is **as good as or marginally better than the market** at every horizon except 3 h. A logistic blend y ~ logit(mid)+logit(model) on rows with 2 c<mid<98 c puts most weight on the model (e.g. h=120: b_model=1.10 (z=6.8), b_mid=−0.18; h=24: 0.71 (z=2.1) vs 0.27; h=1: 1.30 (z=2.9) vs −0.36) — naive z's, strikes in an event are correlated, so treat as indicative. So the market is *slightly* noisier than a good vol model, but the differences are small in probability units (typically 1–3 c), i.e. the same order as spread + fee.

### 2.3 Calibration of the market itself (all strikes, BTC)
Selected bins (full table in `data/crypto/report_above_BTC.md`):

| horizon | mid bin | n | mean mid | realised | z |
|---|---|---:|---:|---:|---:|
| 0.5–1 h | ≤2 c | 3935 | 0.0013 | 0.0003 | −1.9 |
| 0.5–1 h | 98–100 c | 3643 | 0.9985 | 0.9992 | 1.1 |
| 3–12 h | 2–5 c | 418 | 0.032 | 0.050 | 2.2 |
| 3–12 h | 98–100 c | 4699 | 0.9973 | 0.9994 | 2.8 |
| 24–48 h | 60–70 c | 177 | 0.650 | 0.542 | −3.0 |
| 72–120 h | 10–20 c | 555 | 0.143 | 0.090 | −3.5 |
| 72–120 h | 40–50 c | 338 | 0.453 | 0.385 | −2.5 |

* **Far tails (≤1–3 c) are over-priced on both sides** (the cheap token wins 0.3–0.7× its price at ≤1 c; at 0.5–1 h the 1–3 c bucket wins 0.55 % vs 1.75 % priced, symmetric for calls and puts) — a genuine longshot bias, but worth only ≈0.1–1.2 c per share.
* At multi-day horizons YES is over-priced across *all* mid-range bins. Splitting by which side is cheap shows this is **directional** (upside strikes over-priced, downside strikes under-priced): it is the 2025-10 → 2026-06 BTC drawdown (126k → 58k), not a structural bias — the implied median (probit fit of the strike ladder) is within a few bp of spot, i.e. the market prices zero drift, as does the model.
* Implied central width (probit fit per event) vs realised: the market's ±1σ band covers 68–74 % of outcomes (nominal 68.3 %) at 3–120 h — **market vol is about right**; the fitted t-model is slightly too peaked in the centre (covers 55–69 %) but better in the tails.

### 2.4 Trading backtests (BTC, taker, fees charged exactly)
Rule: at decision time t, buy YES if p_model − ask_est − fee(ask_est) > θ, or NO symmetrically; ask_est = mid + cost, cost = half-spread + slippage = **1.5 c (h ≤ 6 h), 2 c (6–24 h), 3 c (> 24 h)** in the 10–90 c range, 1 c for 3–10 c / 90–97 c, 0.5 c beyond. Only tokens priced 5–95 c. Three fill models: `mid0` (execute at ask_est at t), `mid5` (signal at t, execute at mid(t+5 min)+cost — a slow trader), `trade_slow` (first real taker fill in (t+60 s, t+15 min], never dropping a signal for lack of a fill, and skipping if the fill is >1 c worse than planned). ROI = Σ PnL / Σ cost (per $ deployed); `t_cl` = t-stat of per-event summed returns (events clustered). P&L columns = fixed $ stake per trade.

**Pre-registered rule** (spec=combo, θ=3 c, all 9 horizons pooled; no parameter search):

| fill | period | trades | events | hit | avg px | ROI | t_cl | PnL $10 | PnL $50 | PnL $200 | maxDD $50 | trades/day |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| mid0 | all (2025-09→2026-09) | 1070 | 286 | 0.782 | 0.734 | +5.2 % | 2.56 | 1,222 | 6,109 | 24,436 | 635 | 2.8 |
| mid0 | train (<2026-03) | 676 | 156 | 0.811 | 0.762 | +4.9 % | 2.47 | 618 | 3,091 | 12,363 | 671 | 3.8 |
| mid0 | **test (≥2026-03, fee era)** | 394 | 133 | 0.734 | 0.685 | **+5.6 %** | **1.49** | 604 | 3,018 | 12,073 | 687 | 1.9 |
| mid5 | test | 394 | 133 | 0.734 | 0.710 | +1.9 % | 1.14 | 425 | 2,125 | 8,500 | 862 | 1.9 |
| trade_slow | test | 306 | 116 | 0.761 | 0.706 | +6.4 % | 1.73 | 659 | 3,296 | 13,183 | 571 | 1.5 |

Test-period breakdown by horizon (mid0): only h=120 h is individually notable (141 trades, ROI +10.3 %, t_cl 2.07); h=48 h is significantly negative (−14.6 %, t −2.1); others are noise.

**Walk-forward parameter selection** (grid h × spec × θ ∈ {0,2,3,5,8 c}, choose top-5 by TRAIN ROI, report TEST): 4 of 5 selected configs lose or are flat OOS (e.g. h=72/rv/θ=3 c: train +14.9 % → test −6.8 %); the exception is h=120/rv/θ=3 c: train +13.4 % (88 trades) → **test +14.5 % (128 trades, t_cl 2.13; +12 % with 5-min delay; +14 % with real fills)**. Across all 87 configs with ≥20 test trades: median test ROI +1.3 %, 52 % positive, 7 % with t_cl>2 — i.e. close to what noise would produce.

**Selling far-tail longshots** (buy the 97–99.5 c side when the cheap side is 0.5–7 c, h = 0.5–24 h): per-trade ROI between −4 % and +2 % across 24 cells, none robust in both halves; the bias exists but is smaller than half-spread + fee.

### 2.5 Verdict on family (a) (BTC)
No robust, non-latency edge after costs. A good spot/vol model is marginally better than the market mid, and a pre-registered model-vs-market rule earned +5 % per $ over 12 months (t≈2.6), but only +1.9–6.4 % (t 1.1–1.7) in the out-of-sample fee era, and ~60 % of the edge disappears if execution is 5 minutes late (the market converges toward spot-implied fair value within minutes — a latency component). The one surviving pocket is **5-days-ahead (T−120 h) pricing** (~0.6 trades/day, +10–15 % ROI, t≈2): markets that were just listed, have 3–4 c spreads and a few $k of depth per strike. Capacity ≈ $50–200 per trade, i.e. ≲ $100/day deployed, expected profit of order $5–20/day — economically negligible and statistically fragile.

## 3. Family (c): "Bitcoin price on <date>" range buckets (neg-risk, noon ET)

* 374 events / 4,042 buckets (2025-09 → 2026-09), 11 buckets of $2k plus two open tails; 36,356 panel rows; all outcomes reproduce from Binance (0 mismatches). Model bucket probability = difference of two walk-forward t-model CDFs.
* **Overround:** Σ YES mids per event averages 1.008–1.014 within 6 h of expiry and 1.024–1.053 at 24–120 h — the excess sits in the cheap buckets (≤5 c buckets: priced 3.2 c, model 2.2–2.6 c, realised 1.4–2.4 %). Live books show 1.5–8 c spreads on those buckets, so the overround is not harvestable by a taker.
* Log-loss: model ≤ market at 0.5–1 h and 24–120 h, market better at 3–12 h (e.g. h=120: 0.2630 (rv) vs 0.2674; h=3: 0.1260 market vs 0.1276).
* Backtests (same rules/costs as §2.4): **pre-registered combo/θ=3 c: ROI +2.9 % (t_cl 0.6) over 1,000 trades; test period +6.8 % (t 0.7); with 5-min delayed execution −1.3 %**. Walk-forward top-5 train configs all fail OOS (e.g. h=6/rv/3 c: train +27 % → test +3 %/−9 %). Across 105 configs: median test ROI +5.4 %, 58 % positive, 5 % with t>2 (≈ noise).
* **Verdict: no edge.**

## 4. Family (b): touch / barrier markets ("What price will Bitcoin hit …?")

* Model: remaining-horizon scale from the walk-forward t-model; P(hit) = empirical survival of the standardised running extreme |max ln(S_u/S_t)|/s over (t, t+h], pooled up/down, estimated on training windows before the decision month (plus a reflection-principle benchmark 2·P(S_T>H)). Decision times: daily at 16:00 UTC while the strike is untouched + W1−{12,6,3,1} h. Windows reconstructed from the rules (ET calendar windows; "…-from-<date>" re-listings start at creation) — outcomes reproduce from Binance highs/lows for all 28,338 rows.
* **Data-hygiene catch:** events whose window has not ended (only *already-hit* strikes are closed → 100 % YES) and multi-month events ("…before-2027", "…in-2025") must be excluded; left in, they create a spurious "monthly touch probabilities are 30 % too low" result (z≈6). Clean sample: daily 201 events/2,871 strikes (Mar–Sep 2026 only; the daily series barely existed before), weekly 62 events/832, monthly 18 events/328.

| family | LL market | LL model (empirical) | LL model (reflection) | calibration notes |
|---|---:|---:|---:|---|
| daily | 0.0451 | 0.0440 | **0.0438** | strikes priced 0.3–3 c are touched far less than priced (see below) |
| weekly | **0.1454** | 0.1469 | 0.1500 | 1–7 c strikes slightly *under*-priced (1.8 %→3.0 %, z 2.8; 4.6 %→6.2 %) |
| monthly | **0.1767** | 0.1871 | 0.1863 | no bin significant (18 events) |

* **Model-vs-market trading** (θ 2–5 c, costs 0.3 c / 1 c / 1.75 c from mid for tails / 3–10 c / mid-range — tighter than §2 because live touch books quote 0.2–1.5 c spreads): daily −1.8 % … +4.3 %, weekly −1.8 % … +1.8 %, monthly −2.2 % … +4.9 % ROI, all |t_cl| < 1 (and negative with 5-min delay). The market is at least as good as the model for weekly/monthly barriers.
* **Daily-barrier longshot bias (the one robust anomaly found).** Strikes whose YES mid is 0.5–3 c with ≤12 h left:

| subset | rows | events | touched (loss) | priced prob. | realised | ROI buying NO at 1−mid+0.3 c, fee incl. |
|---|---:|---:|---:|---:|---:|---:|
| mid 0.3–1 c | 2,742 | 201 | 1 | 0.53 % | 0.04 % | +0.19 % (real fills +0.20 %) |
| mid 1–3 c | 1,241 | 200 | 4 | 1.77 % | 0.32 % | +1.07 % (real fills +0.94 %; +0.41 % if cost is 1 c) |
| mid 0.5–3 c, H1 (Mar–Jun 14) | 1,350 | 104 | 5 | 1.3 % | 0.37 % | +0.57 % |
| mid 0.5–3 c, H2 (Jun 15–Sep) | 1,031 | 98 | 0 | 1.2 % | 0.00 % | +0.86 % |
| one trade per strike (first eligible time) | 1,460 | — | 4 | — | 0.27 % | +0.74 % |

  Break-even loss rate ≈ 0.8–0.9 %; the Poisson 95 % upper bound on the observed rate (4–5 losses) is ≈0.45 %, so the bias is statistically solid (it is symmetric across ↑/↓ strikes: ROI +0.65 % / +0.75 %). The 4 loss events were distinct days (15-Mar, 7-Apr, 3-May, 3-Jun-2026). Real taker fills in (t+1 min, t+15 min] confirm fill prices within ≈0.1 c of the assumption; the NO book is the mirror of the YES book (NO ask = 1 − YES bid), and live books show 400–3,800 NO shares within 0.3 c of the touch on each of these strikes.
  **Economics:** ≈3.6 eligible strikes/day, ≈0.7 % per trade, held ≤12 h → $50/trade ≈ $1.3/day, $200 ≈ $5/day, $1,000 ≈ $27/day (≈$10k/yr) with single-loss drawdowns equal to one full stake. Classic short-tail profile (one crash day can hit several strikes at once); the sample (7 months) contains no flash crash like 10-Oct-2025.


## 5. Family (d): Up/Down (hourly, 15-minute)

* Rules: hourly = Binance 1h candle close ≥ open; 15m/5m/4h = **Chainlink BTC/USD (TWAP) stream**, not Binance (Binance terminal-vs-open reproduces 97.4 % of 15m, 98.9 % of hourly, 90 % of 5m outcomes). Taker fee 0.07·p(1−p) (1.75 c/share at 50 c) since March 2026.
* Panel: 4,693 hourly markets (2026-03-14 → 09-26) and a random 3,998 of the 15m markets (2026-06 → 09), YES mid from 1-min price history at fixed offsets inside the window. Model: P(Up) = P(S_T ≥ S_open | S_t) with the walk-forward t-scale for the remaining minutes.
* Before the window opens the market is ≈50/50 and fair (buying either side at mid+1 c: −9 % to −16 % after fees). Inside the window the spot model beats the mid in log-loss (e.g. 15m at +5 min: 0.552 vs 0.576), and a θ=3 c rule "earns" +5 % … +23 % ROI if filled at the mid observed at t. **With a 1-minute execution delay every cell collapses to −4.4 % … +0.8 %** (3-min delay similar). The apparent edge is purely the market's quote lag behind Binance/Chainlink spot — a latency trade, excluded by mandate (and the 1-min mid series itself is a lagged sample).
* **Verdict: no non-latency edge.**

## 6. Robustness add-ons

* **ETH daily "above"** (same pipeline, 4,105 strikes/horizon): model LL better than market at ≤12 h, worse at 72–120 h. Pre-registered combo/θ=3 c: train +8.6 % (t 1.9) → **test −1.6 % (t −0.8)**, −6.4 % with 5-min delay. No edge. SOL/XRP not modelled further: their mid-range spreads are 7–10 c (live books), larger than any model-market gap observed for BTC/ETH.
* **BTC "above", freshly listed events (h = 96/144/160 h; horizons chosen *after* seeing §2's h=120 pocket — treat as semi-post-hoc):** combo/θ=3 c, cost 3 c from mid: 1,554 trades, ROI +7.0 % (t_cl 3.5); train +4.5 % (t 2.6), **test +11.8 % (589 trades, t 2.6), +10.0 % with 5-min delay, +12.3 % with real fills**. But the test P&L is directional: YES side +17 % (t 2.5) vs NO side +4.7 % (t −0.7), and August 2026 (BTC +25 % rally) alone contributes 100 trades at +61 %. Consistent with the model's zero-drift fair value beating a market that anchors to the listing price, but indistinguishable from "long BTC in a rally" over 7 months.
* Hourly "above" markets (70,920 strikes since 2026-03): median event volume ≈ $2k, live books 2–7 c wide with <$150 depth → not investable regardless of model quality; not backtested.

## 7. Final verdict

| Family | Model vs market (OOS log-loss) | Best non-latency rule, OOS (fee era ≥2026-03 unless noted) | Survives 5-min delay / real fills? | Capacity | Verdict |
|---|---|---|---|---|---|
| (a) BTC daily "above", 0.5–72 h | model ≈ market (±1–3 %) | pre-reg θ=3 c: +5.6 %, t 1.5 (394 trades) | +1.9 % / +6.4 % | $50–200/trade, ~2 trades/day | no robust edge |
| (a) BTC daily "above", 96–160 h after listing | model better (LL −1 to −3 %) | +11.8 %, t 2.6 (589 trades); h=120 walk-forward pick +14.5 %, t 2.1 | yes (+10 % / +12 %) | 3–4 c spreads, $1–7k within 5 c per strike; ~3 trades/day × $50–200 ≈ $10–40/day | **fragile/possible**: directional (long-YES in Aug-26 rally), semi-post-hoc; paper-trade only |
| (a) ETH/SOL/XRP daily "above" | ETH mixed; SOL/XRP spreads 7–10 c | ETH −1.6 % | no | thin | no edge |
| (c) BTC range buckets | model ≈ market | pre-reg +6.8 %, t 0.7; overround 1–5 % not capturable | −1.3 % (delay) | thin buckets | no edge |
| (b) weekly/monthly touch | market ≥ model | −2 % … +5 %, |t|<1 | no | deep (monthly $M volume) | no edge |
| (b) **daily touch, sell 0.5–3 c longshots (≤12 h left)** | market over-prices far barriers 3–10× | **+0.7 % per trade**, 5 losses / 2,381 rows, both halves positive (+0.57 % / +0.86 %), t_ev≈8 | yes (real fills +0.63 %, delay +0.69 %) | ~3.6 strikes/day; 400–3,800 NO shares within 0.3 c live → ≈$1k/trade ⇒ ≈$25/day | **only robust anomaly, economically tiny**, short-tail risk |
| (d) up/down hourly/15m | model ≫ market *at t* | +5…+23 % at t-mid | **no**: −4 %…+1 % with 1-min delay | — | latency only |

**Bottom line:** Polymarket's crypto threshold markets are well calibrated relative to a Binance-data/DVOL Student-t model once taker fees (0.07·p(1−p)) and 1–3 c spreads are paid. Everything that looks large (up/down, short-horizon "above") is quote lag that disappears with 1 minute of delay. Two small residuals survive realistic fills: (i) selling 0.5–3 c daily-barrier longshots (+0.7 %/trade, ≈$25/day at the book depth available, tail-crash risk), and (ii) model-based trading of newly listed (4–7 days out) BTC "above" strikes (+10–12 % OOS but t≈2.5, directional, ≈$10–40/day). Neither justifies capital beyond a paper-trading / small live pilot.

**Update after the follow-ups (§8–§9):**
- **Daily-barrier longshot sale:** realistic tail fill costs cut it to **+0.36 %/trade across BTC/ETH/SOL/XRP** (+0.54 % BTC), positive in both halves. It is absent in weekly/monthly windows and in the 3–6 c band. A strike-distance filter pre-registered on H1 (x ≥ 4.25σ) removed all H2 losses but did not raise ROI. Capacity is ≈ $10k/day for ≈ $40–50/day.
- **Finance/commodity "hit" markets:** the CLOB mid is unusable (spreads of 50–95 c). With print-based fills, a walk-forward barrier model earned +13–38 % in H1 but ≈ 0 in H2 (except natural gas). Capacity is a few hundred dollars per day.
- **Vagabund97:** their realised ROI sorts cleanly by our model edge, and their edge persisted through H2, which is consistent with minutes-scale execution on 1-minute data.

Artifacts: `src/crypto/` (fetch_events, fetch_spot, fetch_pm_history, parse_markets, volmodel, train_samples, walkforward, panel, evaluate, prereg, report_above, analyze_above/range/touch/updown, implied, live_books, compact); cached panels in `data/crypto/panel_*.parquet`, detailed tables in `data/crypto/report_above_BTC.md`, `data/crypto/report_range_BTC.md`, live book snapshot `data/crypto/live_books_20260926T1409.parquet`.

## 8. Follow-up: barrier longshot sale — cross-asset replication, loss filter, live scanner

Code: `src/crypto/barrier_panels.py` (panels, decision times W1−{24,18,12,6,3,1} h), `barrier_study.py` (tables/filters), `barrier_signals.py` (live read-only scanner), `fetch_barrier.sh`. Panels `data/crypto/panel_touch_<ASSET>_barrier.parquet` (BTC 19.7k, ETH 18.1k, SOL 15.1k, XRP 14.2k rows; every outcome reproduces from Binance 1m highs/lows, 0 mismatches). Windows still open, multi-month events and a few "dip to 0" strikes excluded.

**Fill realism upgrade.** The §4 table priced NO at 1 − mid + 0.3 c. Matching ≈5,000 real taker NO-buy/YES-sell fills in (t+1 min, t+15 min] to the mid shows the actual cost over (1 − mid) is much larger for alts and wider tails, because deep-OTM YES books are one-sided (e.g. bid 0.1 c / ask 1 c ⇒ mid 0.55 c but NO ask 99.9 c). Median effective cost (H1 estimate, used for all rows without a real fill; real fill price used where one exists):

| YES mid | BTC | ETH | SOL | XRP |
|---|---:|---:|---:|---:|
| 0.5–1 c | 0.40 c | 0.45 c | 0.45 c | 0.50 c |
| 1–2 c | 0.51 c | 0.95 c | 1.00 c | 1.25 c |
| 2–3 c | 0.65 c | 1.25 c | 1.55 c | 1.70 c |
| 3–4.5 c | 0.80 c | 1.77 c | 2.20 c | 2.50 c |

### 8.1 Replication (rule: untouched strike, ≤12 h to window end, YES mid 0.5–3 c, buy NO, fee included; H1 = before 2026-06-15, H2 = after)

| asset / family | rows | strikes | events | loss rows (days) | ROI (calibrated fills) | H1 ROI | H2 ROI | one trade per strike | t (event-clustered) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC daily | 2,353 | 1,458 | 201 | 5 (4) | **+0.54 %** | +0.39 % | +0.73 % | +0.59 % | 6.5 |
| ETH daily | 2,921 | 1,512 | 197 | 11 (10) | +0.15 % | +0.07 % | +0.27 % | +0.13 % | 0.0 |
| SOL daily | 3,008 | 1,236 | 197 | 2 (2) | +0.41 % | +0.31 % | +0.50 % | +0.37 % | 8.0 |
| XRP daily | 2,988 | 1,280 | 196 | 1 (1) | +0.37 % | +0.30 % | +0.44 % | +0.38 % | 3.8 |
| **all daily** | 11,270 | 5,486 | ~200/asset | 19 (13) | **+0.36 %** | +0.26 % | +0.48 % | +0.36 % | 5.1 |
| weekly + monthly, last ≤12 h (4 assets) | 1,562 | 771 | — | 11 (6) | −0.05 % | −0.29 % | +0.62 % | −0.08 % | −0.5 |
| weekly + monthly, 12–24 h left | 1,417 | 885 | — | 15 (8) | −0.40 % | −0.55 % | +0.06 % | −0.57 % | −1.7 |
| daily, 12–24 h left (before/at window open) | 3,864 | — | — | 18 | BTC −0.35 %, ETH −0.06 %, SOL +0.37 %, XRP +0.30 % | | | | |
| 3–6 c YES, daily ≤12 h | 2,155 | 1,603 | — | 46 (33) | −0.05 % | −0.28 % | +0.26 % | −0.23 % | −0.6 |
| 3–6 c YES, weekly/monthly ≤12 h | 225 | 162 | — | 8 (6) | −0.83 % | | | | |

* The anomaly **replicates on all four daily series and in both halves**, but after realistic fills it is **+0.36 % per trade overall** (BTC +0.54 %, SOL/XRP ≈ +0.4 %, ETH ≈ +0.15 % and not significant). With the naive 0.3 c cost it would have looked like +0.8 %.
* It does **not** carry over to the last 12–24 h of daily windows, to weekly/monthly windows (≈0 / negative; their tails are *under*-priced, consistent with §4), or to the 3–6 c band (break-even or worse). Keep the rule narrow: daily barrier, ≤12 h left, 0.5–3 c.
* Share of rows with an actual fill in the 15-min window: BTC 48 %, ETH 22 %, SOL 9 %, XRP 7 %. For SOL/XRP the result therefore rests mostly on the calibrated cost model.

### 8.2 Do losses cluster on high-vol days? Pre-registered filter
* 19 losing rows on 13 days (ETH 11). Losses cluster **across assets on the same day** (7-Apr: BTC+ETH+SOL; 16-Mar: BTC+ETH; 4-May: BTC+SOL), i.e. crypto-wide moves. They are only weakly concentrated in high realised vol: 16 % of losses vs 11 % of rows in the top decile of 1h RV, and 5 % vs 4 % for DVOL. Vol-regime filters therefore do not help. In H1 they cut losses 16→14 but lowered PnL, and were not selected.
* Losses **are** concentrated at small distance-to-strike in σ√τ units. Here x = |ln(H/S)| / (walk-forward t-model scale); losses have median x ≈ 4.1 vs 8.3 for all eligible rows.
* Candidate filters: 1h-RV top decile, DVOL top decile, either of the two, x < {2, 2.5, 3, 3.5}, model p ≥ mid or ≥ ½·mid, and x below the H1 10th/25th percentile. Disclosure: the last few candidates (x-quantile and model-based) were added after seeing that the original x grid sat below almost all eligible rows. Each filter was ranked by H1 PnL; the winner was **skip if x < 4.25 (the H1 10th percentile)**.

| filter | H1 rows kept | H1 losses | H1 ROI | H2 rows kept | H2 losses | H2 ROI |
|---|---:|---:|---:|---:|---:|---:|
| none | 100 % | 16 | +0.26 % | 100 % | 3 | +0.48 % |
| **x < 4.25 (pre-registered on H1)** | 90 % | 8 | +0.31 % | 89 % | **0** | +0.46 % |
| RV1h top decile | 88 % | 14 | +0.24 % | 90 % | 2 | +0.48 % |
| DVOL top decile | 93 % | 15 | +0.25 % | 100 % | 3 | +0.48 % |

  Out of sample, the filter removed all 3 H2 losses and kept 89 % of the volume, but ROI was unchanged (+0.46 % vs +0.48 %). It is a **tail-risk reducer, not a return enhancer**. With it (one trade per strike, all assets): 4,403 trades, 5 losses, +0.41 %.

### 8.3 Capacity (live books 2026-09-26 18:21 UTC, 9.7 h left on the daily events) and economics
* Eligible strikes per day (first eligible time): BTC 3.6, ETH 3.7, SOL 3.1, XRP 3.2. Median NO-side taker flow from the decision time to expiry per strike: BTC $6.7k, ETH $0.95k, SOL $155, XRP $160.
* Live NO depth within 0.3 c of the ask on eligible daily strikes: BTC $490–6,400 (NO ask 98.0–99.5 c), ETH ≈ $3.1–3.3k but at 99.7 c (0.28 % if untouched), XRP ≈ $300 at 99.8 c (0.19 %). Many strikes with a 0.5–1 c YES mid have NO asks of 99.9 c (a 0.09 % payoff), which the scanner correctly ranks as worthless.
* **Combined capacity ≈ $10–12k deployed per day** (BTC ≈ $7k, ETH ≈ $3k, SOL+XRP ≈ $1k). That is **≈ $40–50/day expected (≈ $15–18k/yr)**, almost all from BTC. The payoff is short-tailed: a loss costs the full stake, and the worst day hit 3 strikes across assets.
* **Verdict:** real and robust, but a small carry trade. BTC daily is worth running only as an automated, filtered (x ≥ 4.25), small-size sleeve. ETH is marginal after costs, and SOL/XRP capacity is too thin to matter.

### 8.4 Live scanner
`python src/crypto/barrier_signals.py [--max-hours 12] [--min-x 4.25] [--rv-filter] [--all] [--json out.json]` lists every open daily/weekly/monthly BTC/ETH/SOL/XRP barrier strike that is untouched and within the time limit. For each it shows the YES mid, the NO ask (from the NO book, or 1 − YES bid), NO depth within 0.3 c / 1 c, the fee, the ROI if untouched, the break-even touch probability, and x = distance / (24h realised σ·√τ). Rows are flagged when x < min-x or when 1h RV is above its 30-day 90th percentile. It only reads data and never places orders. Its x uses a plain 24h-RV σ rather than the backtest's t-model scale. On the panel, model-x / (dist ÷ RV24·√τ) has a median of 1.37 (IQR 1.18–1.63), so the backtest filter x ≥ 4.25 corresponds to **`--min-x 3.1`** in scanner units (approximate).

## 9. Follow-up: finance/commodity and altcoin barrier markets vs. wallet Vagabund97

Code: `src/crypto/fetch_fin_underlying.py`, `analyze_fin_barrier.py` (panel + walk-forward model), `fin_backtest.py`, `fin_prints.py`, `fin_print_trigger.py` (executable print-based backtests), `fin_vaga.py` (wallet comparison), `altm_panels.py`. Data: `data/crypto/fin/`, `data/crypto/vaga/`, `data/crypto/panel_fin_barrier.parquet`, `data/crypto/fin_print_trigger_*.parquet`.

### 9.1 Families, rules, resolution sources and basis
| family (series) | events used | resolution rule | proxy data we used | reproduced resolutions |
|---|---|---|---|---|
| Gold XAUUSD weekly (11397) / monthly (12052 + 3 unseriesed) | 26 w / 6 m | **Pyth** XAU/USD 1-min High/Low, after market creation, inside Pyth sessions (Sun 18:00 → Fri 17:00 ET, daily 17–18 ET break) | Binance USD-M **XAUUSDT perp** 1h, filtered to Pyth session hours; Yahoo GC=F as second proxy | perp 97.7 % (12/520 disagree); GC=F futures only 92.1 % (contango basis ≈ 0.5–1 %) |
| Silver XAGUSD weekly / monthly | 26 / 6 | Pyth XAG/USD, same session rules | XAGUSDT perp; SI=F | perp 98.5 %; SI=F 95.2 % |
| WTI weekly (11399) + monthly (6 unseriesed, $8–60 M volume each) | 26 / 6 | Pyth, **active month** of WTI futures (rolls 2 sessions before expiry) | Yahoo CL=F 1h | 99.8 % |
| Natural gas weekly (11401) / monthly (11908) | 26 / 3 | Pyth NG active month | Yahoo NG=F | 97.3 % (roll timing) |
| SPY weekly (11389) / monthly (11909) | 26 / 4 | Pyth SPY, **regular hours only** | Yahoo SPY 1h RTH | 99.1 % |
| NVDA weekly (11380) / monthly (10482) | 26 / 12 | Pyth NVDA, regular hours only | Yahoo NVDA 1h RTH | 99.8 % |
| HYPE / DOGE / BNB / SOL / XRP monthly | 11–16 each | Binance 1m Low/High (HYPE: **USDⓈ-M perp** HYPEUSDT; others spot) | Binance 1m (exact source) | 100 % |

Pyth's historical API needs authentication (the TradingView-shim history endpoint returns 404, `/v1/updates` returns 401), so we could not download the exact source. Basis risk vs the best proxy is about 1.5–2.5 % of strikes for gold/silver/NG and under 1 % for WTI/SPY/NVDA. The CME **settlement**-based families ("Crude Oil (CL) hit…", "Gold (GC) hit…", "Silver (SI) hit…") resolve on the official daily settle, not on intraday prints. They are a different product and were not modelled; Vagabund97 lost −7 % on them.

Fees: finance markets pay `0.04·p(1−p)` (taker only); crypto alts pay `0.07·p(1−p)`.

### 9.2 Model
The model uses hourly bars from the proxy. It keeps an EWMA per-bar vol (half-life 60 bars) as of the last *completed* bar, and counts the remaining bars n in the window from the deterministic session calendar. The standardised distance is x = |ln(H/S)| / (σ√n). P(hit) is the empirical survival function of the standardised running extreme max(|ln H_k/S|, |ln L_k/S|)/(σ√n) over n bars, pooled across up and down strikes. It is estimated on bars whose horizon ended before the first day of the decision month (walk-forward); overnight and weekend gaps are included in the empirical distribution. Decisions are taken at 16:00 UTC on each weekday while a strike is live and untouched.

### 9.3 The CLOB midpoint is meaningless in these books
This is the main pitfall. A live snapshot (2026-09-26) of next week's gold ladder shows **YES bid 0.02–0.50 against YES ask 0.98 on every strike**. Median spreads are 88–95 c for gold, silver and WTI weekly, 17–22 c for SPY, 6–7 c for NVDA, and 47–96 c for HYPE/BNB/DOGE monthly. With mids, the market looks badly overpriced on touches: 35–50 c bins realise 31 %, and a weekly buy-NO model rule shows +28 % ROI (t 5). But only **2.7 %** of those signals had a real fill within 15 minutes. A strike 3σ away "priced" at a 28 c mid is simply a 0.02/0.55 book. **Every mid-based result for these families is therefore discarded.**

### 9.4 Executable backtests
* **Print-triggered backtest.** Every historical taker print reveals real liquidity: a YES bid that was hit means NO was buyable at 1−px, and a YES ask that was lifted means YES was buyable at px. At each print we evaluate the model using only hourly bars completed before the print, take the revealed side if the edge after fees exceeds θ, and allow at most one trade per market per hour, at the print's size.

| subset (θ = 5 c) | trades | events | ROI | t (event-clustered) | trades/day | median print size |
|---|---:|---:|---:|---:|---:|---:|
| all finance barriers | 26,258 | 192 | +5.9 % | 0.1 | 80 | $6–20 |
| weekly finance, H1 (< 2026-06-15) | 2,463 | 66 | +17.3 % | 2.7 | 32 | |
| **weekly finance, H2 (≥ 2026-06-15)** | 4,519 | 90 | **+0.5 %** | 0.6 | 44 | |
| weekly, buying NO: H1 / H2 | 1,512 / 2,561 | 64 / 88 | +13.2 % / **−3.2 %** | 2.1 / −0.9 | | $20 / $12 |
| weekly, buying YES: H1 / H2 | 951 / 1,958 | 63 / 87 | +32 % / +9.9 % | 1.9 / 0.9 | | $6 |
| monthly finance | 19,276 | 37 | +5.5 % | −0.5 | | |
| weekly, one trade per market, θ = 10 c: H1 / H2 | 356 / 529 | 64 / 89 | +38 % / +9.4 % | 4.1 / 1.4 | 4.9 / 5.2 | |
| alt monthly (HYPE/DOGE/BNB/SOL/XRP) | 11,996 | 69 | **−7.8 %** | −2.2 | | (YES side −34 %, NO side +10 %, t 1.4) |

  By family, weekly θ = 5 c, H1 → H2: gold +34 % → +13 % (t 3.1 → 0.6); **natural gas +40 % → +24 % (t 3.0 → 2.2, the only family positive and significant in both halves)**; SPY +8 % → +6 %; silver +18 % → −17 %; WTI +18 % → −12 %; NVDA +13 % → −7 %.
* A decision-time version (16:00 UTC, fill only on a qualifying print within 15 min / 1 h / 4 h) gives +3 % to +8 % ROI with |t| < 1.6. The mid-based alt monthly result (+30 %, t 4.7) likewise collapses to −8 % with prints.

### 9.5 Vagabund97 (0xa53b…4021)
* 2,823 fills since 2025-12-12 (69 % taker), $148k notional, **+$25.0k realised on resolved markets (+17 % per $)**. In the families above: weekly gold +42 %, weekly WTI +23 %, weekly silver +12 %, monthly silver +33 %, monthly gold +15 %, monthly WTI +13 %, alt monthly +17 %, SPY −24 %, CME-settle families −7 %.
* Entries are mostly 15–50 c tokens, typically 2–3 days after window open and 55–80 h before the end of weekly windows, 97 % as taker, with fills of about $50–100 each.
* **Our model evaluated at their fill times** (694 fills, $72k, no look-ahead): their realised ROI rises monotonically with our model edge. Edge ≤ −10 c: +1 %; −10…−3 c: +5 %; ±3 c: +22 %; +3…+10 c: +29 %; +10…+20 c: +35 %; correlation 0.14. They trade in line with a spot+vol barrier model, as suspected.
* **Their performance did not decay:** weekly H1 +21 %, H2 +26 %; monthly +9 % / +15 %. Our hourly-bar print-triggered replica decays to about 0 in H2. The likely difference is execution: they react within minutes on 1-minute underlying data, choose their moments (the book is stale right after underlying moves), and probably use a better-calibrated model. That is a minutes-scale reaction edge. It is not millisecond latency, but our hourly-snapshot backtest cannot capture it.

### 9.6 Capacity and verdict
* **Capacity is tiny.** Live NO-side depth within 2 c of the ask is about $60 (gold weekly), $140 (silver), $250 (WTI), $820 (SPY) and $40–100 (NVDA) per strike. Historical prints have a median of $6–27. Vagabund97 deploys about $500/day of notional for roughly $90/day of P&L across *all* their families, which is about the ceiling for one careful taker.
* **Verdict:** a hourly-bar barrier model **does** identify mispricing in the finance "hit" markets: the realised ROI of a known profitable trader sorts cleanly by our model edge, and H1 print-based results are +13–38 % with t 2–4. But our non-latency implementation lost the edge in H2 (Jun–Sep 2026) except for natural gas, and capacity is a few hundred dollars per day. It is worth a paper-trading pilot only if it is re-built on 1-minute underlying data with continuous monitoring (react within minutes to underlying moves, take only resting liquidity at model-edge ≥ 10 c, weekly gold/NG/SPY). It is not a scalable strategy. Alt-coin monthly barriers show no edge once executable prices are used.
