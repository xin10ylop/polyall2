"""No-look-ahead posting model.
At decision time t, uses only posts with createdAt < t AND importedAt <= t (what xtracker showed at t).
Rate: profile-adjusted EWMA (half-life hl days) over the last L days; hour-of-day profile (UTC) from the last
PROF_DAYS days (shrunk to uniform). Expected remaining count mu = R * sum_{hours in (t,E]} prof(hour)/1 (R per day).
Predictive: N ~ NegBin(mean mu, var mu + alpha(h) mu^2), alpha calibrated per account & horizon bin."""
import numpy as np, pandas as pd
from scipy import stats, special
from common import posts

L_DAYS = 56
PROF_DAYS = 28
PROF_SHRINK = 3.0   # pseudo-posts per hour toward uniform
DOW = True          # separable day-of-week factor (ET days, fixed -4h offset), shrunk toward 1
DOW_SHRINK = 2.0     # pseudo-days at the mean rate
ET_OFF = 4 * 3600
HBINS = np.array([0, 2, 4, 8, 16, 32, 64, 128, 256, 1e9])  # hours

class Acct:
    def __init__(self, h, strict=True):
        p = posts(h)
        self.h = h
        self.ca = p.createdAt.values.astype("datetime64[s]").astype(np.int64)
        self.ia = p.importedAt.values.astype("datetime64[s]").astype(np.int64)
        if not strict:
            self.ia = self.ca.copy()
        o = np.argsort(self.ca, kind="stable"); self.ca = self.ca[o]; self.ia = self.ia[o]

    def visible(self, t, lo):
        """createdAt in [lo, t) and imported by t"""
        i0, i1 = np.searchsorted(self.ca, [lo, t])
        c = self.ca[i0:i1]; return c[self.ia[i0:i1] <= t]

    def count(self, s, t):
        """as-of-t count of posts created in [s, t)"""
        return len(self.visible(t, s))

    def final_count(self, s, e):
        i0, i1 = np.searchsorted(self.ca, [s, e]); return int(i1 - i0)

    def state(self, t, hl):
        """returns (R per day, profile[24]) using data visible at t"""
        c = self.visible(t, t - L_DAYS * 86400)
        # profile from last PROF_DAYS
        cp = c[c >= t - PROF_DAYS * 86400]
        hc = np.bincount(((cp // 3600) % 24).astype(int), minlength=24).astype(float)
        prof = (hc + PROF_SHRINK) / (hc.sum() + 24 * PROF_SHRINK)          # share per hour-of-day
        dowf = np.ones(7)
        if DOW:
            day = (c - ET_OFF) // 86400
            d0 = (t - ET_OFF) // 86400 - L_DAYS
            dc = np.bincount((day - d0).astype(int), minlength=L_DAYS + 1)[:L_DAYS]   # complete past days
            dw = (np.arange(d0, d0 + L_DAYS) + 3) % 7                                   # 0=Mon (1970-01-01 was Thu)
            mean = dc.mean() if dc.mean() > 0 else 1e-9
            for w in range(7):
                sel = dw == w
                dowf[w] = (dc[sel].sum() + DOW_SHRINK * mean) / (sel.sum() * mean + DOW_SHRINK * mean)
            dowf = dowf / dowf.mean()
        self._dowf = dowf
        # EWMA numerator: sum of weights of posts; denominator: expected weight per unit daily rate
        tau = hl * 86400 / np.log(2)
        num = np.exp(-(t - c) / tau).sum()
        # hours back from t: hour j covers [t-(j+1)h, t-jh)
        nh = L_DAYS * 24
        mids = t - (np.arange(nh) + 0.5) * 3600
        w = np.exp(-(t - mids) / tau)
        dmid = ((mids - ET_OFF) // 86400 + 3) % 7
        den = (w * prof[((mids // 3600) % 24).astype(int)] * dowf[dmid.astype(int)]).sum()
        return num / max(den, 1e-9), (prof, dowf)

    def expected(self, t, e, R, prof):
        """expected posts in [t, e) given daily rate R and (hour profile, dow factor)"""
        prof, dowf = prof
        if e <= t: return 0.0
        h0 = t // 3600; h1 = (e - 1) // 3600
        hrs = np.arange(h0, h1 + 1)
        frac = np.ones(len(hrs))
        frac[0] = ((h0 + 1) * 3600 - t) / 3600
        frac[-1] -= ((h1 + 1) * 3600 - e) / 3600 if len(hrs) > 1 else 0
        if len(hrs) == 1: frac[0] = (e - t) / 3600
        dw = (((hrs * 3600 + 1800) - ET_OFF) // 86400 + 3) % 7
        return R * float((frac * prof[(hrs % 24).astype(int)] * dowf[dw.astype(int)]).sum())

def nb_pmf_cdf(mu, alpha, nmax):
    """NB with mean mu, var mu+alpha mu^2 -> (pmf array 0..nmax, sf beyond)"""
    k = np.arange(nmax + 1)
    if alpha < 1e-6 or mu <= 0:
        pm = stats.poisson.pmf(k, max(mu, 1e-9))
    else:
        r = 1.0 / alpha; p = r / (r + mu)
        pm = stats.nbinom.pmf(k, r, p)
    return pm

def nb_logpmf(n, mu, alpha):
    mu = np.maximum(mu, 1e-6); r = 1.0 / np.maximum(alpha, 1e-8)
    return (special.gammaln(n + r) - special.gammaln(r) - special.gammaln(n + 1)
            + r * np.log(r / (r + mu)) + n * np.log(mu / (r + mu)))

def bucket_probs(C, mu, alpha, lo, hi):
    """P(C+N in [lo_k, hi_k]) for each bucket."""
    lo = np.asarray(lo); hi = np.asarray(hi)
    top = int(min(max(hi[hi < 1e8].max() if (hi < 1e8).any() else lo.max(), lo.max()) + 5, 1e6))
    nmax = max(top - C, 0) + 1
    pm = nb_pmf_cdf(mu, alpha, nmax)
    cdf = np.concatenate([[0.0], np.cumsum(pm)])   # cdf[j] = P(N < j)
    def P_lt(x):  # P(C+N < x) = P(N < x-C)
        j = np.clip(x - C, 0, nmax + 1).astype(int)
        return np.where(x - C <= 0, 0.0, cdf[np.minimum(j, len(cdf) - 1)])
    p_hi = np.where(hi >= 1e8, 1.0, P_lt(hi + 1))
    pr = p_hi - P_lt(lo)
    pr = np.clip(pr, 0, 1)
    return pr / pr.sum() if pr.sum() > 0 else pr

def hbin(hours):
    return np.clip(np.searchsorted(HBINS, hours, side="right") - 1, 0, len(HBINS) - 2)
