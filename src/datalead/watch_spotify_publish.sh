#!/bin/bash
# Poll kworb + Spotify public chart endpoint every 10 min; log when a new daily chart date appears.
LOG=/home/user/polyall2/data/datalead/spotify_publish_times.log
for i in $(seq 1 60); do
  k=$(curl -sS -m 30 https://kworb.net/spotify/country/global_daily.html | grep -o 'Spotify Daily Chart - Global - [0-9/]*' | awk '{print $NF}')
  s=$(curl -sS -m 30 https://charts-spotify-com-service.spotify.com/public/v0/charts | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['chartEntryViewResponses'][0]['displayChart']['date'])" 2>/dev/null)
  echo "$(date -u +%FT%TZ) kworb=$k spotify_public=$s" >> $LOG
  sleep 600
done
