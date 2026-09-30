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

## Forward test: LLM research + Jev judge (final, 30 Sep 2026)

27 open markets, forecasts pre-registered at commit 34a196c (`research/forward_test/`), scored with
`src/jev_tests/fwd_score.py resolve` against the snapshot bid/ask (taker, 5¢ edge threshold, fee included).
23 of 27 resolved; the other 4 (Primetime box office, Kraków mayor, Trump insult on 27 Sep, Ukraine–Moscow on
27 Sep) are past their end date but still awaiting UMA resolution.

| Forecaster | Brier (lower is better) | Trades | Won / lost | Sum of per-trade ROI | Mean per trade |
|---|---|---|---|---|---|
| Market mid at snapshot | **0.119** | — | — | — | — |
| LLM research alone | 0.121 | 17 | 8 / 9 | −4.01 | −24% |
| Jev judging the LLM's evidence | 0.181 | 19 | — | −6.75 | −36% |
| 50/50 blend (pipeline's rule) | 0.142 | 18 | — | −5.73 | −32% |

**Verdict: reject.** The LLM's research added no accuracy over the market price (Brier 0.121 vs 0.119), and
every version lost money as a taker. The interim lead after 11 markets (0.075 vs 0.093) disappeared. The
pattern in the losses is the same one seen in the backtests: when the forecaster disagrees with a favourite
(Xiaomi third-best lab, 10-year yield, "A Different World" #2, Olivia Rodrigo, Bruno Mars) the favourite
usually wins, and the cheap side it buys goes to zero. Jev judging the evidence was worse than both, so its
role stays limited to the rules/station verification gate above.
