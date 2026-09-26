# 02 — Polymarket Leaderboard Forensics: how consistent, small-capital traders make money

*Status: complete (v1). Data pulled 2026-09-26. Author: research agent. Nothing here is investment advice; all numbers are from public Polymarket APIs and carry the caveats in §7.*

## 0. Data sources and API notes (verified by probing)

| Endpoint | What it gives | Limits discovered |
|---|---|---|
| `data-api.polymarket.com/v1/leaderboard?timePeriod=DAY\|WEEK\|MONTH\|ALL&orderBy=PNL\|VOL&category=<c>&limit&offset&user=` | ranked wallets with `pnl`, `vol` | `limit` max 50; `offset` works to at least 1000; categories: `overall, politics, sports, crypto, culture, mentions, weather, economics, tech, finance, esports`; `user=` returns a single wallet's PnL in that category/window (used for category split) |
| `lb-api.polymarket.com/profit?window=1d\|7d\|30d\|all` | legacy profit board | returns max 50 rows; same ranking as v1 |
| `user-pnl-api.polymarket.com/user-pnl?user_address=&interval=all&fidelity=1d` | daily **cumulative** PnL series (realized + mark-to-market) | 1 call per wallet; basis for all consistency metrics |
| `data-api.polymarket.com/activity?user=&limit=500&offset&end=` | TRADE / REDEEM / MERGE / SPLIT / REWARD / CONVERSION events with `usdcSize` | limit max 500, **offset max 5000**; page further back with `end=<ts>` |
| `data-api.polymarket.com/trades?user=&takerOnly=true\|false&limit=` | fills; **`takerOnly` defaults to true** | `takerOnly=true` vs `false` difference = maker fills → maker/taker split |
| `data-api.polymarket.com/closed-positions?user=&limit=50&offset&sortBy=REALIZEDPNL\|TIMESTAMP` | per-outcome-token realized PnL, avgPrice, totalBought | limit 50/page; includes resolved losers (curPrice 0) |
| `data-api.polymarket.com/positions?user=&sizeThreshold=0` | open positions, `cashPnl`, `redeemable` | limit 500 |
| `data-api.polymarket.com/traded?user=` | count of distinct markets traded | |
| `gamma-api.polymarket.com/markets?condition_ids=..` | market metadata incl. `endDate`, `closedTime`, `gameStartTime`, `eventDate`, series, `feesEnabled` | multiple `condition_ids` per call |

Notable: many 2026 markets have `feesEnabled: true` (taker fees), and wallets receive `REWARD` activity (liquidity rewards / maker rebates) — both materially change the economics of high-frequency and near-certain ("0.99") strategies.

## 1. Universe and screening funnel

**Pull (2026-09-26):** overall PnL leaderboard top-1000 for each of DAY / WEEK / MONTH / ALL, top-200 of each of 10 category boards for WEEK / MONTH / ALL, and top-200 volume boards → **10,600 rows, 5,192 unique wallets** (`data/leaderboard/leaderboard_raw.csv`, legacy board in `lbapi_profit.csv`).

**Cheap screen (all 5,192 wallets):** daily cumulative PnL series (`user-pnl-api`) + distinct-markets count (`/traded`) → `pnl_series_daily.jsonl`, `screen_metrics.csv`. Metrics: all-time PnL, 30d/90d PnL, share of *active* weeks (|ΔPnL|>$1) that were profitable, best-day share of total PnL, top-3-day share, max drawdown / PnL, R² of cumulative PnL vs. time, annualised daily Sharpe.

### Survivorship / "leaderboard is a lottery ticket" evidence

| Board (top-1000) | share with **negative all-time PnL** | median share of profitable weeks | share whose single best day > 50% of all-time PnL |
|---|---|---|---|
| DAY | **38.4%** | 0.55 | 22.5% |
| WEEK | 22.6% | 0.64 | 25.1% |
| MONTH | 13.7% | 0.67 | 27.0% |
| ALL | 0% (by construction) | 0.67 | 27.0% |

- More than a third of today's top-1000 winners are lifetime losers; a daily/weekly board is mostly noise. Example: `stupid22` (0x8afa…6adb6) is #1 on the MONTH *weather* board (+$68k) but is **−$101k all-time** (−$117k in politics). Category/window boards must never be taken at face value.
- ~1 in 4 all-time-top wallets made more than half of their lifetime PnL on one day → "lucky whale / single event" profile.
- Survivorship bias: we only see wallets that are *currently* on a board. Wallets running the same strategies that blew up or stopped are invisible, so any strategy's apparent hit-rate is an upper bound.

**Consistency filter** (PnL > $3k, ≥ 8 active weeks, ≥ 30 markets, ≥ 70% profitable active weeks, best day ≤ 20% of PnL, max drawdown ≤ 50% of PnL, still active in last 30d) → **532 wallets** (`screen_consistent_candidates.csv`). Ranked by a composite (rank-average of profitable-week share, last-26-week share, daily Sharpe, R², longevity, 1 − best-day share). The extreme-Sharpe end (daily Sharpe 20–45, 100k+ markets, e.g. crypto boards) is dominated by bots — flagged later.

**Deep-fetch set:** top-110 composite + top-6 per best category + 30 smaller-PnL consistent wallets (< $60k) + 24 whales for contrast (ALL rank ≤ 15 or MONTH rank ≤ 10) → **146 wallets**. Per wallet: last ≤ 4,000 activity events, taker-only trades (to flag maker vs taker fills), up to 3,000 most-recent closed positions + top/bottom-50 by realized PnL (full history), open positions, all-time PnL by category (leaderboard `user=` filter), profile (`data/leaderboard/wallets/<addr>.json.gz`).

## 2. Three accounting facts that change how every leaderboard number must be read

1. **Leaderboard / profile PnL EXCLUDES liquidity rewards and fee rebates.** `user-pnl-api` (and `v1/leaderboard`, which matches it: e.g. `0x30fb41…` MONTH −$61k on the board vs −$54k in the 30-day series) does not move when `REWARD`, `MAKER_REBATE` or `TAKER_REBATE` USDC is paid (payouts land 00:00–00:45 UTC daily):
   - `0x510f49…` (PPMT): ~$270/day of reward+rebate paid in the 00:00–01:00 UTC hour with **zero trades in that hour**; hourly PnL deltas in those hours were −42, +59, +27, +13, +4, +18, +7.
   - `0x30fb41…` (tradetosurvive1): $4.1–4.8k REWARD at 00:00 UTC each day; PnL delta in those hours −383…+37.
   - `0xb55fa1…` (crypto bot): $3.0–6.4k TAKER_REBATE at 00:10 UTC; PnL deltas −2.2k…+1.1k (no jump).
   - `0x04586f…` (I---I, $434 positions): $29–48 REWARD per day; hourly PnL deltas +3.5, +19, −34, −0.3.
   ⇒ *True economic PnL = board PnL + rewards + rebates.* LP farmers can be net-profitable while showing losses (Dr.PNL `0xc602e3…`: board −$178k/month, rewards +$192k/month), and rebate-driven crypto bots are *more* profitable than they look (e.g. Polkadot-Frog `0x9d57c4…`: rewards+rebates ≈ 1.06× its board PnL). Consistency metrics in §1 are therefore metrics of *trading* PnL.
2. **Taker fees are now material on most markets.** Empirically (fills' `usdcSize` vs `size×price`) the taker fee is **`rate × p × (1−p)` per share**, i.e. `rate × (1−p)` of notional. Gamma `feeSchedule` rates seen in our 35.6k-market sample: crypto 0.07 (rebate 20%), weather/sports/esports 0.05 (sports/esports rebate 15%, weather 25%), politics/mentions/finance/tech/culture mostly 0.04 (rebate 25%); a minority of markets have fees disabled. Consequences: a taker buy at 0.50 costs 2.0–2.5% of notional, at 0.10 costs 3.6–4.5%, at 0.97 only ~0.15%. Makers pay nothing and receive a share of taker fees as `MAKER_REBATE`. **Mid-price taker strategies need >2% edge per trade just to break even; near-certain (≥0.95) taker buys are almost fee-free.**
3. **Activity event types** include `TRADE, REDEEM, MERGE, SPLIT, CONVERSION` (neg-risk), `REWARD` (liquidity rewards), `MAKER_REBATE`, `TAKER_REBATE` (volume rebate paid to some high-volume takers — large for crypto up/down bots), `YIELD`, `REFERRAL_REWARD`. Wallets that buy both sides and `MERGE`/`SPLIT` show huge offsetting per-outcome realized PnL in `closed-positions`; concentration must be computed **netted per market** (done below).

## 3. Deep-dive of 146 wallets: rule-based archetypes

Files: `deep_metrics.csv` (119 metrics/wallet), `deep_metrics_archetypes.csv`, `archetype_summary.csv`, `timing_metrics.csv` + `calibration_by_price.csv` (61 small-capital candidates, joined to 35.6k gamma markets in `gamma_markets.jsonl`).

Metric notes: *position* = cost basis per market (closed+open, ≤3,000 most recent closed positions); *PnL concentration* = realized PnL of top-1/top-5 markets (netted over both outcomes, from full-history top/bottom-50 + recent sample) ÷ all-time PnL; *edge* = hold-to-resolution value of the buys in the activity window: Σ(size·1[won]) − Σ(usdc paid incl. taker fee), per $ bought (ignores later sells, so it understates edge of wallets that scalp and exit); *speed flag* = >1,000 fills/day, or median hold <0.1 h with >50% taker $, or HFT archetype. Assignment rules are in `s8_archetypes.py` logic (whale test first, then category/price/frequency).

| archetype | n | median PnL | median % profitable weeks | median markets | median mkt win-rate | median position $ | median fills/day | median entry px | median taker $ share | median hold (h) | rewards+rebates / PnL | median top-5 share | speed-flagged | hold-to-res. edge (¢/$) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. Weather nowcast / near-certain harvest | 7 | $24k | 95% | 2,210 | 98% | 150 | 47 | 0.99 | 65% | 0.9 | 0% | 10% | 14% | +2.7 |
| B. Weather forecast bracket trading | 6 | $21k | 85% | 1,540 | 45% | 47 | 58 | 0.24 | 72% | 13.3 | 3% | 21% | 0% | +6.0 |
| C. Mentions / count markets | 6 | $28k | 90% | 1,266 | 53% | 92 | 34 | 0.45 | 75% | 6.1 | 2% | 18% | 17% | +10.8 |
| D. In-play sports/esports trading | 13 | $193k | 96% | 2,010 | 74% | 57 | 104 | 0.51 | 59% | 0.5 | 2% | 16% | 23% (all latency-sensitive) | +10.3 |
| E. Sports end-of-game 0.99 harvest | 12 | $164k | 98% | 1,446 | 95% | 724 | 212 | 1.00 | 20% | 1.0 | 1% | 16% | 0% (but see text) | +0.3 |
| F2. Event near-certain ("No at 0.9x") | 10 | $43k | 87% | 2,476 | 88% | 708 | 40 | 0.93 | 34% | 36.5 | 1% | 21% | 0% | +5.2 |
| F. Niche event/value generalist | 21 | $71k | 90% | 1,691 | 70% | 109 | 64 | 0.47 | 64% | 93.8 | 5% | 19% | 0% | +5.2 |
| G. Crypto up/down HFT & rebate bots | 29 | $244k | 95% | 71,004 | 42% | 37 | 3,179 | 0.47 | 70% | 0.1 | 25% | 3% | 100% | +4.3 |
| H. High-frequency market making | 17 | $305k | 93% | 24,899 | 51% | 242 | 1,668 | 0.51 | 69% | 2.2 | 15% | 7% | 100% | +2.4 |
| X. Lucky whale / concentrated | 26 | $7.5M | (few weeks) | 18 | 72% | 78,838 | 114 | 0.58 | 68% | 5.1 | 1% | 101% | 12% | |

Representative members: A: HighTempTation `0x6011…`, Weatherstappen `0xb901…`, bhuumi `0x937b…`, wuxiuming `0x9196…`, LittleBitBadBoy `0x0335…`, Kanonenrohr `0x3f4a…`, FuuUuUu `0x2d44…`. B: BeefSlayer `0x331b…`, jjavi `0x6ff2…`, securebet `0xaa7a…`, CreamCream1215 `0x01ce…`, hlwp229 `0x76f4…`, AzerTpn `0xb3b4…`. C: Quarrelsome-Branch `0x0cb1…`, BipBop `0x9ba4…`, startrader `0xd317…`, Jackybrown `0x7505…`, EffyBig `0xb0cc…`, oidocrop `0x23c4…`. D: geiyecapixie, ewww1, leegunner, roberto73, mishipolis, howtoplaydota, jack.jr, chicken689, milktea3. E: trgparking, 0xB595…, qwe258, Rock.San, RIPabloEscobar, avonking, ilushin, LhordGryffin. G: Bonereaper, 0xb55fa1…, drfc4eybh7i8, gabagool-style both-sides bots. H: RN1, e46m3, Flaznorp, BookWarrior, 0x496f76… (weather MM bot, 8k fills/day).

### 3.1 Excluded "lucky whale" profiles (for contrast)

| wallet | name | all-time PnL | markets | top-5 share | median position | best day share |
|---|---|---|---|---|---|---|
| `0x56687bf447db6ffa42ffe2204a05edaa20f55839` | Theo4 | $22.1M | 14 | 99% | $103,237 | – |
| `0x1f2dd6d473f3e824cd2f8a89d9c69fb96f6ad0cf` | Fredi9999 | $16.6M | 45 | 94% | $54,439 | – |
| `0x96cfcb0c30942cfcd1cdf76c7d408794d66b1acb` | mintblade | $9.2M | 5 | 99% | $667,332 | 87% |
| `0xed64a7bf029040aa331abc87902434d815ef217d` | fishalive | $9.1M | 2 | 99% | $2,141,006 | – |
| `0xbc11a64ab34a03a043fbe80598fa065ee87eeec6` | frostrizz | $8.9M | 5 | 99% | $2,033,522 | 65% |
| `0x78b9ac44a6d7d7a076c14e0ad518b301b63c6b76` | Len9311238 | $8.7M | 7 | 99% | $600,974 | – |
| `0x664ce9fb97ae1bbd538d7381b2f4e92dab16f49c` | sparklingwater123 | $8.5M | 4 | 102% | $1,150,678 | 51% |
| `0x09b428f7c2b469786286214aa5c90dd9015f7320` | DEEDDIT | $8.1M | 17 | 211% | $1,202,279 | 123% |
| `0x3f87d51f27ba6e19ec52aaeebb68559a839c742c` | GRIMDRIP | $7.6M | 2 | 99% | $3,045,500 | – |
| `0x863134d00841b2e200492805a01e1e2f5defaa53` | RepTrump | $7.5M | 8 | 99% | $165,268 | – |
| `0x5e4c3b5b81171e2ca4ab776ac0d6bba787f9dba2` | endlessFate | $7.4M | 9 | 124% | $849,964 | 49% |

("–" = PnL series too short/flat to measure; >100% top-5 share = the rest of the book lost money.) The MONTH board's current top (vito3corleone, totoro3miyazaki, 00gringo00: $2.5–4.5M from 8–20 markets, $0.4–1M per position) are the same profile. None of this is replicable with small capital and all of it is indistinguishable from luck at n ≤ 20 bets.

### 3.2 Skeptical observations from the deep set
- **Near-certain buyers' consistency is not skill-proof.** E/F2 wallets win 88–99% of markets at 0.93–1.00 average price; one bad resolution erases weeks (e.g. `stupid22` −$117k in politics despite 93% market win-rate; 0xB595… lost $2,960 on a 0.99 tennis favourite that lost; HighTempTation lost $1,924 on a 0.988 "No" in Panama City).
- **Crypto up/down and HF market-making P&L is partly rebates** (median rewards+rebates = 25% and 15% of board PnL, up to >100% for Polkadot-Frog, tmsd-test) and is entirely speed/infra-dependent.
- **Edge decays.** securebet (weather since 2024) made $23.4k but only $0.8k in the last 90 days; jjavi (+$69k May–Aug) made $0 in September; BeefSlayer was flat May–July. Weather edges are being competed away as more bots arrive.
- **"Median position" understates capital** for LPs/near-certain buyers: resting orders lock USDC that is invisible to `/value`; Quarrelsome-Branch has a $32 median position but ~$97k of open positions today.

## 4. Top consistent, small-capital candidates — reverse-engineered

Selection: from the 61 wallets passing the small-capital consistency filter (all-time PnL ≥ $5k, ≥ 80% profitable active weeks, ≥ 200 markets, top-5 share ≤ 45%, median position ≤ $600, rewards < 30% of PnL, still profitable in last 90 d, < 1,500 fills/day), I kept those whose strategy is **not** speed/feed-dependent and can be explained from the data. Ordered by my replicability-for-$100 × consistency judgement. Capital = max(cash trough in the analysed window, current open value).

| # | wallet | name | archetype | all-time PnL | profitable weeks | median pos. | capital est. | edge (¢/$, net of fees) | $100-replicable? |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `0x2d44274747466c0936c3e01d5a5ad6c260d97023` | FuuUuUu | A | $5.4k | 100% of 17 | $73 | $694 | +12.4 | YES (best) |
| 2 | `0x0cb10c40b0776e9ee8cef970af85724654dda76c` | Quarrelsome-Branch | C | $104.4k | 93% of 95 | $32 | $96,681 | +18.5 | YES |
| 3 | `0x4388640a35b4ecebc33f8c73b58a2b988c615050` | Started-with-20-USD | F | $55.1k | 93% of 30 | $22 | $30,577 | +20.5 | YES (started with $20) |
| 4 | `0x9578af80708f271f705e27867dcf6ec653acf066` | KimchiCapital | F | $28.1k | 95% of 38 | $64 | $33,164 | +11.2 | YES |
| 5 | `0x6ff2cb14da8be7eb57541d250a0196c5f295f140` | jjavi | B | $69.0k | 93% of 15 | $44 | $3,761 | +13.3 | YES (needs forecast model; high variance) |
| 6 | `0x919698b19427cbe6945b0dc823f2d9e126a4d934` | wuxiuming | A | $24.4k | 86% of 42 | $9 | $3,029 | +5.2 | YES |
| 7 | `0xb9012e0d9b60d3920286309328b935cdfa609fc4` | Weatherstappen | A | $51.4k | 96% of 26 | $335 | $1,192 | +2.7 | yes (low margin, tail risk) |
| 8 | `0x937bcac3a8a30c07d827ad0550c3fe3a6756bfab` | bhuumi | A | $25.8k | 94% of 33 | $199 | $1,358 | +2.6 | yes (low margin, tail risk) |
| 9 | `0x331bf91c132af9d921e1908ca0979363fc47193f` | BeefSlayer | B | $86.9k | 85% of 53 | $29 | $12,340 | +5.3 | partly |
| 10 | `0xaa7a74b8c754e8aacc1ac2dedb699af0a3224d23` | securebet | B | $23.4k | 85% of 91 | $8 | $669 | +10.8 | yes, but edge decayed |
| 11 | `0xd12f443b6a45225ae65d519a4bdef568d29ce85a` | Hot-Skull | F | $26.9k | 100% of 23 | $44 | $11,819 | +13.2 | YES |
| 12 | `0xa53ba9d683f68602ccd767512d5c862a43824021` | Vagabund97 | F | $26.8k | 83% of 41 | $76 | $4,460 | +24.4 | YES |
| 13 | `0x750545482cf883fcd5e7f7ad8e14d3f61a322978` | Jackybrown | C | $27.7k | 92% of 26 | $347 | $1,739 | +14.8 | model part yes; sniping part is a race |
| 14 | `0x01ced860d8dca5d7987579d2a2635df8520d27a2` | CreamCream1215 | B | $19.1k | 85% of 26 | $90 | $1,341 | +6.7 | yes (as maker) |
| 15 | `0xd3179f7ca7e1313a89aff7f09353c77ebbab025a` | startrader | C | $29.2k | 87% of 55 | $15 | $15,511 | +6.8 | yes, lumpy |
| 16 | `0x76f4765ebc9bdeaeb4af4d27504bff1d4ce782da` | hlwp229 | B | $9.7k | 89% of 9 | $95 | n/a (window starts mid-cycle) | +1.8 | only as maker |
| 17 | `0xc3262aeb0bd81deab067726635f5b5bd39201db1` | X-Rabbit.Sezu | F | $34.6k | 93% of 41 | $115 | $11,154 | +1.8 | yes, low edge |

Each card below is generated from the data (`s9_cards` logic; per-market reconstructions saved in `data/leaderboard/cards/<wallet>_markets.csv`), followed by my interpretation. Example-trade tables show the best, the worst and two typical (median-size) resolved market-sides in the analysed window; "local" = city-local time of first buy for weather markets; PnL = sale proceeds + held shares × outcome − cost.

#### FuuUuUu — `0x2d44274747466c0936c3e01d5a5ad6c260d97023`
- Archetype (rule-based): **A_weather_nowcast_near_certain**; speed flag: False; profile created 2026-04-26
- All-time PnL $5,373 (last 90d $2,855); profitable active weeks 100% of 17; best day 8% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 10.9; rewards+rebates 0% of PnL
- Breadth: 269 markets all-time; market win-rate 93%; top-1/top-5 market share of PnL 4%/16%
- Size: median position $73 (p90 $400); median fill $14.5; est. capital in use ≈ $694 (cash trough in window $694, open value now $24)
- Activity window analysed: 2026-04-26 → 2026-09-26 (153 d, 763 fills, 5 fills/day, 1.8 markets/day)
- Entry prices: median 0.80; $-share of buys ≥0.90: 72%, ≤0.10: 1%, 0.3–0.7: 9%; taker share of $ 79%; exits by selling in 50% of markets; median buy→exit 8.7 h
- Timing/edge: $-weighted median entry 10.9 h before market close; 5% of $ bought in last 6 h before close; weather: 89% bought on the observation day (median local hour 13.8), 11% day-before; hold-to-resolution edge +12.4¢ per $ net of taker fees (+12.8¢ gross; hit rate 97% vs avg price 0.90); taker fees paid ≈ 0.45% of buy $
- Category mix of buys: {'weather': 1.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Tokyo be 25°C on June 18? | No | 2026-06-18 05:32 UTC | 06-18 14:32 local | 0.657 | 393 | held | WON (9.8 h pre-close) | +206 |
| Will the highest temperature in Sao Paulo be 18°C on July 14? | Yes | 2026-07-14 17:57 UTC | 07-14 14:57 local | 0.894 | 161 | sold 100% @ 0.001 | LOST (9.4 h pre-close) | -161 |
| Will the highest temperature in Sao Paulo be 24°C on June 27? | Yes | 2026-06-27 17:58 UTC | 06-27 14:58 local | 0.617 | 70 | sold 100% @ 0.949 | WON (9.6 h pre-close) | +38 |
| Will the highest temperature in Sao Paulo be 25°C on September 12? | No | 2026-09-12 16:32 UTC | 09-12 13:32 local | 0.990 | 71 | held | WON (11.0 h pre-close) | +1 |

  Window reconstruction (272 resolved market-sides): win 93%, total $5,138, median ROI +13.1%, mean ROI +69.0%

**Strategy (A, weather nowcasting):** trades 1–2 daily-high markets per day in tropical/southern cities (Panama City, São Paulo, Tokyo, Buenos Aires, Singapore). Enters on the observation day around 13:00–15:00 local — after most of the daily high has been recorded — buying the bracket side that the live observations make near-certain (72% of $ at ≥0.90), plus occasional mid-price conviction buys (Tokyo 25°C "No" at 0.657 → +$206). Exits by selling at 0.95–0.999 in half the markets. **External info:** live station observations (the resolution source is the Wunderground/airport station) and the short-range forecast for the rest of the afternoon. **Speed:** minutes, not milliseconds. **$100 replicable: YES** — median position $73, ~$700 capital ever needed, 5 fills/day, 17/17 profitable weeks. **Risk:** a late-afternoon spike (São Paulo 18°C "Yes" bought 0.894 → −$161, i.e. one loss ≈ 10 wins).

#### Quarrelsome-Branch — `0x0cb10c40b0776e9ee8cef970af85724654dda76c`
- Archetype (rule-based): **C_mentions_counts**; speed flag: False; profile created 2024-09-27
- All-time PnL $104,378 (last 90d $17,888); profitable active weeks 93% of 95; best day 5% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 7.3; rewards+rebates 4% of PnL
- Breadth: 4255 markets all-time; market win-rate 48%; top-1/top-5 market share of PnL 5%/12%
- Size: median position $32 (p90 $247); median fill $10.8; est. capital in use ≈ $96,681 (cash trough in window $4,323, open value now $96,681)
- Activity window analysed: 2026-07-06 → 2026-09-26 (82 d, 3137 fills, 38 fills/day, 10.8 markets/day)
- Entry prices: median 0.30; $-share of buys ≥0.90: 17%, ≤0.10: 2%, 0.3–0.7: 51%; taker share of $ 66%; exits by selling in 31% of markets; median buy→exit 48.0 h
- Timing/edge: $-weighted median entry 79.6 h before market close; 12% of $ bought in last 6 h before close; 12% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +18.5¢ per $ net of taker fees (+19.7¢ gross; hit rate 64% vs avg price 0.56); taker fees paid ≈ 1.22% of buy $
- Category mix of buys: {'mentions': 0.51, 'politics': 0.22, 'sports': 0.103, 'other': 0.078, 'tech': 0.077, 'finance': 0.007, 'culture': 0.002, 'economics': 0.001, 'crypto': 0.001, 'weather': 0.0, 'esports': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will there be exactly 4 ChatGPT outages in July 2026? | Yes | 2026-07-21 22:06 UTC |  | 0.453 | 764 | held | WON (260.5 h pre-close) | +923 |
| Will there be 5 or more ChatGPT outages in July 2026? | Yes | 2026-07-27 14:06 UTC |  | 0.597 | 1,847 | sold 20% @ 0.286 | LOST (124.5 h pre-close) | -1,667 |
| Will Donald Trump publicly insult Candace Owens by August 31, 2026? | Yes | 2026-07-31 21:55 UTC |  | 0.208 | 37 | sold 34% @ 0.508 | LOST (755.2 h pre-close) | -7 |
| Will MrBeast say "Wedding" or "Married" during his next YouTube video? | No | 2026-07-30 14:44 UTC | -216.3 h vs start | 0.605 | 37 | held | WON (219.4 h pre-close) | +24 |

  Window reconstruction (922 resolved market-sides): win 51%, total $12,748, median ROI +1.0%, mean ROI +35.4%

**Strategy (C/F, research-heavy event trading):** the most durable wallet found — 95 active weeks since Nov 2024, 93% profitable, every calendar month positive, $104k. Diversified small bets ($11 median fill, ~11 markets/day): Trump "will say X this week" mention markets, MrBeast video word markets, ChatGPT-outage counts, Steam/Game Awards, geopolitical deadline markets. Entries ~80 h before close at avg 0.56; holds ~2 days; 66% taker; +18.5¢/$ net. Losses are capped small (worst ≈ −$1.7k). **Info:** base rates from transcripts/past videos, event schedules, status pages. **Not speed dependent. $100 replicable: YES** — skill/time-intensive rather than capital-intensive. Recent slowdown (Sep +$0.6k).

#### Started-with-20-USD — `0x4388640a35b4ecebc33f8c73b58a2b988c615050`
- Archetype (rule-based): **F_niche_event_value**; speed flag: False; profile created 2026-01-29
- All-time PnL $55,122 (last 90d $38,516); profitable active weeks 93% of 30; best day 7% of PnL; max DD/PnL 0.02; daily Sharpe(ann.) 8.9; rewards+rebates 4% of PnL
- Breadth: 3314 markets all-time; market win-rate 59%; top-1/top-5 market share of PnL 3%/11%
- Size: median position $22 (p90 $294); median fill $15.4; est. capital in use ≈ $30,577 (cash trough in window $2,616, open value now $30,577)
- Activity window analysed: 2026-08-09 → 2026-09-26 (48 d, 3090 fills, 65 fills/day, 16.0 markets/day)
- Entry prices: median 0.44; $-share of buys ≥0.90: 7%, ≤0.10: 2%, 0.3–0.7: 52%; taker share of $ 80%; exits by selling in 39% of markets; median buy→exit 93.6 h
- Timing/edge: $-weighted median entry 227.6 h before market close; 3% of $ bought in last 6 h before close; hold-to-resolution edge +20.5¢ per $ net of taker fees (+22.1¢ gross; hit rate 67% vs avg price 0.60); taker fees paid ≈ 1.68% of buy $
- Category mix of buys: {'other': 0.515, 'sports': 0.147, 'economics': 0.119, 'finance': 0.087, 'politics': 0.05, 'tech': 0.047, 'crypto': 0.01, 'weather': 0.01, 'culture': 0.009, 'crypto_updown': 0.006, 'mentions': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the 30-year Treasury yield hit 5.45% in September? | Yes | 2026-09-23 14:43 UTC |  | 0.124 | 316 | sold 33% @ 0.598 | WON (31.2 h pre-close) | +1,899 |
| Will it rain during the Dutch Grand Prix? | No | 2026-08-11 18:55 UTC |  | 0.803 | 2,294 | sold 37% @ 0.743 | LOST (320.9 h pre-close) | -1,516 |
| Will Revolut's valuation hit (HIGH) $115B by August 31? | No | 2026-08-14 17:08 UTC |  | 0.166 | 85 | held | LOST (151.1 h pre-close) | -85 |
| Will Epic Games' valuation hit (LOW) $12B by August 31? | No | 2026-08-25 17:15 UTC |  | 0.865 | 87 | held | WON (174.1 h pre-close) | +14 |

  Window reconstruction (610 resolved market-sides): win 51%, total $16,602, median ROI +4.0%, mean ROI +12.7%

**Strategy (F, niche generalist) — the best small-start existence proof:** first trades Jan–Mar 2026 were **$1–$13** bets on F1 practice "fastest lap" markets; cumulative PnL −$11 (Feb) → $0.2k (Mar) → $7.8k (May) → $27k (Jul) → **$55k (Sep)**, every month positive since March. Now trades low-attention markets where public data leads the price: ORNN GPU-rental price-index brackets, "Will it rain during the Dutch GP", Treasury-yield "hit" markets (30y 5.45% "Yes" at 0.12 → +$1,899), private-company valuation markets (Revolut, Epic, Lambda), F1 fastest-lap/podium. Entries ~9 days before close, avg price 0.60, 80% taker (≈1.7% fees), +20.5¢/$ net. **Not speed dependent. $100 replicable: YES** — the archetype to copy; the edge is breadth of niche knowledge + willingness to trade thin markets.

#### KimchiCapital — `0x9578af80708f271f705e27867dcf6ec653acf066`
- Archetype (rule-based): **F_niche_event_value**; speed flag: False; profile created 2025-12-29
- All-time PnL $28,076 (last 90d $16,946); profitable active weeks 95% of 38; best day 7% of PnL; max DD/PnL 0.07; daily Sharpe(ann.) 5.1; rewards+rebates 4% of PnL
- Breadth: 1289 markets all-time; market win-rate 80%; top-1/top-5 market share of PnL 4%/15%
- Size: median position $64 (p90 $774); median fill $22.6; est. capital in use ≈ $33,164 (cash trough in window $1,125, open value now $33,164)
- Activity window analysed: 2026-06-02 → 2026-09-26 (116 d, 2799 fills, 24 fills/day, 6.8 markets/day)
- Entry prices: median 0.74; $-share of buys ≥0.90: 43%, ≤0.10: 0%, 0.3–0.7: 17%; taker share of $ 79%; exits by selling in 34% of markets; median buy→exit 125.1 h
- Timing/edge: $-weighted median entry 159.8 h before market close; 8% of $ bought in last 6 h before close; hold-to-resolution edge +11.2¢ per $ net of taker fees (+11.8¢ gross; hit rate 92% vs avg price 0.84); taker fees paid ≈ 0.64% of buy $
- Category mix of buys: {'other': 0.305, 'culture': 0.271, 'politics': 0.181, 'tech': 0.121, 'finance': 0.05, 'economics': 0.027, 'sports': 0.025, 'crypto': 0.013, 'mentions': 0.006}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will "I Knew It, I Knew You - Taylor Swift" be the Billboard Hot 100 # | Yes | 2026-08-09 12:31 UTC | +47.4 h vs start | 0.631 | 1,696 | sold 2% @ 0.950 | WON (202.7 h pre-close) | +989 |
| Will "Don't Look Down" - Rod Wave first week album sales be between 10 | Yes | 2026-08-31 17:55 UTC |  | 0.708 | 821 | held | LOST (100.6 h pre-close) | -821 |
| Will "Janice STFU - Drake" be the #1 song on US Spotify this week? | No | 2026-06-19 22:10 UTC | -62.6 h vs start | 0.980 | 61 | sold 100% @ 0.998 | WON (165.3 h pre-close) | +1 |
| Will "Babydoll - Dominic Fike" be the #1 song on Spotify this week? | No | 2026-06-06 02:39 UTC |  | 0.914 | 61 | held | WON (161.3 h pre-close) | +6 |

  Window reconstruction (657 resolved market-sides): win 76%, total $15,921, median ROI +9.0%, mean ROI +10.3%

**Strategy (F, music-chart & culture data):** Billboard Hot 100 #1, Spotify weekly #1, first-week album sales brackets, plus politics/tech. Buys ~1 week before close at avg 0.84 (Taylor Swift Hot-100 #1 "Yes" at 0.63 → +$989); 92% hit rate on resolved buys; 95% profitable weeks over 38. **Info:** Spotify daily charts / Kworb, chart-tracker accounts, sales projections (HITS Daily Double) that are public days before the official chart. **Not speed dependent. $100 replicable: YES.**

#### jjavi — `0x6ff2cb14da8be7eb57541d250a0196c5f295f140`
- Archetype (rule-based): **B_weather_forecast_brackets**; speed flag: False; profile created 2026-05-17
- All-time PnL $69,029 (last 90d $51,398); profitable active weeks 93% of 15; best day 8% of PnL; max DD/PnL 0.04; daily Sharpe(ann.) 9.8; rewards+rebates 3% of PnL
- Breadth: 2108 markets all-time; market win-rate 25%; top-1/top-5 market share of PnL 7%/27%
- Size: median position $44 (p90 $384); median fill $0.5; est. capital in use ≈ $3,761 (cash trough in window $3,761, open value now $0)
- Activity window analysed: 2026-08-13 → 2026-09-26 (19 d, 3935 fills, 210 fills/day, 9.7 markets/day)
- Entry prices: median 0.05; $-share of buys ≥0.90: 0%, ≤0.10: 11%, 0.3–0.7: 54%; taker share of $ 73%; exits by selling in 23% of markets; median buy→exit 23.0 h
- Timing/edge: $-weighted median entry 26.5 h before market close; 0% of $ bought in last 6 h before close; weather: 46% bought on the observation day (median local hour 10.9), 54% day-before; hold-to-resolution edge +13.3¢ per $ net of taker fees (+15.5¢ gross; hit rate 35% vs avg price 0.34); taker fees paid ≈ 2.24% of buy $
- Category mix of buys: {'weather': 1.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Paris be 31°C on August 15? | Yes | 2026-08-14 16:41 UTC | 08-14 18:41 local | 0.052 | 210 | held | WON (29.7 h pre-close) | +3,842 |
| Will the highest temperature in Paris be 26°C on August 18? | Yes | 2026-08-17 19:08 UTC | 08-17 21:08 local | 0.399 | 953 | held | LOST (27.2 h pre-close) | -953 |
| Will the highest temperature in Paris be 39°C on August 14? | Yes | 2026-08-14 10:20 UTC | 08-14 12:20 local | 0.697 | 102 | held | WON (12.1 h pre-close) | +44 |
| Will the highest temperature in Madrid be 33°C on August 16? | Yes | 2026-08-16 10:34 UTC | 08-16 12:34 local | 0.069 | 100 | held | LOST (11.8 h pre-close) | -100 |

  Window reconstruction (182 resolved market-sides): win 25%, total $5,382, median ROI -100.0%, mean ROI +36.4%

**Strategy (B, forecast-driven tail brackets):** Paris, Munich, London, Milan, Amsterdam, Madrid, NYC. 54% of $ bought the day *before*, the rest on the morning of the day (median 10:54 local). Places ladders of tiny maker bids (median fill $0.51) at 1–5¢ on tail brackets and larger buys at 0.2–0.6 on the forecast-favoured bracket. Only 25% of markets win, but winners pay 20–100×: Munich 24°C "Yes" avg 0.8¢ → +$4,883; Paris 31°C at 5.2¢ (bought 18:41 the evening before) → +$3,842. **Info:** NWP ensemble forecasts (ECMWF/GFS/ICON) vs. market-implied distribution — the market systematically under-prices forecast-model tails. **Not speed dependent** (entries ~26 h before close). **$100 replicable: yes** via $0.5–$5 ladders, but high variance and it needs a calibrated forecast model; note the wallet earned $69k May–Aug and **nothing in September** (edge decay or pause).

#### wuxiuming — `0x919698b19427cbe6945b0dc823f2d9e126a4d934`
- Archetype (rule-based): **A_weather_nowcast_near_certain**; speed flag: False; profile created 2025-11-13
- All-time PnL $24,376 (last 90d $10,662); profitable active weeks 86% of 42; best day 3% of PnL; max DD/PnL 0.02; daily Sharpe(ann.) 11.7; rewards+rebates 1% of PnL
- Breadth: 3972 markets all-time; market win-rate 53%; top-1/top-5 market share of PnL 2%/8%
- Size: median position $9 (p90 $223); median fill $2.4; est. capital in use ≈ $3,029 (cash trough in window $3,029, open value now $0)
- Activity window analysed: 2026-08-05 → 2026-09-26 (49 d, 3672 fills, 75 fills/day, 18.0 markets/day)
- Entry prices: median 0.23; $-share of buys ≥0.90: 84%, ≤0.10: 1%, 0.3–0.7: 6%; taker share of $ 55%; exits by selling in 54% of markets; median buy→exit 4.0 h
- Timing/edge: $-weighted median entry 10.8 h before market close; 0% of $ bought in last 6 h before close; weather: 100% bought on the observation day (median local hour 13.8), 0% day-before; hold-to-resolution edge +5.2¢ per $ net of taker fees (+5.5¢ gross; hit rate 95% vs avg price 0.92); taker fees paid ≈ 0.32% of buy $
- Category mix of buys: {'weather': 1.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Shenzhen be 35°C on August 13? | No | 2026-08-13 06:01 UTC | 08-13 14:01 local | 0.831 | 1,858 | held | WON (10.7 h pre-close) | +377 |
| Will the highest temperature in Beijing be 31°C on August 19? | Yes | 2026-08-19 07:02 UTC | 08-19 15:02 local | 0.449 | 448 | held | LOST (9.4 h pre-close) | -448 |
| Will the highest temperature in Shenzhen be 32°C on August 19? | Yes | 2026-08-19 02:49 UTC | 08-19 10:49 local | 0.084 | 5 | sold 55% @ 0.054 | LOST (13.8 h pre-close) | -3 |
| Will the highest temperature in Shanghai be 30°C on August 13? | Yes | 2026-08-13 02:38 UTC | 08-13 10:38 local | 0.044 | 5 | sold 29% @ 0.038 | LOST (13.7 h pre-close) | -3 |

  Window reconstruction (1012 resolved market-sides): win 48%, total $2,938, median ROI -3.4%, mean ROI +10.1%

**Strategy (A, China cities):** Shenzhen, Shanghai, Guangzhou, Qingdao, Beijing, Wuhan, Chengdu, Chongqing (+ Hong Kong). 100% of buys on the observation day, median 13:50 local; 84% of $ at ≥0.90 but ~half the *fills* are $1–5 lottery tickets at 1–10¢ on neighbouring brackets (cheap convexity). 86% profitable weeks over 42 weeks, +5.2¢/$. **Info:** CMA / airport METAR observations; Chinese-language local sources may be the edge (less competition). **$100 replicable: yes.**

#### Weatherstappen — `0xb9012e0d9b60d3920286309328b935cdfa609fc4`
- Archetype (rule-based): **A_weather_nowcast_near_certain**; speed flag: False; profile created 2025-06-01
- All-time PnL $51,436 (last 90d $16,384); profitable active weeks 96% of 26; best day 4% of PnL; max DD/PnL 0.02; daily Sharpe(ann.) 14.3; rewards+rebates 0% of PnL
- Breadth: 2210 markets all-time; market win-rate 99%; top-1/top-5 market share of PnL 3%/8%
- Size: median position $335 (p90 $1,188); median fill $17.1; est. capital in use ≈ $1,192 (cash trough in window $1,192, open value now $2)
- Activity window analysed: 2026-08-02 → 2026-09-26 (55 d, 3988 fills, 73 fills/day, 10.8 markets/day)
- Entry prices: median 0.99; $-share of buys ≥0.90: 92%, ≤0.10: 0%, 0.3–0.7: 1%; taker share of $ 66%; exits by selling in 99% of markets; median buy→exit 0.1 h
- Timing/edge: $-weighted median entry 10.4 h before market close; 0% of $ bought in last 6 h before close; weather: 100% bought on the observation day (median local hour 14.0), 0% day-before; hold-to-resolution edge +2.7¢ per $ net of taker fees (+2.9¢ gross; hit rate 99% vs avg price 0.97); taker fees paid ≈ 0.14% of buy $
- Category mix of buys: {'weather': 1.0, 'other': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Milan be 25°C on September 12? | No | 2026-09-12 15:50 UTC | 09-12 17:50 local | 0.382 | 458 | sold 100% @ 0.998 | WON (7.0 h pre-close) | +739 |
| Will the highest temperature in Manila be 32°C on September 20? | No | 2026-09-20 04:40 UTC | 09-20 12:40 local | 0.995 | 1,194 | sold 100% @ 0.618 | LOST (14.8 h pre-close) | -452 |
| Will the highest temperature in Milan be 24°C on September 22? | No | 2026-09-22 13:50 UTC | 09-22 15:50 local | 0.988 | 403 | sold 100% @ 0.999 | WON (9.0 h pre-close) | +4 |
| Will the highest temperature in Houston be between 94-95°F on August 2 | No | 2026-08-02 18:55 UTC | 08-02 13:55 local | 0.979 | 403 | sold 100% @ 0.999 | WON (11.3 h pre-close) | +8 |

  Window reconstruction (589 resolved market-sides): win 99%, total $9,790, median ROI +0.9%, mean ROI +2.4%

**Strategy (A, 0.99 harvest with capital recycling):** EU (Munich, Milan), Karachi, Singapore, Ankara, Toronto. Around 14:00 local on the observation day buys "No" at 0.98–0.995 on brackets that the observed max has already ruled out (or makes practically unreachable), frequently via resting 0.99 bids, then **sells at 0.999 minutes later** (99% of markets exited by sale, median hold 0.1 h) — i.e. it harvests ~0.5–1% per turn and recycles ~$1.2k of capital many times a day. 99% market win-rate; losses when a "dead" bracket revives (Manila 32°C "No" at 0.995 → −$452; Munich 14°C −$906). **$100 replicable:** mechanically yes, but income ∝ capital × turns and tail losses are −100% of a position; must restrict to brackets that are *physically* dead (below the already-observed max for "highest" markets).

#### bhuumi — `0x937bcac3a8a30c07d827ad0550c3fe3a6756bfab`
- Archetype (rule-based): **A_weather_nowcast_near_certain**; speed flag: False; profile created 2026-02-02
- All-time PnL $25,784 (last 90d $9,006); profitable active weeks 94% of 33; best day 5% of PnL; max DD/PnL 0.18; daily Sharpe(ann.) 5.9; rewards+rebates 0% of PnL
- Breadth: 4897 markets all-time; market win-rate 99%; top-1/top-5 market share of PnL 3%/10%
- Size: median position $199 (p90 $991); median fill $47.5; est. capital in use ≈ $1,358 (cash trough in window $1,358, open value now $0)
- Activity window analysed: 2026-07-11 → 2026-09-26 (77 d, 3581 fills, 47 fills/day, 11.5 markets/day)
- Entry prices: median 0.99; $-share of buys ≥0.90: 95%, ≤0.10: 0%, 0.3–0.7: 0%; taker share of $ 65%; exits by selling in 98% of markets; median buy→exit 0.7 h
- Timing/edge: $-weighted median entry 12.3 h before market close; 1% of $ bought in last 6 h before close; weather: 100% bought on the observation day (median local hour 12.6), 0% day-before; hold-to-resolution edge +2.6¢ per $ net of taker fees (+2.8¢ gross; hit rate 100% vs avg price 0.97); taker fees paid ≈ 0.12% of buy $
- Category mix of buys: {'weather': 1.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Buenos Aires be 15°C on July 14? | No | 2026-07-14 20:04 UTC | 07-14 17:04 local | 0.781 | 781 | sold 100% @ 0.998 | WON (7.3 h pre-close) | +217 |
| Will the lowest temperature in Atlanta be between 72-73°F on August 27 | No | 2026-08-27 13:32 UTC | 08-27 09:32 local | 0.990 | 95 | sold 73% @ 0.998 | LOST (15.8 h pre-close) | -25 |
| Will the highest temperature in Cape Town be 16°C on August 17? | No | 2026-08-17 10:55 UTC | 08-17 12:55 local | 0.994 | 118 | sold 100% @ 0.998 | WON (11.4 h pre-close) | +0 |
| Will the highest temperature in Amsterdam be 23°C on July 25? | No | 2026-07-25 08:50 UTC | 07-25 10:50 local | 0.990 | 117 | sold 100% @ 0.997 | WON (13.9 h pre-close) | +1 |

  Window reconstruction (886 resolved market-sides): win 99%, total $6,338, median ROI +0.9%, mean ROI +1.2%

**Strategy (A):** same template as Weatherstappen across ~12 cities/day worldwide (4,897 markets all-time), entries ~12:30 local, avg price 0.97, 100% hit-rate on resolved buys in the window, exits at 0.997–0.998. Edge ≈ +2.6¢/$ held to resolution, +0.9% median per market. 94% profitable weeks over 33. **$100 replicable: yes** (fills of $50–$100), but only ~1% per turn; the capital-recycling speed matters more than prediction.

#### BeefSlayer — `0x331bf91c132af9d921e1908ca0979363fc47193f`
- Archetype (rule-based): **B_weather_forecast_brackets**; speed flag: False; profile created 2025-09-17
- All-time PnL $86,903 (last 90d $19,818); profitable active weeks 85% of 53; best day 5% of PnL; max DD/PnL 0.02; daily Sharpe(ann.) 7.6; rewards+rebates 0% of PnL
- Breadth: 2556 markets all-time; market win-rate 51%; top-1/top-5 market share of PnL 6%/20%
- Size: median position $29 (p90 $313); median fill $0.1; est. capital in use ≈ $12,340 (cash trough in window $8,188, open value now $12,340)
- Activity window analysed: 2026-09-07 → 2026-09-26 (19 d, 3726 fills, 199 fills/day, 15.1 markets/day)
- Entry prices: median 0.01; $-share of buys ≥0.90: 41%, ≤0.10: 11%, 0.3–0.7: 23%; taker share of $ 71%; exits by selling in 35% of markets; median buy→exit 17.6 h
- Timing/edge: $-weighted median entry 29.7 h before market close; 0% of $ bought in last 6 h before close; weather: 92% bought on the observation day (median local hour 5.5), 8% day-before; hold-to-resolution edge +5.3¢ per $ net of taker fees (+6.5¢ gross; hit rate 64% vs avg price 0.58); taker fees paid ≈ 1.12% of buy $
- Category mix of buys: {'weather': 1.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Seattle be 63°F or below on September  | Yes | 2026-09-19 15:43 UTC | 09-19 08:43 local | 0.010 | 7 | sold 85% @ 0.991 | WON (16.9 h pre-close) | +684 |
| Will the highest temperature in Houston be between 92-93°F on Septembe | Yes | 2026-09-11 19:22 UTC | 09-11 14:22 local | 0.789 | 264 | held | LOST (10.9 h pre-close) | -264 |
| Will the highest temperature in Austin be between 94-95°F on September | Yes | 2026-09-22 05:59 UTC | 09-22 00:59 local | 0.030 | 15 | held | LOST (24.3 h pre-close) | -15 |
| Will the highest temperature in Chicago be between 78-79°F on Septembe | Yes | 2026-09-15 02:56 UTC | 09-14 21:56 local | 0.113 | 15 | sold 13% @ 0.100 | LOST (27.3 h pre-close) | -13 |

  Window reconstruction (275 resolved market-sides): win 28%, total $2,325, median ROI -97.8%, mean ROI +56.5%

**Strategy (B + A mix, US cities & tropical storms):** Chicago, Dallas, Seattle, Atlanta, Austin, Houston, NYC daily highs/lows plus hurricane-intensity/landfall markets. Barbell: cheap tail buys (Seattle ≤63°F at 1¢ → sold 0.991, +$684) and 0.95–0.99 near-certain buys; 92% of $ on the observation day with median local hour 05:30 — early-morning entries, when the overnight minimum is known and the day's forecast has been updated. 85% profitable weeks over 53 weeks; flat May–July 2026 (regime/edge change), resumed Aug–Sep. Capital ≈ $8–12k. **$100 replicable: partially** (tails yes; near-certain yes).

#### securebet — `0xaa7a74b8c754e8aacc1ac2dedb699af0a3224d23`
- Archetype (rule-based): **B_weather_forecast_brackets**; speed flag: False; profile created 2024-07-23
- All-time PnL $23,369 (last 90d $832); profitable active weeks 85% of 91; best day 3% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 7.4; rewards+rebates 4% of PnL
- Breadth: 4376 markets all-time; market win-rate 39%; top-1/top-5 market share of PnL 4%/14%
- Size: median position $8 (p90 $58); median fill $2.7; est. capital in use ≈ $669 (cash trough in window $669, open value now $0)
- Activity window analysed: 2026-04-22 → 2026-09-26 (157 d, 3540 fills, 23 fills/day, 3.4 markets/day)
- Entry prices: median 0.15; $-share of buys ≥0.90: 30%, ≤0.10: 4%, 0.3–0.7: 16%; taker share of $ 48%; exits by selling in 65% of markets; median buy→exit 9.1 h
- Timing/edge: $-weighted median entry 15.0 h before market close; 8% of $ bought in last 6 h before close; weather: 84% bought on the observation day (median local hour 10.0), 14% day-before; hold-to-resolution edge +10.8¢ per $ net of taker fees (+11.3¢ gross; hit rate 72% vs avg price 0.70); taker fees paid ≈ 0.49% of buy $
- Category mix of buys: {'weather': 0.926, 'crypto_updown': 0.032, 'sports': 0.024, 'crypto': 0.018, 'other': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the lowest temperature in New York City be between 58-59°F on May | No | 2026-05-06 06:39 UTC | 05-06 02:39 local | 0.490 | 545 | sold 98% @ 0.953 | WON (24.1 h pre-close) | +516 |
| WTI Crude Oil (WTI) Up or Down on May 27? | Up | 2026-05-27 04:06 UTC | +7.1 h vs start | 0.171 | 597 | sold 100% @ 0.113 | LOST (19.0 h pre-close) | -203 |
| Will the highest temperature in Busan be 36°C on August 8? | Yes | 2026-08-07 21:49 UTC | +6.8 h vs start | 0.120 | 11 | sold 100% @ 0.491 | WON (17.6 h pre-close) | +34 |
| Will the highest temperature in San Francisco be between 68-69°F on Ma | No | 2026-05-28 21:38 UTC | 05-28 14:38 local | 0.870 | 11 | sold 100% @ 0.931 | WON (15.0 h pre-close) | +1 |

  Window reconstruction (564 resolved market-sides): win 48%, total $3,154, median ROI -2.1%, mean ROI +25.9%

**Strategy (B, day-of bracket trading, longest record):** NYC, Seoul, Seattle, Atlanta, Shanghai. Enters day-of around 10:00 local at mid-to-high prices (avg 0.70), 52% maker, and **trades out before resolution in 65% of markets** (e.g. NYC low 58–59°F "No" bought 0.49 at 02:39 local, sold 0.953 → +$516). 91 active weeks since mid-2024, 85% profitable, $8 median position, ~$670 capital. **But only +$0.8k in the last 90 days** — a clear example of a small-account weather edge being competed away. **$100 replicable: yes, but the edge may be gone.**

#### Hot-Skull — `0xd12f443b6a45225ae65d519a4bdef568d29ce85a`
- Archetype (rule-based): **F_niche_event_value**; speed flag: False; profile created 2026-04-11
- All-time PnL $26,883 (last 90d $18,656); profitable active weeks 100% of 23; best day 9% of PnL; max DD/PnL 0.06; daily Sharpe(ann.) 7.2; rewards+rebates 3% of PnL
- Breadth: 1054 markets all-time; market win-rate 74%; top-1/top-5 market share of PnL 10%/25%
- Size: median position $44 (p90 $686); median fill $1.4; est. capital in use ≈ $11,819 (cash trough in window $5,991, open value now $11,819)
- Activity window analysed: 2026-07-17 → 2026-09-26 (72 d, 3716 fills, 52 fills/day, 6.0 markets/day)
- Entry prices: median 0.02; $-share of buys ≥0.90: 52%, ≤0.10: 1%, 0.3–0.7: 14%; taker share of $ 77%; exits by selling in 51% of markets; median buy→exit 59.2 h
- Timing/edge: $-weighted median entry 76.8 h before market close; 23% of $ bought in last 6 h before close; hold-to-resolution edge +13.2¢ per $ net of taker fees (+13.6¢ gross; hit rate 96% vs avg price 0.87); taker fees paid ≈ 0.55% of buy $
- Category mix of buys: {'other': 0.368, 'politics': 0.277, 'sports': 0.254, 'tech': 0.072, 'finance': 0.016, 'crypto_updown': 0.007, 'culture': 0.003, 'crypto': 0.001, 'economics': 0.001, 'esports': 0.0, 'mentions': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will Republican Senate incumbents not win in exactly two nominating el | No | 2026-08-04 15:49 UTC |  | 0.830 | 6,980 | sold 29% @ 0.964 | WON (689.2 h pre-close) | +1,344 |
| Who will win the gold medal in Men's Skateboard Vert Best Trick at X G | Yes | 2026-07-25 20:10 UTC |  | 0.626 | 816 | sold 2% @ 0.293 | LOST (10.4 h pre-close) | -808 |
| Trump declassifies new UFO files by September 30? | No | 2026-09-17 19:52 UTC |  | 0.063 | 42 | held | LOST (18.8 h pre-close) | -42 |
| Will ByteDance's valuation hit (HIGH) $850B by July 31? | No | 2026-07-30 17:17 UTC |  | 0.999 | 42 | held | WON (49.7 h pre-close) | +0 |

  Window reconstruction (303 resolved market-sides): win 61%, total $8,305, median ROI +0.6%, mean ROI +10.1%

**Strategy (F, long-tail news/AI/sports niches):** AI-benchmark and arena-score markets, private valuations, obscure elections (São Tomé presidential "Yes" at 0.9986), X Games, chess; mixes near-certain "No" at 0.98+ (52% of $) with value bets. 23/23 profitable weeks, $27k, 96% hit on resolved buys at avg 0.87. **$100 replicable: yes.** Risk: near-certain "No" legs (Claude Code commits ≥750k "Yes" at 0.98 → −$949).

#### Vagabund97 — `0xa53ba9d683f68602ccd767512d5c862a43824021`
- Archetype (rule-based): **F_niche_event_value**; speed flag: False; profile created 2025-12-12
- All-time PnL $26,821 (last 90d $8,128); profitable active weeks 83% of 41; best day 7% of PnL; max DD/PnL 0.15; daily Sharpe(ann.) 5.6; rewards+rebates 15% of PnL
- Breadth: 838 markets all-time; market win-rate 70%; top-1/top-5 market share of PnL 5%/17%
- Size: median position $76 (p90 $445); median fill $3.1; est. capital in use ≈ $4,460 (cash trough in window $2,795, open value now $4,460)
- Activity window analysed: 2026-07-20 → 2026-09-26 (68 d, 3650 fills, 54 fills/day, 5.1 markets/day)
- Entry prices: median 0.48; $-share of buys ≥0.90: 0%, ≤0.10: 2%, 0.3–0.7: 64%; taker share of $ 44%; exits by selling in 63% of markets; median buy→exit 46.6 h
- Timing/edge: $-weighted median entry 181.6 h before market close; 5% of $ bought in last 6 h before close; 94% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +24.4¢ per $ net of taker fees (+25.7¢ gross; hit rate 52% vs avg price 0.45); taker fees paid ≈ 1.46% of buy $
- Category mix of buys: {'finance': 0.546, 'economics': 0.192, 'crypto': 0.124, 'other': 0.096, 'crypto_updown': 0.042, 'politics': 0.001}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will Gold (XAUUSD) hit (HIGH) $4,350 Week of August 3 2026? | Yes | 2026-08-06 00:56 UTC | +75.9 h vs start | 0.210 | 387 | sold 25% @ 0.179 | WON (37.6 h pre-close) | +1,074 |
| Will Gold (XAUUSD) hit (LOW) $3,900 in August? | Yes | 2026-07-31 21:03 UTC | +0.1 h vs start | 0.495 | 1,562 | held | LOST (746.3 h pre-close) | -1,562 |
| Will the price of Bitcoin be between $64,000 and $66,000 on August 7? | No | 2026-08-07 09:25 UTC |  | 0.120 | 72 | held | LOST (6.9 h pre-close) | -72 |
| Will Zcash reach $700 by December 31, 2026? | Yes | 2026-08-21 20:12 UTC |  | 0.887 | 74 | held | WON (2.5 h pre-close) | +9 |

  Window reconstruction (252 resolved market-sides): win 62%, total $6,414, median ROI +5.5%, mean ROI +32.1%

**Strategy (F, finance/economics barrier markets):** gold/BTC/altcoin "hit HIGH/LOW price by date" and economics markets, entered after the window opens (94% of $), avg price 0.45, +24¢/$ net; also a steady LP-reward earner ($1.8k rewards/30d, passes the strict LP-steadiness test in §6). **Info:** spot price + volatility → barrier-hit probability (a simple lognormal model is enough to find mispricings). **$100 replicable: yes.**

#### Jackybrown — `0x750545482cf883fcd5e7f7ad8e14d3f61a322978`
- Archetype (rule-based): **C_mentions_counts**; speed flag: False; profile created 2026-03-24
- All-time PnL $27,730 (last 90d $15,972); profitable active weeks 92% of 26; best day 6% of PnL; max DD/PnL 0.03; daily Sharpe(ann.) 8.6; rewards+rebates 2% of PnL
- Breadth: 272 markets all-time; market win-rate 59%; top-1/top-5 market share of PnL 5%/20%
- Size: median position $347 (p90 $3,013); median fill $29.9; est. capital in use ≈ $1,739 (cash trough in window $1,739, open value now $4)
- Activity window analysed: 2026-06-27 → 2026-09-26 (91 d, 3826 fills, 42 fills/day, 1.5 markets/day)
- Entry prices: median 0.50; $-share of buys ≥0.90: 15%, ≤0.10: 2%, 0.3–0.7: 39%; taker share of $ 92%; exits by selling in 97% of markets; median buy→exit 16.1 h
- Timing/edge: $-weighted median entry 12.4 h before market close; 33% of $ bought in last 6 h before close; 100% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +14.8¢ per $ net of taker fees (+16.5¢ gross; hit rate 68% vs avg price 0.63); taker fees paid ≈ 1.71% of buy $
- Category mix of buys: {'mentions': 0.997, 'sports': 0.002, 'other': 0.001}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will Elon Musk post 200-219 tweets from September 11 to September 18,  | Yes | 2026-09-17 06:35 UTC | +134.6 h vs start | 0.297 | 4,345 | sold 100% @ 0.389 | WON (35.5 h pre-close) | +1,361 |
| Will Elon Musk post <40 tweets from September 5 to September 7, 2026? | No | 2026-09-06 07:33 UTC | +15.6 h vs start | 0.518 | 3,663 | sold 70% @ 0.492 | LOST (34.5 h pre-close) | -1,214 |
| Will Elon Musk post 65-89 tweets from September 3 to September 5, 2026 | Yes | 2026-09-05 06:04 UTC | +38.1 h vs start | 0.849 | 454 | sold 100% @ 0.948 | WON (12.0 h pre-close) | +52 |
| Will Elon Musk post 40-64 tweets from June 29 to July 1, 2026? | No | 2026-07-01 04:58 UTC | +37.0 h vs start | 0.599 | 449 | sold 100% @ 0.418 | LOST (13.6 h pre-close) | -135 |

  Window reconstruction (171 resolved market-sides): win 57%, total $11,449, median ROI +4.0%, mean ROI +2.5%

**Strategy (C, Elon-Musk tweet-count brackets):** 99.8% of volume in "Will Elon post X–Y tweets" markets. Tracks the live post count and (a) takes mid-price positions on the brackets a tweet-rate model favours, exiting by selling (97% of markets), and (b) snipes brackets that just became impossible — e.g. "180–199 tweets" **No** bought 0.94 and sold 0.999 twenty seconds later (+$260). 92% taker. 92% profitable weeks over 26. **Info:** real-time post counter + tweet-rate model. **Speed:** part (b) is a race (seconds); part (a) is model-driven. **$100: part (a) yes.**

#### CreamCream1215 — `0x01ced860d8dca5d7987579d2a2635df8520d27a2`
- Archetype (rule-based): **B_weather_forecast_brackets**; speed flag: False; profile created 2026-03-23
- All-time PnL $19,060 (last 90d $8,649); profitable active weeks 85% of 26; best day 6% of PnL; max DD/PnL 0.07; daily Sharpe(ann.) 7.6; rewards+rebates 2% of PnL
- Breadth: 971 markets all-time; market win-rate 42%; top-1/top-5 market share of PnL 6%/21%
- Size: median position $90 (p90 $440); median fill $10.0; est. capital in use ≈ $1,341 (cash trough in window $1,066, open value now $1,341)
- Activity window analysed: 2026-06-30 → 2026-09-26 (88 d, 3682 fills, 42 fills/day, 4.5 markets/day)
- Entry prices: median 0.34; $-share of buys ≥0.90: 3%, ≤0.10: 3%, 0.3–0.7: 56%; taker share of $ 76%; exits by selling in 73% of markets; median buy→exit 20.4 h
- Timing/edge: $-weighted median entry 32.4 h before market close; 0% of $ bought in last 6 h before close; weather: 80% bought on the observation day (median local hour 11.9), 19% day-before; hold-to-resolution edge +6.7¢ per $ net of taker fees (+8.6¢ gross; hit rate 52% vs avg price 0.52); taker fees paid ≈ 1.93% of buy $
- Category mix of buys: {'weather': 0.997, 'politics': 0.002, 'sports': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the highest temperature in Hong Kong be 32°C on July 4? | Yes | 2026-07-04 01:39 UTC | 07-04 09:39 local | 0.130 | 207 | sold 100% @ 0.856 | WON (49.2 h pre-close) | +1,153 |
| Will Tropical Storm Saudel make landfall in Japan? | Yes | 2026-08-25 10:26 UTC |  | 0.651 | 1,696 | sold 81% @ 0.245 | LOST (230.1 h pre-close) | -1,180 |
| Will the highest temperature in Hong Kong be 29°C on July 27? | Yes | 2026-07-27 06:43 UTC | 07-27 14:43 local | 0.154 | 99 | sold 53% @ 0.223 | LOST (20.1 h pre-close) | -23 |
| Will the highest temperature in Hong Kong be 30°C on August 31? | Yes | 2026-08-31 01:37 UTC | 08-31 09:37 local | 0.400 | 99 | sold 100% @ 0.330 | LOST (25.4 h pre-close) | -17 |

  Window reconstruction (410 resolved market-sides): win 41%, total $6,596, median ROI -27.8%, mean ROI +4.3%

**Strategy (B):** Hong-Kong-centric daily-high brackets, mid prices (0.3–0.7), day-of mornings (~12:00 local) and sells 73% of positions before resolution (HK 32°C "Yes" bought 0.13 → sold 0.856, +$1,153). Paying ~1.9% of notional in taker fees cuts gross edge 8.6¢ → net 6.7¢. One big non-weather loss (tropical-storm landfall −$1,180). 85% profitable weeks over 26. **$100 replicable: yes; use maker orders to avoid the fee.**

#### startrader — `0xd3179f7ca7e1313a89aff7f09353c77ebbab025a`
- Archetype (rule-based): **C_mentions_counts**; speed flag: False; profile created 2025-08-10
- All-time PnL $29,212 (last 90d $9,484); profitable active weeks 87% of 55; best day 7% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 5.9; rewards+rebates 2% of PnL
- Breadth: 773 markets all-time; market win-rate 35%; top-1/top-5 market share of PnL 12%/45%
- Size: median position $15 (p90 $1,742); median fill $7.8; est. capital in use ≈ $15,511 (cash trough in window $15,511, open value now $0)
- Activity window analysed: 2026-05-15 → 2026-09-26 (132 d, 3866 fills, 29 fills/day, 1.9 markets/day)
- Entry prices: median 0.11; $-share of buys ≥0.90: 64%, ≤0.10: 2%, 0.3–0.7: 7%; taker share of $ 57%; exits by selling in 68% of markets; median buy→exit 2.7 h
- Timing/edge: $-weighted median entry 2.2 h before market close; 82% of $ bought in last 6 h before close; 100% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +6.8¢ per $ net of taker fees (+7.3¢ gross; hit rate 92% vs avg price 0.87); taker fees paid ≈ 0.47% of buy $
- Category mix of buys: {'mentions': 0.994, 'tech': 0.006, 'weather': 0.0, 'sports': 0.0, 'other': 0.0, 'crypto_updown': 0.0, 'crypto': 0.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will Elon Musk post 120-139 tweets from June 30 to July 7, 2026? | Yes | 2026-07-07 14:31 UTC | +166.5 h vs start | 0.745 | 7,579 | sold 12% @ 0.044 | WON (3.6 h pre-close) | +1,404 |
| Will Elon Musk post 100-119 tweets from June 30 to July 7, 2026? | Yes | 2026-07-07 12:29 UTC | +164.5 h vs start | 0.863 | 1,164 | sold 29% @ 0.809 | LOST (5.5 h pre-close) | -842 |
| Will Elon Musk post 40-64 tweets from July 25 to July 27, 2026? | No | 2026-07-27 05:36 UTC | +37.6 h vs start | 0.126 | 27 | sold 98% @ 0.078 | LOST (12.5 h pre-close) | -11 |
| Will Elon Musk post 65-89 tweets from June 25 to June 27, 2026? | Yes | 2026-06-27 15:20 UTC | +47.3 h vs start | 0.026 | 26 | sold 100% @ 0.023 | LOST (2.7 h pre-close) | -3 |

  Window reconstruction (295 resolved market-sides): win 42%, total $14,156, median ROI -11.4%, mean ROI -22.9%

**Strategy (C, end-of-window count harvest):** also Elon tweet counts, but 82% of $ bought in the last 6 h at avg 0.87 on the bracket the count is converging to (+ cheap lottery tickets). Large end-of-window bets ($7.6k on one bracket → +$1,404; a $1.2k bet lost −$842 when the count overshot). 87% profitable weeks over 55 but top-5 markets = 45% of PnL (lumpy). **$100:** feasible but the payoff profile (small wins, occasional big loss) needs strict sizing.

#### hlwp229 — `0x76f4765ebc9bdeaeb4af4d27504bff1d4ce782da`
- Archetype (rule-based): **B_weather_forecast_brackets**; speed flag: False; profile created 2026-07-22
- All-time PnL $9,717 (last 90d $9,717); profitable active weeks 89% of 9; best day 6% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 22.1; rewards+rebates 5% of PnL
- Breadth: 364 markets all-time; market win-rate 86%; top-1/top-5 market share of PnL 2%/8%
- Size: median position $95 (p90 $365); median fill $6.8; est. capital in use: not measurable from this window (cash trough ≈ $1 because the window starts with exits of earlier positions)
- Activity window analysed: 2026-08-09 → 2026-09-26 (48 d, 3594 fills, 75 fills/day, 5.9 markets/day)
- Entry prices: median 0.40; $-share of buys ≥0.90: 0%, ≤0.10: 0%, 0.3–0.7: 80%; taker share of $ 92%; exits by selling in 93% of markets; median buy→exit 5.9 h
- Timing/edge: $-weighted median entry 53.5 h before market close; 0% of $ bought in last 6 h before close; weather: 0% bought on the observation day (median local hour 5.4), 100% day-before; hold-to-resolution edge +1.8¢ per $ net of taker fees (+4.2¢ gross; hit rate 44% vs avg price 0.45); taker fees paid ≈ 2.38% of buy $
- Category mix of buys: {'weather': 1.0}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will the lowest temperature in Shanghai be 24°C on September 8? | Yes | 2026-09-06 11:09 UTC | 09-06 19:09 local | 0.381 | 698 | sold 48% @ 0.502 | WON (53.3 h pre-close) | +691 |
| Will the lowest temperature in Seoul (Incheon) be 20°C on September 8? | Yes | 2026-09-06 07:27 UTC | 09-06 16:27 local | 0.249 | 41 | sold 100% @ 0.410 | LOST (55.9 h pre-close) | +26 |
| Will the lowest temperature in Seoul (Incheon) be 18°C on September 11 | No | 2026-09-09 09:02 UTC | 09-09 18:02 local | 0.678 | 41 | held | WON (54.3 h pre-close) | +19 |

  Window reconstruction (440 resolved market-sides): win 63%, total $4,967, median ROI +13.6%, mean ROI +27.1%

**Strategy (B, day-before):** Shanghai/Seoul *lowest*-temperature brackets bought ~2 days before close at mid prices, 92% taker, trades out. Short history (9 weeks, $9.7k). Illustrates the fee problem: gross +4.2¢/$ → **net +1.8¢/$** after 2.4% taker fees. **$100: only as maker.**

#### X-Rabbit.Sezu — `0xc3262aeb0bd81deab067726635f5b5bd39201db1`
- Archetype (rule-based): **F_niche_event_value**; speed flag: False; profile created 2025-12-08
- All-time PnL $34,560 (last 90d $7,221); profitable active weeks 93% of 41; best day 5% of PnL; max DD/PnL 0.05; daily Sharpe(ann.) 6.7; rewards+rebates 5% of PnL
- Breadth: 1466 markets all-time; market win-rate 67%; top-1/top-5 market share of PnL 8%/24%
- Size: median position $115 (p90 $1,172); median fill $9.5; est. capital in use ≈ $11,154 (cash trough in window $3,972, open value now $11,154)
- Activity window analysed: 2026-07-24 → 2026-09-26 (64 d, 3790 fills, 59 fills/day, 5.2 markets/day)
- Entry prices: median 0.42; $-share of buys ≥0.90: 43%, ≤0.10: 1%, 0.3–0.7: 26%; taker share of $ 61%; exits by selling in 76% of markets; median buy→exit 162.3 h
- Timing/edge: $-weighted median entry 457.6 h before market close; 10% of $ bought in last 6 h before close; hold-to-resolution edge +1.8¢ per $ net of taker fees (+2.2¢ gross; hit rate 86% vs avg price 0.85); taker fees paid ≈ 0.58% of buy $
- Category mix of buys: {'tech': 0.638, 'finance': 0.209, 'other': 0.08, 'sports': 0.038, 'politics': 0.03, 'mentions': 0.005}

| market | side | first buy | local / vs start | avg px | $ in | exit | resolved | PnL |
|---|---|---|---|---|---|---|---|---|
| Will Google be the #3 AI Lab at the end of August 2026 (Style Control  | Yes | 2026-08-03 19:20 UTC |  | 0.500 | 707 | sold 56% @ 0.541 | WON (675.3 h pre-close) | +345 |
| Will Francesca Hong win the 2026 Wisconsin Governor Democratic primary | Yes | 2026-08-11 12:39 UTC | -11.3 h vs start | 0.809 | 1,077 | sold 100% @ 0.478 | LOST (31.6 h pre-close) | -441 |
| Will Google be the third-best Math AI lab at the end of August 2026? | Yes | 2026-08-07 12:31 UTC |  | 0.281 | 80 | sold 100% @ 0.413 | LOST (585.9 h pre-close) | +38 |
| Will GPT-6 be released by August 31, 2026? | No | 2026-08-08 08:12 UTC |  | 0.810 | 81 | sold 100% @ 0.852 | WON (573.8 h pre-close) | +4 |

  Window reconstruction (212 resolved market-sides): win 62%, total $1,681, median ROI +1.5%, mean ROI +4.2%

**Strategy (F, AI-leaderboard markets):** LMArena "best AI model/Code Arena/WebDev" end-of-month markets, AI release deadlines, some finance; holds ~1 week, 93% profitable weeks over 41, but window edge only +1.8¢/$. **Info:** LMArena leaderboard snapshots & release rumours. **$100: yes but low edge.**

### 4.1 Contrast cards — consistent but NOT acceptable for us (speed / feed / capital)

#### jack.jr — `0x1985327e5782c62362dbbdf714c423d40d8f51ab`
- Archetype (rule-based): **D_inplay_sports**; speed flag: False; profile created 2026-06-04
- All-time PnL $47,183 (last 90d $44,808); profitable active weeks 100% of 16; best day 4% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 15.7; rewards+rebates 1% of PnL
- Breadth: 1723 markets all-time; market win-rate 82%; top-1/top-5 market share of PnL 2%/7%
- Size: median position $22 (p90 $375); median fill $13.4; est. capital in use ≈ $1,156 (cash trough in window $1,156, open value now $0)
- Activity window analysed: 2026-08-01 → 2026-09-26 (56 d, 3872 fills, 69 fills/day, 21.1 markets/day)
- Entry prices: median 0.51; $-share of buys ≥0.90: 0%, ≤0.10: 0%, 0.3–0.7: 59%; taker share of $ 45%; exits by selling in 98% of markets; median buy→exit 0.0 h
- Timing/edge: $-weighted median entry 2.8 h before market close; 98% of $ bought in last 6 h before close; 100% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +33.9¢ per $ net of taker fees (+35.2¢ gross; hit rate 73% vs avg price 0.57); taker fees paid ≈ 1.26% of buy $
- Category mix of buys: {'sports': 0.729, 'other': 0.27, 'esports': 0.001, 'finance': 0.0}

**CONTRAST — speed/feed-dependent (NOT acceptable):** in-play soccer (exact score, totals, moneylines), buys and sells within ~1 minute (median buy→exit 0.0 h), +34¢/$ with 84% win on resolved market-sides. An edge this large on 1-minute holds in live football is the signature of a faster-than-market live feed (courtsiding/scraped data).

#### roberto73 — `0x5ad5c4608c4661361b91c92e1091d2c5b43c37b9`
- Archetype (rule-based): **D_inplay_sports**; speed flag: False; profile created 2025-10-24
- All-time PnL $238,397 (last 90d $61,091); profitable active weeks 87% of 46; best day 8% of PnL; max DD/PnL 0.03; daily Sharpe(ann.) 7.1; rewards+rebates 1% of PnL
- Breadth: 3413 markets all-time; market win-rate 48%; top-1/top-5 market share of PnL 8%/22%
- Size: median position $4 (p90 $125); median fill $6.9; est. capital in use ≈ $3,565 (cash trough in window $3,565, open value now $0)
- Activity window analysed: 2026-05-09 → 2026-09-26 (135 d, 3366 fills, 25 fills/day, 6.2 markets/day)
- Entry prices: median 0.19; $-share of buys ≥0.90: 0%, ≤0.10: 4%, 0.3–0.7: 47%; taker share of $ 29%; exits by selling in 16% of markets; median buy→exit 2.8 h
- Timing/edge: $-weighted median entry 2.0 h before market close; 96% of $ bought in last 6 h before close; 99% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +39.5¢ per $ net of taker fees (+39.6¢ gross; hit rate 67% vs avg price 0.51); taker fees paid ≈ 0.11% of buy $
- Category mix of buys: {'sports': 0.689, 'other': 0.311, 'politics': 0.0, 'finance': 0.0}

**CONTRAST — in-play maker (NOT acceptable):** resting in-play bids on soccer totals/spreads/moneylines (92% maker), positions up to $12–30k (Norway–England U4.5 +$18k; CSKA Sofia −$6.9k). Requires real-time game state and fast cancel; the "median position $4" hides five-figure bets.

#### HighTempTation — `0x6011655c4afb76f36dd1b08a137a1ba73466b31e`
- Archetype (rule-based): **A_weather_nowcast_near_certain**; speed flag: True; profile created 2026-03-03
- All-time PnL $91,640 (last 90d $66,176); profitable active weeks 95% of 20; best day 4% of PnL; max DD/PnL 0.01; daily Sharpe(ann.) 15.6; rewards+rebates 0% of PnL
- Breadth: 3927 markets all-time; market win-rate 100%; top-1/top-5 market share of PnL 1%/5%
- Size: median position $128 (p90 $597); median fill $75.5; est. capital in use ≈ $1,279 (cash trough in window $1,279, open value now $0)
- Activity window analysed: 2026-08-19 → 2026-09-26 (38 d, 3935 fills, 104 fills/day, 46.9 markets/day)
- Entry prices: median 0.97; $-share of buys ≥0.90: 85%, ≤0.10: 0%, 0.3–0.7: 1%; taker share of $ 91%; exits by selling in 98% of markets; median buy→exit 0.0 h
- Timing/edge: $-weighted median entry 12.3 h before market close; 3% of $ bought in last 6 h before close; weather: 97% bought on the observation day (median local hour 11.0), 3% day-before; hold-to-resolution edge +6.2¢ per $ net of taker fees (+6.5¢ gross; hit rate 99% vs avg price 0.94); taker fees paid ≈ 0.32% of buy $
- Category mix of buys: {'weather': 1.0}

**CONTRAST — weather latency arbitrage:** 91% taker; buys stale asks at 0.90–0.98 the moment an observation update kills a bracket, then sells into 0.99 bids seconds later (e.g. Cape Town 20°C "No" bought 0.9005, sold 0.99 four seconds later). 100% market win-rate, 95% profitable weeks — but it is a race against other bots on observation-feed latency. Flagged as speed-dependent.

#### 0xB595d09Ce5bBc4d39E3b3D04E80C402d2C8D5922-1769777706105 — `0xb595d09ce5bbc4d39e3b3d04e80c402d2c8d5922`
- Archetype (rule-based): **E_endgame_0.99_harvest**; speed flag: False; profile created 2026-01-30
- All-time PnL $454,660 (last 90d $252,487); profitable active weeks 94% of 33; best day 4% of PnL; max DD/PnL 0.05; daily Sharpe(ann.) 10.0; rewards+rebates 1% of PnL
- Breadth: 70555 markets all-time; market win-rate 99%; top-1/top-5 market share of PnL 1%/5%
- Size: median position $56 (p90 $922); median fill $52.0; est. capital in use ≈ $68,502 (cash trough in window $68,502, open value now $14,631)
- Activity window analysed: 2026-09-20 → 2026-09-26 (6 d, 2376 fills, 397 fills/day, 242.1 markets/day)
- Entry prices: median 0.99; $-share of buys ≥0.90: 96%, ≤0.10: 0%, 0.3–0.7: 1%; taker share of $ 27%; exits by selling in 0% of markets; median buy→exit 2.1 h
- Timing/edge: $-weighted median entry 2.1 h before market close; 85% of $ bought in last 6 h before close; 100% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +2.0¢ per $ net of taker fees (+2.1¢ gross; hit rate 99% vs avg price 0.98); taker fees paid ≈ 0.07% of buy $
- Category mix of buys: {'sports': 0.847, 'other': 0.097, 'esports': 0.044, 'economics': 0.009, 'finance': 0.004, 'politics': 0.0}

**CONTRAST — sports end-of-game 0.99 harvest (NOT for us):** 240 markets/day, buys the decided side at 0.99 after the event (85% of $ in last 6 h), +2¢/$, $68k cash trough. Needs live scores, large capital and eats occasional −100% (M15 Telavi tennis 0.99 favourite lost −$2,960).

#### ohioism — `0x361528e242bc6cc789ac8da6fd5cb98046178fdf`
- Archetype (rule-based): **G_crypto_updown_bot**; speed flag: True; profile created 2026-03-29
- All-time PnL $118,792 (last 90d $98,358); profitable active weeks 95% of 21; best day 4% of PnL; max DD/PnL 0.06; daily Sharpe(ann.) 10.4; rewards+rebates 9% of PnL
- Breadth: 52195 markets all-time; market win-rate 60%; top-1/top-5 market share of PnL 1%/4%
- Size: median position $11 (p90 $92); median fill $8.9; est. capital in use ≈ $151 (cash trough in window $115, open value now $151)
- Activity window analysed: 2026-09-23 → 2026-09-26 (3 d, 2269 fills, 850 fills/day, 565.6 markets/day)
- Entry prices: median 0.64; $-share of buys ≥0.90: 18%, ≤0.10: 0%, 0.3–0.7: 28%; taker share of $ 96%; exits by selling in 0% of markets; median buy→exit 0.1 h
- Timing/edge: $-weighted median entry 0.1 h before market close; 100% of $ bought in last 6 h before close; 100% of $ bought after event start (count markets: after counting window opened); hold-to-resolution edge +4.6¢ per $ net of taker fees (+6.4¢ gross; hit rate 76% vs avg price 0.73); taker fees paid ≈ 1.74% of buy $
- Category mix of buys: {'crypto_updown': 1.0}

**CONTRAST — crypto 5/15-min up/down bot (NOT acceptable):** 850 fills/day, 96% taker, entries in the final minutes using spot-price feeds; pays ~1.7% fees and relies on execution speed.

## 5. Strategy archetypes ranked for a small, non-speed account

Scores 1–5 (5 = best for us). Consistency = profitable-week share / drawdown / tail risk; capital efficiency = PnL per $ of capital actually tied up (incl. turnover); replicability = can it run on $100 with 5-share minimum orders and manual/simple tooling; speed dependency: 5 = none, 1 = millisecond race.

| rank | archetype | consistency | capital efficiency | $100 replicability | speed independence | verdict | best examples |
|---|---|---|---|---|---|---|---|
| 1 | **A. Weather nowcast — day-of, afternoon, buy the bracket side already decided by observations** | 5 (95% weeks, 98% market wins; rare −100% reversals) | 4 (1–13¢/$, capital recycled daily; ~$0.7–1.3k supports $5–90k/yr at the top wallets) | 5 (5-share orders, 1–10 markets/day) | 4 (minutes; avoid the stale-quote race, prefer resting bids) | **ADOPT** | FuuUuUu `0x2d4427…`, wuxiuming `0x919698…`, bhuumi `0x937bca…`, Weatherstappen `0xb9012e…` |
| 2 | **F/C. Niche event research (low-attention markets where public data leads price: charts, counts, mentions, benchmarks, valuations, yields)** | 4–5 (90–95% weeks; Quarrelsome 95 weeks) | 3 (11–20¢/$ but capital locked days–weeks) | 5 | 5 | **ADOPT** (time/skill-intensive) | Started-with-20-USD `0x438864…`, Quarrelsome-Branch `0x0cb10c…`, KimchiCapital `0x9578af…`, Hot-Skull `0xd12f44…`, Vagabund97 `0xa53ba9…` |
| 3 | **B. Weather forecast bracket trading (day-before / morning, NWP vs market distribution; tail ladders)** | 3–4 (85–93% weeks, 25–50% market win-rate, visible edge decay) | 4 (5–13¢/$ net; tiny fills) | 4 (needs a calibrated forecast model) | 5 | **ADOPT, maker-only** (taker fees eat 25–60% of gross edge) | jjavi `0x6ff2cb…`, BeefSlayer `0x331bf9…`, securebet `0xaa7a74…`, CreamCream1215 `0x01ced8…` |
| 4 | **LP reward farming** (see §6) | 2–3 (trading loses ~0.7–0.9× rewards for small farmers; only 9/127 small LPs steady) | 3 (headline rewards $0.5–11 per $1k book-liquidity/day, mostly handed back via adverse selection) | 3 (min size 20–100 shares; reward share tiny at $100) | 3 (must pull quotes before information windows) | **COMPLEMENT ONLY** — rest your directional maker orders in rewarded markets | SPLPB `0xdf0e45…`, 0x9495d6…, defiance-cr `0xb84ca5…`, 0xd38f5f… |
| 5 | F2. Event near-certain ("No" at 0.9x on long-dated news markets) | 3 (88% market wins, tail blow-ups like stupid22 −$117k) | 2 (≈5¢/$ but capital locked for weeks) | 3 | 5 | selective only, small size | -Dominus-, archaic, Hit-man |
| 6 | E. Sports/esports end-of-game 0.99 harvest | 4 | 1 (0–2¢/$, $20k–$300k capital) | 1 | 2 (needs live scores, first to the book) | **REJECT** | 0xB595…, qwe258, Rock.San, avonking |
| 7 | D. In-play sports/esports trading | 4 | 4 | 2 | 1 (live-feed latency; +34¢/$ on 1-minute holds = informational speed edge) | **REJECT (speed)** | jack.jr, roberto73, chicken689, ewww1 |
| 8 | G/H. Crypto up/down HFT, rebate farming, HF market making | 4–5 | 5 | 1 | 1 | **REJECT (speed/infra)** | Bonereaper, 0xb55fa1…, RN1, BookWarrior |
| 9 | X. Lucky whales | 1 (n ≤ 20 bets) | n/a | 1 | – | **EXCLUDE** | Theo4, Fredi9999, GRIMDRIP… |

## 6. LP reward farming — net economics

Data: `data/leaderboard/lp/` — `rewarded_markets_current.csv` (CLOB `/rewards/markets/current`, 16,424 markets), `rewarded_pools_by_category.csv`, `reward_yield_by_category.csv`, `rewarded_market_fills.csv.gz` (166,854 fills from the 325 highest-paying active markets across 10 categories, maker/taker split), `rewarded_market_makers.csv` (4,390 maker wallets), `lp_econ_30d.csv` + `lp_econ_raw.json.gz` (424 wallets: 30-day daily REWARD / MAKER_REBATE / TAKER_REBATE income + daily trading PnL), `lp_block_stability.csv`, `small_lp_candidates.csv`, `small_lp_quoting.csv` + `small_lp_fills_30d.json.gz` (≤5,000 most recent fills per wallet with maker flags).

### 6.1 Does PnL include rewards? — **No.**
See §2.1: no jump in hourly `user-pnl-api` PnL in the 00:00–01:00 UTC hour when REWARD/REBATE USDC is paid, even for wallets with zero trades in that hour (PPMT `0x510f49…`: ~$270/day paid, hourly PnL moves −42…+59; I---I `0x04586f…`: $29–48 paid, PnL +3.5/+19/−34/−0.3). The leaderboard number matches `user-pnl-api` (tradetosurvive1 `0x30fb41…`: board MONTH −$61k, 30-day series −$54k, while it received **$121.5k rewards + $6.6k rebates** in the same 30 days). A full-history cash-flow reconciliation (trade/redeem/merge flows + current value) agrees with the PnL series to within ~$50–250 but cannot discriminate for small reward totals (neg-risk CONVERSION flows are not modelled); the hourly test is the decisive one. **Net LP economics = board PnL + rewards + rebates.**

### 6.2 Size of the prize
$134.8k/day of liquidity rewards across 16,424 markets (typical params: max spread 4.5¢ (2.5–6.5¢), min size 20 shares (100–200 on the largest markets)). Reward per $1k of *total* book liquidity per day (aggregate, before competition for proximity to mid): **mentions $11.2, weather $8.6, culture $4.9, esports $4.6**, other $2.2, tech $2.0, economics $1.4, finance $1.2, politics $0.6, sports $0.5. Weather ($18.5k/day over 702 daily markets, median $17.5/market/day on $1.6k liquidity) and mentions ($10/market/day on $180 liquidity) are the richest per unit of liquidity.

### 6.3 Reward income vs trading PnL, last 30 days
- 424 wallets screened (the 350 most active makers in rewarded markets + coordinator examples + deep-set wallets with rewards). 310 earned > $50 of rewards: **61% had negative trading PnL; 80% were net positive after rewards**; medians: rewards $1,677, trading −$507, net +$2,204. Trading PnL ÷ (rewards+rebates) quantiles: p10 −1.46, p25 −0.92, **p50 −0.52**, p75 +3.4.
- "Clean" LP-dominant set (rewards ≥ $150, rewards > rebates, ≥ 15 paid days, excluding 24 wallets whose PnL series is implausible for their size — see note): **206 wallets; 75% lost money trading; median trading PnL = −0.73 × rewards; 79% net positive.** In aggregate the 206 made $1.83M rewards + $0.15M rebates + $2.62M trading (the trading profit is concentrated in the largest market makers).

| positions value | n | median rewards 30d | median trading PnL 30d | median net | net > 0 | trading ≥ 0 | net > 0 in all three 10-day blocks | median daily trading PnL |
|---|---|---|---|---|---|---|---|---|
| < $1k | 72 | $2,201 | **−$1,679** | +$467 | 81% | **6%** | 49% | −$35 |
| $1–5k | 55 | $3,791 | **−$3,288** | +$381 | 69% | 15% | 47% | −$76 |
| $5–25k | 30 | $4,419 | −$2,921 | +$4,423 | 87% | 30% | 70% | −$57 |
| $25–100k | 28 | $4,054 | +$3,697 | +$9,509 | 86% | 61% | 55%* | +$43* |
| > $100k | 21 | $7,575 | +$16,038 | +$24,750 | 81% | 67% | (*>$25k pooled) | |

Reading: **small farmers hand back ~85% of their rewards to informed traders (median trading/rewards −0.86)**; larger two-sided market makers earn spread *and* rewards. Caveats: (i) "positions value" excludes USDC locked in resting orders, so a "$500" wallet may be quoting $5–20k; (ii) survivorship — these are wallets *currently* quoting; farmers who quit after losses are invisible, so 80% "net positive" is an upper bound; (iii) 30 days only.

Note — excluded artifact/sybil cluster: 17 small wallets (e.g. quietparcel, northdrawer, plainfolder, smallreceipt, graynotebook19, godblessme2026 — several created on 2026-04-22 with random-word names, near-identical ~$650–720 rewards and ~$250 rebates each, heavy neg-risk `CONVERSION` use) show +$40–150k "trading PnL" on $1–3k of positions with −$40–65k single days. Either PnL-accounting artefacts of conversions or a multi-account operation; not usable evidence either way.

### 6.4 Small wallets (< $5k positions) with steady rewards AND non-negative trading PnL
Basic test (≥ 20 paid days, trading PnL 30d ≥ 0): **12 of 127** clean small LPs. Strict test (trading ≥ 0 in ≥ 2 of 3 ten-day blocks, ≥ 0 even after removing the best day, net > 0 in all blocks): **9**, of which only four are genuinely small reward-driven farmers:

| wallet | name | pos. value | rewards 30d | trading 30d | comment |
|---|---|---|---|---|---|
| `0xd38f5f17d57b4ded218dfcbca4bd8deee78abf78` | (unnamed) | $1,380 | $687 | +$848 | long-dated politics/other, bids mostly low-priced (median fill 0.09), 83% maker |
| `0x460bdf120d096cb6acef687cc984770288079894` | LonelyScissors | $1,066 | $155 | +$553 | finance/tech/other, 11-share clips, 85% maker |
| `0xb84ca5f197a73429f608842cd75ebbc7c578e169` | defiance-cr | $669 | $3,282 | +$296 | **mentions**-heavy, 67% of markets quoted two-sided, ~51 h to close |
| `0x081a3b357baafc91af26f83f622e2652668c66d0` | nani | $2,161 | $485 | +$1,226 | mostly cheap (≤0.05) bids, 32 h to close; lumpy |

The others passing are larger-quote market makers with small *position* value (SPLPB `0xdf0e455c…` $9.1k rewards + $22.1k trading; `0x9495d622…` $10.8k + $21.4k) or directional traders who also collect rewards (Vagabund97 `0xa53ba9…`, TunSahur `0x95d381…` weather, BAO95889 `0x300c5e…`). Two more (`0xe8c6c48e…`, mu-builder `0xb1f590…` with $73 of positions) pass the basic test only because of a single +$900–1,070 resolution day; their daily pattern is the typical farmer pattern: **trading −$50…−$150 every day, rewards +$80…+$180 every day.** The coordinator's small example I---I (`0x04586f…`, $434) is net −$1,046 over 30 days but +$221 over its 4 days of heavy farming (rewards $30–54/day vs trading −$102…+$147/day) — too short to call.

### 6.5 How they quote (last ≤5,000 fills, 30 days)

| wallet | name | pos. value | rewards 30d | trading PnL 30d | maker $ share | maker fills that are buys | markets filled 2-sided | median fill px | fills in 0.1–0.9 | median fill (shares) | median h to close at fill | fills after event start | weather: fills on obs-day / after local noon | maker-buy markout (¢/$, to resolution) | main categories |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `0xdf0e455c…` | SPLPB | $2,033 | $9,130 | +$22,114 | 94% | 38% | 57% | 0.38 | 75% | 49 | 708 | 22% | 21% / 0% | −5 | politics 58%, other 14%, economics 9% |
| `0x9495d622…` | 0x9495d6 | $4,080 | $10,779 | +$21,401 | 97% | 47% | 62% | 0.40 | 79% | 24 | 980 | 48% |  | −14 | politics 49%, other 17%, finance 8% |
| `0xd38f5f17…` | 0xd38F5f | $1,380 | $687 | +$848 | 83% | 72% | 43% | 0.09 | 46% | 20 | 1,002 | 75% |  | −32 | politics 39%, other 23%, tech 9% |
| `0x460bdf12…` | LonelyScissors | $1,066 | $155 | +$553 | 85% | 73% | 56% | 0.23 | 63% | 11 | 230 | 37% |  | −14 | other 24%, tech 19%, finance 16% |
| `0xb84ca5f1…` | defiance-cr | $669 | $3,282 | +$296 | 64% | 45% | 67% | 0.55 | 83% | 20 | 51 | 79% | 34% / 16% | −8 | mentions 46%, finance 26%, other 17% |
| `0x081a3b35…` | nani | $2,161 | $485 | +$1,226 | 64% | 88% | 27% | 0.03 | 26% | 25 | 32 | 38% |  | −4 | other 41%, politics 20%, tech 17% |
| `0xe8c6c48e…` | 0xE8C6C4 | $920 | $1,917 | +$74 | 43% | 99% | 9% | 0.55 | 85% | 5 | 252 | 61% | 65% / 28% | −1 | politics 20%, economics 20%, finance 17% |
| `0xb1f5904f…` | mu-builder | $73 | $535 | +$1,069 | 70% | 71% | 38% | 0.50 | 96% | 20 | 503 | 47% | 27% / 2% | −23 | other 37%, finance 22%, tech 13% |
| `0x30fb41b5…` | tradetosurvive1 | $87,961 | $121,521 | −$53,900 | 100% | 100% | 53% | 0.50 | 95% | 20 | 30 | 36% | 27% / 0% | −4 | weather 68%, other 12%, finance 5% |
| `0x04586f5d…` | I---I | $434 | $188 | −$1,234 | 56% | 81% | 23% | 0.22 | 61% | 10 | 16 | 80% | 80% / 26% | −1 | weather 100% |
| `0x510f4963…` | PPMT | $17,874 | $4,468 | −$647 | 96% | 53% | 44% | 0.30 | 58% | 15 | 116 | 75% | 69% / 35% | −7 | politics 24%, weather 19%, other 13% |
| `0x758dac51…` | a5533 | $24,530 | $3,644 | −$262 | 100% | 100% | 39% | 0.46 | 73% | 18 | 2 | 86% | 60% / 43% | −0 | esports 54%, sports 21%, other 16% |
| `0x98a88cd1…` | Miaomi666 | $1,434 | $14,192 | −$6,775 | 44% | 99% | 11% | 0.33 | 96% | 20 | 975 | 59% |  | −23 | politics 35%, other 30%, economics 8% |
| `0xe457dd29…` | ViscaElBarca | $2,239 | $20,003 | −$17,108 | 49% | 97% | 13% | 0.43 | 77% | 20 | 996 | 71% |  | −24 | politics 47%, other 18%, finance 10% |
| `0xfe468989…` | maomao228 | $839 | $10,724 | −$5,323 | 40% | 99% | 15% | 0.31 | 91% | 20 | 996 | 68% |  | −41 | politics 33%, other 30%, sports 10% |
| `0x0bef2bc1…` | 0xwordjnn | $4,530 | $16,918 | −$5,740 | 90% | 29% | 70% | 0.42 | 88% | 65 | 1,130 | 14% |  | −28 | politics 60%, economics 15%, other 13% |

"2-sided" = maker fills on both outcome tokens (or both buy and sell of one token) in the same market; "markout" = (outcome − fill price) per $ for maker buys that were held to resolution in the window (sample biased to markets that resolved). Distance from mid: comparing maker fill prices with other wallets' fills in the same token within ±30 min, all of these fill **at the local mid (median distance 0–1¢, ≤6¢ worst)** — they sit at/inside the reward band (max spread 4.5¢) rather than at its edge.

Patterns:
- **Size:** clips of exactly the reward minimum (median 20 shares; 5–65) — quoting "min size, many markets" (400–2,000 markets touched per 30 days) to collect scores broadly.
- **One- vs two-sided:** the persistent losers (Miaomi666, ViscaElBarca, maomao228, Pol7StrategyBuilder) are **one-sided bidders** (97–99% of maker fills are buys, 11–15% two-sided) in long-dated politics/other markets and get picked off (markouts −10…−41¢/$ to resolution). The profitable small/medium ones quote **both sides** (SPLPB 57%, 0x9495d6 62%, defiance-cr 67%) and earn spread on the round trips.
- **Time to resolution:** profitable farmers mostly quote long-dated markets (median 700–1,000 h to close) or mentions (≈50 h); losers include very short-dated sports (a5533: 2 h to close, 86% of fills after event start = quoting in-play) and weather observation days.
- **Pulling before information:** tradetosurvive1 (largest weather LP) takes only 27% of its weather fills on the observation day and **0% after local noon** — it withdraws or stops refreshing quotes before the daily max is revealed; I---I (80% of fills on the observation day, 26% after local noon) and PPMT (69% / 35%) do not, and show negative trading. In sports/esports, a5533 keeps quoting in-play and gives back 7% of rewards. Direct evidence that the survivable farming discipline is "quote early, pull before the information window".

### 6.6 Verdict for a $100 account
- LP rewards are real money (0.5–11 $/day per $1k of book liquidity; richest in mentions and weather), but for small farmers they are **mostly a subsidy for being adversely selected**: median small farmer loses ~85% of rewards in trading; only ~7% (9/127) of small farmers were steadily non-negative in trading over 30 days, and most of those are two-sided quoters or have directional edge.
- With $100 you can post ~2–5 minimum-size (20-share) orders. At the observed richest yields (e.g. I---I: ~$30–50/day on high-rate weather markets with a few hundred $ of positions plus unknown resting orders) the *gross* reward might be ~$1–4/day per $100 quoted in the best markets, before adverse selection — attractive only if quotes are pulled before the observation/news window.
- **Recommendation:** do not run standalone reward farming. Instead, (1) place the resting maker bids that our weather-nowcast and niche-research strategies want anyway inside rewarded markets' spread band (≥ min size), earning rewards + maker rebates and avoiding the 2–4.5% taker fee on mid/low prices; (2) quote two-sided only in slow, long-dated or research-heavy markets (mentions, culture charts) where we have a view; (3) hard-cancel all quotes in a market before its information window (weather: before local ~11:00 on the observation day unless our model is live; mentions: before the event starts; sports: never in-play).

## 7. Caveats (read before acting)

1. **Survivorship.** Every wallet here was found *because* it is on a board or actively quoting today. Wallets that ran the same strategies and lost (or stopped) are invisible; 38% of today's DAY top-1000 are lifetime losers. Treat every hit-rate as an upper bound.
2. **Board PnL ≠ economics.** It excludes rewards and rebates (§2.1) and includes mark-to-market of open positions; open-position values for long-dated markets can swing the series.
3. **Short windows for active wallets.** Trade-level stats use the most recent ≤4,000 activity events (API offset cap 5,000; I paged with `end=`), i.e. 1–200 days depending on activity. The "edge" metric only covers buys in that window and assumes hold-to-resolution (understates scalpers' edge). Closed-position samples are capped at the 3,000 most recent; concentration uses full-history top/bottom-50 netted per market.
4. **Capital is under-observed.** USDC in resting orders is invisible to `/value`; the "capital est." column is a lower bound (cash trough in window vs current open value).
5. **Heuristic categories.** Slug/title regexes (`common.py`) — e.g. some elections were misfiled until fixed; per-wallet category PnL from the leaderboard `user=` filter is stored in each wallet file (`cats`) for cross-checks.
6. **Edge decay is visible** (securebet, jjavi, BeefSlayer). Weather markets are now crowded with bots (e.g. `0x496f76…` makes 8,000 weather fills/day; HighTempTation races stale asks). Expect lower edge than historical.
7. **Resolution risk.** Near-certain strategies are short a tail: station data errors, revised observations, rounding (°C vs °F conversions) and ambiguous resolution rules can turn a 0.99 into 0. The rules text (e.g. HKO "Absolute Daily Min", Wunderground station, "first publication" revision cut-offs) is part of the edge.
8. **No causality.** Strategy descriptions are inferred from fills, prices, timing and outcomes, not from the traders; alternative explanations (e.g. private data feeds) cannot be excluded.
9. **Sybil/artefact clusters** exist (§6.3 note); some very high Sharpe/low-capital PnL series are accounting artefacts of neg-risk conversions.

## 8. What this implies for a $100 account (concrete)

- **Primary: weather nowcast, maker-first (archetype A), 1–3 cities we can monitor well.** On the observation day, from ~12:00–15:00 local, once the running max (for "highest temperature") is known from the resolution station's live METAR/Wunderground feed: bid 0.95–0.99 for "No" on brackets *below* the observed running max (physically dead — only resolution-risk remains), and selectively on brackets far above what the remaining afternoon can reach per the hourly forecast. Rest orders as maker (no fee, rebates, possible rewards), 5–20 shares each, ≤ $20 per market, ≤ 5 markets/day; recycle by selling to 0.999 bids if they appear (Weatherstappen/bhuumi pattern). Expected: ~1–3% per turn, a few turns/day, rare −100% legs → keep each position ≤ 20% of bankroll. Templates: FuuUuUu `0x2d44274747466c0936c3e01d5a5ad6c260d97023`, bhuumi `0x937bcac3a8a30c07d827ad0550c3fe3a6756bfab`, wuxiuming `0x919698b19427cbe6945b0dc823f2d9e126a4d934`.
- **Secondary: forecast-vs-market bracket ladders (archetype B)** with a calibrated NWP-ensemble model, maker-only $0.5–$5 ladders on tails the model rates ≥ 3× market odds, entered the evening before / early morning. Template: jjavi `0x6ff2cb14da8be7eb57541d250a0196c5f295f140` (watch its September pause).
- **Tertiary: niche-research event trading (archetype F/C)** in 1–2 domains where we can build data advantage (music charts, mention/count markets, AI leaderboards, barrier-hit price markets): $2–10 positions, ~1 week holds, avoid taker fees on mid prices. Templates: Started-with-20-USD `0x4388640a35b4ecebc33f8c73b58a2b988c615050`, Quarrelsome-Branch `0x0cb10c40b0776e9ee8cef970af85724654dda76c`, KimchiCapital `0x9578af80708f271f705e27867dcf6ec653acf066`, Vagabund97 `0xa53ba9d683f68602ccd767512d5c862a43824021`.
- **Do not:** chase end-of-game 0.99 sports, in-play sports, crypto up/down, or standalone LP farming (§6); do not copy anything from the whale list.
- **Next research steps:** (1) build a weather-station observation + forecast pipeline and back-test archetype A/B on the last 90 days of weather markets using CLOB price history; (2) verify fee/rebate formulas against docs; (3) monitor the named wallets weekly (the scripts below can be re-run) to detect edge decay.

## 9. Reproducibility

Scripts (copied to `data/leaderboard/scripts/`): `s1_leaderboard.py` (boards) → `s2_screen.py` (PnL series + traded) → `s4_screen_metrics.py` → `s3_deep.py` (+ `s3b_income.py`) → `s5_deep_metrics.py` → `s6_gamma.py` → `s7_timing.py` → `s8_archetypes.py` → `s9_cards.py`; LP study: `s10_lp_markets.py` → `s11_lp_makers.py` → `s12_lp_econ.py` → `s13_lp_quoting.py`; shared `common.py` (category regexes). All raw pulls are under `data/leaderboard/` (total < 200 MB). Nothing was committed to git.
