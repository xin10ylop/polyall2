"""Shared constants/helpers for the weather study."""
import numpy as np
import pandas as pd

D = "/home/user/polyall2/data/weather"

TZ = {
    "CYYZ": "America/Toronto", "DNMM": "Africa/Lagos", "EDDM": "Europe/Berlin", "EFHK": "Europe/Helsinki",
    "EGLC": "Europe/London", "EHAM": "Europe/Amsterdam", "EPWA": "Europe/Warsaw", "FACT": "Africa/Johannesburg",
    "KATL": "America/New_York", "KAUS": "America/Chicago", "KBKF": "America/Denver", "KDAL": "America/Chicago",
    "KDCA": "America/New_York", "KHOU": "America/Chicago", "KLAX": "America/Los_Angeles", "KLGA": "America/New_York",
    "KMIA": "America/New_York", "KORD": "America/Chicago", "KPHX": "America/Phoenix", "KSEA": "America/Los_Angeles",
    "KSFO": "America/Los_Angeles", "LEMD": "Europe/Madrid", "LFPB": "Europe/Paris", "LFPG": "Europe/Paris",
    "LIMC": "Europe/Rome", "LLBG": "Asia/Jerusalem", "LTAC": "Europe/Istanbul", "LTFM": "Europe/Istanbul",
    "MMMX": "America/Mexico_City", "MPMG": "America/Panama", "NZWN": "Pacific/Auckland", "OEJN": "Asia/Riyadh",
    "OMDB": "Asia/Dubai", "OPKC": "Asia/Karachi", "RCSS": "Asia/Taipei", "RCTP": "Asia/Taipei", "RJTT": "Asia/Tokyo",
    "RKPK": "Asia/Seoul", "RKSI": "Asia/Seoul", "RPLL": "Asia/Manila", "SAEZ": "America/Argentina/Buenos_Aires",
    "SBGR": "America/Sao_Paulo", "UUWW": "Europe/Moscow", "VHHH": "Asia/Hong_Kong", "VILK": "Asia/Kolkata",
    "WIHH": "Asia/Jakarta", "WMKK": "Asia/Kuala_Lumpur", "WSSS": "Asia/Singapore", "ZBAA": "Asia/Shanghai",
    "ZGGG": "Asia/Shanghai", "ZGSZ": "Asia/Shanghai", "ZHCC": "Asia/Shanghai", "ZHHH": "Asia/Shanghai",
    "ZSJN": "Asia/Shanghai", "ZSPD": "Asia/Shanghai", "ZSQD": "Asia/Shanghai", "ZUCK": "Asia/Shanghai",
    "ZUUU": "Asia/Shanghai", "HKO": "Asia/Hong_Kong", "CWA46692": "Asia/Taipei",
}

MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"])}


def event_date(slug, end_date):
    """Target local date from slug '...-on-september-25-2026' (year may be missing -> from endDate)."""
    import re
    m = re.search(r"-on-([a-z]+)-(\d{1,2})(?:-(\d{4}))?$", slug)
    if not m:
        return None
    mon = MONTHS.get(m.group(1))
    if mon is None:
        for k, v in MONTHS.items():
            if k.startswith(m.group(1)[:3]):
                mon = v
    if mon is None:
        return None
    day = int(m.group(2))
    yr = int(m.group(3)) if m.group(3) else pd.Timestamp(end_date).year
    try:
        return pd.Timestamp(year=yr, month=mon, day=day).date()
    except ValueError:
        return None


def f2c(f):
    return (np.asarray(f) - 32.0) * 5.0 / 9.0


def c2f(c):
    return np.asarray(c) * 9.0 / 5.0 + 32.0


def round_half_up(x):
    return np.floor(np.asarray(x) + 0.5)


def taker_fee_per_share(p, rate=0.05):
    p = np.asarray(p)
    return rate * p * (1 - p)
