#!/bin/bash
# sequential fetch of price histories + trades for the other families
cd /home/user/polyall2/src/crypto
L=/home/user/polyall2/data/crypto/fetch_ph_rest.log
python3 fetch_pm_history.py bitcoin-neg-risk-weekly --kinds range --since 2025-08-01 --slug-prefix bitcoin-price-on >> $L 2>&1
python3 fetch_pm_history.py bitcoin-hit-price-weekly --kinds touch_up,touch_down --since 2025-07-01 >> $L 2>&1
python3 fetch_pm_history.py bitcoin-hit-price-monthly --kinds touch_up,touch_down --since 2025-01-01 >> $L 2>&1
python3 fetch_pm_history.py ethereum-multi-strikes-weekly --kinds above --since 2025-08-01 --slug-prefix ethereum-above-on >> $L 2>&1
python3 fetch_pm_history.py bitcoin-hit-price-daily --kinds touch_up,touch_down --since 2025-08-01 >> $L 2>&1
python3 fetch_pm_history.py solana-multi-strikes-weekly --kinds above --since 2025-08-01 --slug-prefix solana-above-on >> $L 2>&1
python3 fetch_pm_history.py xrp-multi-strikes-weekly --kinds above --since 2025-08-01 --slug-prefix xrp-above-on >> $L 2>&1
echo ALLDONE >> $L
