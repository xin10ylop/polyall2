"""Build barrier (touch) panels for all assets with decision times W1-{24,18,12,6,3,1}h."""
import sys
from analyze_touch import make_panel

FAM = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana', 'XRP': 'xrp'}

if __name__ == '__main__':
    for a in sys.argv[1:]:
        f = FAM[a]
        pn = make_panel(a, (f'{f}-hit-price-monthly', f'{f}-hit-price-weekly', f'{f}-hit-price-daily'),
                        spec='combo' if a in ('BTC', 'ETH') else 'rv', rebuild=True,
                        offsets=(24, 18, 12, 6, 3, 1), daily16=False, tag='_barrier')
        print(a, len(pn), pn.series.value_counts().to_dict(), 'resolution mismatch:', int((pn.y != pn.y_bin).sum()), flush=True)
