#!/bin/bash
cd /home/user/polyall2/src/crypto
L=/home/user/polyall2/data/crypto/fetch_altm.log
while pgrep -f fetch_fin.sh > /dev/null; do sleep 15; done
for s in hyperliquid-hit-price-monthly dogecoin-hit-price-monthly bnb-hit-price-monthly solana-hit-price-monthly xrp-hit-price-monthly; do
  python3 fetch_pm_history.py $s --kinds touch_up,touch_down --since 2025-06-01 --fine-hours 0 --workers 6 >> $L 2>&1
done
echo ALLDONE >> $L
