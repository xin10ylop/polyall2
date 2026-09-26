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
