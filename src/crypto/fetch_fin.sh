#!/bin/bash
cd /home/user/polyall2/src/crypto
L=/home/user/polyall2/data/crypto/fetch_fin.log
for s in gold-hit-price-weekly silver-hit-price-weekly wti-crude-oil-hit-price-weekly spy-hit-price-weekly natural-gas-hit-price-weekly nvidia-hit-price-weekly xauusd-hit-month xagusd-hit-month spy-hit-month ng-hit-month nvidia-hit-price-monthly fin-extra; do
  python3 fetch_pm_history.py $s --kinds touch_up,touch_down --since 2025-01-01 --fine-hours 0 --workers 6 >> $L 2>&1
done
echo ALLDONE >> $L
