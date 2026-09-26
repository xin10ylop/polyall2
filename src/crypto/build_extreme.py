import sys
from pathlib import Path
from analyze_touch import extreme_train
from volmodel import Features
SP = Path('/tmp/claude-0/-home-user-polyall2/23837d40-49ff-5c90-86c9-24d18e8ba96d/scratchpad')
for a in sys.argv[1:]:
    tr = extreme_train(a, Features(a))
    tr.to_parquet(SP / f'train_extreme_{a}.parquet', compression='zstd')
    print(a, len(tr), flush=True)
