# 11 — Independent checks of the two adopted "satellite" edges (lead, 2026-09-26)

## Tweet counts, small X accounts (research/06)
Recomputed from `data/tweets/oos_trades_small.parquet` (604 OOS trades, 188 events, Jun–Sep 2026, $200 target):
* ROI +18.6% ($1,160 on $6,223). Event-bootstrap ROI 90% CI **[+3.4%, +35.3%]**, P(ROI<0) = 2%.
* **Concentrated:** top-5 events = 66% of P&L; dropping the top-10 events turns P&L negative (−$133).
* By account: Cruz +54%, Khamenei +44%, CZ +30%, NYC Mayor +23%, Zelenskyy +7%, **White House −19%**.
* By month: Jun +16%, Jul +25%, Aug +4%, Sep +38%.
* Maker variant (resting at model fair ± margin): every configuration loses OOS (−4% to −35%).
Verdict: real but lumpy, ~$54/day deployable → ~$10/day expected. Keep only as a small satellite; exclude White House.

## Daily BTC barrier longshot sale (research/04 §4)
Recomputed from `data/crypto/panel_touch_BTC_barrier.parquet` (daily series, τ ≤ 12 h, YES mid 0.5–3 c, first eligible
time per strike, NO bought at 1 − mid + 0.3 c, fee 0.07·p(1−p)):
* 1,468 trades over 207 days; 4 losses (0.27%); ROI **+0.74%** per trade.
* Day-clustered bootstrap ROI 90% CI **[+0.50%, +0.94%]**, P(ROI<0) ≈ 0.
* Only 4 of 207 days negative, but each loss ≈ −1 stake; the sample contains no flash-crash day, so the true tail is
  fatter than observed. Per-event exposure cap is mandatory.
Verdict: robust small edge; ~7 eligible strikes/day; ≈$25/day at $500–1,000 per trade. Implemented as
`bot/strategies/btc_barrier_no.py` (paper mode running; first paper fill 18:10 UTC: NO ↑86,000 at 0.9949).

### Update after the crypto agent's fill-realism upgrade (research/04 §8)
Matching ≈5,000 real taker NO fills shows the true cost over (1 − mid) is 0.40–0.65 c for BTC (more for alts), not the
0.3 c assumed above. Calibrated ROI: BTC +0.54% (t 6.5), SOL +0.41%, XRP +0.37%, ETH +0.15% (n.s.); all daily +0.36%.
A distance-to-strike filter pre-registered on H1 (skip x < 4.25 σ√τ units) removed all 3 H2 losses with unchanged ROI.
Capacity ≈ $10–12k staked/day → ≈ $40–50/day. The bot's limit rule (NO ask ≤ 1 − mid + 0.3 c) only takes the cheaper
subset, so it trades less often than the backtest.

## Finance/commodity/alt barrier markets (research/04 §9)
Mids are meaningless (weekly gold/silver/WTI ladders show 88–95 c spreads); only print-triggered evaluation is valid.
Weekly: +17% (H1, t 2.7) → +0.5% (H2, t 0.6) with an hourly-bar model; natural-gas weekly held in both halves
(+40% / +24%, t 3.0 / 2.2) but median trades are $6–27. Vagabund97's own fills keep earning in H2 (+26% weekly),
consistent with reacting on 1-minute data. Verdict: real but tiny; pilot only after a 1-minute rebuild.
