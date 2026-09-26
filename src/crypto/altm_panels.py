"""Alt monthly barrier panels (HYPE, DOGE, BNB, SOL, XRP): daily 16:00 UTC decisions + W1-{12,6,3,1}h."""
import sys
from analyze_touch import make_panel
FAM = {'HYPE': 'hyperliquid', 'DOGE': 'dogecoin', 'BNB': 'bnb', 'SOL': 'solana', 'XRP': 'xrp'}
for a in sys.argv[1:]:
    pn = make_panel(a, (f'{FAM[a]}-hit-price-monthly',), spec='rv', rebuild=True, tag='_monthly')
    print(a, len(pn), 'resolution mismatch', int((pn.y != pn.y_bin).sum()), flush=True)
