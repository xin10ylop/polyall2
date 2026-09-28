# 07 — Where does Jev (TypeSafe System One, `typesafe/jev-1.13`) actually add value?

Jev returns calibrated probabilities for typed questions about a `state`; it has no web access and produces no text.
Cost measured: ~$0.00002–0.00003 per call (input tokens only). All experiments are reproducible from `src/jev_tests/`.

| Experiment | Setup | Result | Verdict |
|---|---|---|---|
| Outcome leakage / oracle | 150 resolved May-2026 non-sports markets, question + rules only | AUC 0.61, Brier worse than base rate | Little knowledge of 2026 outcomes → no look-ahead contamination, but also no oracle skill |
| Zero-context forecaster on mentions | 3,816 mentions markets; Jev prob vs outcome, vs market price 12 h before end | AUC Jev 0.63 vs market 0.87; adding Jev to price in walk-forward logit: OOS log-loss 0.4527 → 0.4531 | No information beyond the market price |
| Toxicity classifier for liquidity provision | 1,907 non-weather markets; realized adverse-selection of naive 2-sided quoting 12–72 h before end vs Jev "decisive info likely before end?" / "information intensity" | AUC 0.53 / 0.58 for identifying toxic markets | Weak; category priors (politics/economics least toxic; mentions/tech/general most) do as well |
| **Rules-verification guardrail** | 300 weather markets (Jun–Sep 2026); bot's assumed station ICAO (true in half the cases, deliberately wrong in the other half) vs the rules text | **AUC 1.000; at threshold 0.8: 0 false-accepts, 0 false-rejects**; $0.0066 for 300 checks | **Useful**: cheap, reliable pre-trade check that the market resolves on the station/unit/metric the model assumes (Polymarket does change stations, e.g. Paris LFPG→LFPB, Taipei 466920→RCTP→RCSS) |

Conclusion: Jev is **not** a source of alpha by itself. Its proven role in the final system is a fast, calibrated
**verification gate** (rules/station/unit checks on every new market before the bot quotes it, and a
kill-switch style check on free-text status messages), with thresholds chosen from the measured error rates above.

## Forward test: LLM research + Jev judge (interim, 28 Sep 2026)

27 open markets, forecasts pre-registered at commit 34a196c (`research/forward_test/`), scored with
`src/jev_tests/fwd_score.py resolve` against the snapshot bid/ask (taker, 5¢ edge threshold, fee included).
11 of 27 have resolved so far (MTV VMAs ×7, Israel–Lebanon, MrBeast views, Trump post count, Codex resets).

| Forecaster | Brier (lower is better) | Trades | Sum of per-trade ROI | Won / lost |
|---|---|---|---|---|
| Market mid at snapshot | 0.093 | — | — | — |
| LLM research alone | **0.075** | 9 | −0.31 (−3.5%/trade) | 6 / 3 |
| Jev judging the LLM's evidence | 0.161 | 9 | −2.86 (−32%/trade) | 4 / 5 |
| 50/50 blend (pipeline's rule) | 0.108 | 9 | −2.86 (−32%/trade) | 4 / 5 |

Interim reading, n = 11 (far too small to conclude anything):
* The LLM's probabilities scored better than the market on Brier, but lost money: the 3 losses were cheap
  contrarian buys (NO at 0.17 and 0.34, YES at 0.16) that each lose the full stake.
* Jev as a judge of the evidence was worse than both. It moved away from the market in the wrong direction on
  Israel–Lebanon (0.36 vs market 0.69, resolved YES) and on the Trump post count (0.58 vs 0.15, resolved NO).
  Blending it in turned the LLM's winners on those two into losers. The judge step is dropped from the
  pipeline unless the final 27 reverse this.
* Final scoring when the last markets resolve on 30 Sep.
