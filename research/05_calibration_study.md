# 05 — Market-wide calibration study (taker trades + price snapshots)

Data: stratified sample of 3,917 resolved binary markets whose end date fell in May–June 2026
(≈12 markets per day per fee category; volume ≥ $1k; short-horizon crypto up/down excluded),
1.62M taker trades (data-api, `takerOnly=true`), hourly price history for 3,339 of them.
Stats are **market-clustered** (size-weighted per market per bucket, then averaged over markets).
Fees: taker fee = shares × rate × p × (1−p) using each market's `feeSchedule`.

## Finding 1 — Taker favourite–longshot bias is strong outside sports
Taker buys priced 0.10–0.50 lose 25–45% of stake (t ≈ −3 to −7) in politics, culture, weather,
mentions, economics. Taker buys priced 0.50–0.90 earn +3% to +13% after fees in the same categories.
Sports is close to efficient (no significant bias in any bucket).

## Finding 2 — …but a *systematic* strategy cannot harvest it naively
* Snapshot test (mid price at fixed horizons 1h…14d before close, favourite side): roughly calibrated;
  small favourite under-pricing at long horizons (≥7d) that is not significant after spread + fee.
  => the taker-trade bias is largely about *when* takers trade (endogenous timing), not a static mispricing.
* Maker view: across all maker fills, bids on favourites (0.5–0.8) look like +9% to +29% ROI.
  **Conservative trade-through backtest** (fill only if the market later trades *through* our bid, so
  price priority guarantees the fill) turns this into **−2% to −40% ROI in every category**.
  Adverse selection dominates: the fills you can be *sure* of are exactly the ones where the favourite
  is collapsing. Maker edges measured from "all maker fills" are therefore not trustworthy, and the
  user's requirement ("must be executable, same live as in test") rules out relying on queue position.

## Finding 3 — "Bond" buying at 0.95–0.995 is not free money
Market-clustered taker ROI at 0.95–0.995 is ≈ 0 to −3% in most categories (sports, tech, crypto,
finance, weather negative). Post-deadline/pre-resolution windows contain real blow-ups (weather and
mentions markets whose `endDate` precedes the actual decisive observation; rule technicalities).
Positive only in some categories (culture, economics, general) — needs a verification layer.

## Implication
Edges must come from **information/models** (weather forecasts, underlying-asset models, rule
verification) executed as **taker** orders at the displayed ask (fully executable), not from
generic price-level biases or passive quoting.

## Finding 4 — Mentions "fade the longshot" (executable taker NO-buys) does not survive out-of-sample
All 3,816 resolved mentions markets (May–Sep 2026). Rule: first 3-hourly clock mark where YES mid ∈ [lo,hi],
buy NO at max(1−mid+1¢, first actual NO taker print within 30 min), pay fee, hold. Event-clustered t-stats.
In-sample May–Jun looked good (+3% to +14% ROI), but Jul–Sep OOS: evROI between −2.6% and +1.6%, |t| < 1.3
in every YES bucket from 0.02 to 0.7. Rejected (classic decay/overfit).

## Finding 5 — Jev as a zero-context forecaster adds nothing
* Resolved May-2026 non-sports markets (n=150): Jev AUC 0.61, Brier worse than base rate → little outcome leakage,
  but also little forecasting skill without evidence.
* Mentions (n=3,370): AUC market price 0.87 vs Jev 0.63; adding Jev to market price in a walk-forward logistic model
  does not improve OOS log-loss (0.4527 → 0.4531).
=> Jev's value must come from judging *evidence the market has not priced yet* (data feeds, transcripts, rules),
   i.e. as a verifier/classifier inside a model pipeline, not as an oracle.
