#!/bin/bash
cd /home/user/polyall2/src/crypto
L=/home/user/polyall2/data/crypto/fetch_ph_rest.log
while pgrep -f "fetch_pm_history.py bitcoin-hit-price-weekly" > /dev/null; do sleep 10; done
python3 fetch_pm_history.py bitcoin-hit-price-monthly --kinds touch_up,touch_down --since 2025-01-01 --fine-hours 0 >> $L 2>&1
python3 fetch_pm_history.py ethereum-multi-strikes-weekly --kinds above --since 2025-08-01 --slug-prefix ethereum-above-on --fine-fid 5 >> $L 2>&1
python3 fetch_pm_history.py bitcoin-hit-price-daily --kinds touch_up,touch_down --since 2025-08-01 --fine-fid 5 >> $L 2>&1
python3 fetch_pm_history.py solana-multi-strikes-weekly --kinds above --since 2025-08-01 --slug-prefix solana-above-on --fine-fid 10 >> $L 2>&1
python3 fetch_pm_history.py xrp-multi-strikes-weekly --kinds above --since 2025-08-01 --slug-prefix xrp-above-on --fine-fid 10 >> $L 2>&1
echo ALLDONE >> $L
