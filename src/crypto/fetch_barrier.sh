#!/bin/bash
# price history (last 28h, 5-min) + all taker trades for daily/weekly/monthly barrier markets of ETH/SOL/XRP
cd /home/user/polyall2/src/crypto
L=/home/user/polyall2/data/crypto/fetch_barrier.log
for s in ethereum-hit-price-daily solana-hit-price-daily xrp-hit-price-daily; do
  python3 fetch_pm_history.py $s --kinds touch_up,touch_down --since 2026-03-01 --only-fine --fine-hours 28 --fine-fid 5 --workers 6 >> $L 2>&1
done
for s in ethereum-hit-price-weekly solana-hit-price-weekly xrp-hit-price-weekly ethereum-hit-price-monthly solana-hit-price-monthly xrp-hit-price-monthly; do
  python3 fetch_pm_history.py $s --kinds touch_up,touch_down --since 2025-01-01 --only-fine --fine-hours 28 --fine-fid 5 --workers 6 >> $L 2>&1
done
echo ALLDONE >> $L
