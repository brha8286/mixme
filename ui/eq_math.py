"""
EQ frequency response computation using Audio EQ Cookbook biquad formulas.
https://www.musicdsp.org/en/latest/Filters/197-rbj-audio-eq-cookbook.html
"""
import math
import numpy as np

FS = 96000.0  # virtual sample rate — high enough that 20kHz << Nyquist
FREQS = np.logspace(math.log10(20), math.log10(20000), 300)
FREQ_LIST = FREQS.tolist()  # cached for JSON serialisation

BAND_NAMES = ['LOW', 'LO MID', 'HI MID', 'HIGH']
BAND_TYPES = ['LCut', 'LShelf', 'PEQ', 'VEQ', 'HShelf', 'HCut']
Q_RELEVANT = {2, 3}  # PEQ, VEQ — only types where Q matters visually


# ── OSC raw → human value conversions ────────────────────────────────────────

def raw_to_hz(raw: float) -> float:
    raw = max(0.0, min(1.0, raw))
    return 20.0 * (1000.0 ** raw)          # log_get(20, 20000, raw)


def raw_to_db_gain(raw: float) -> float:
    return -15.0 + raw * 30.0              # lin_get(-15, 15, raw)


def raw_to_q(raw: float) -> float:
    inv = max(1e-4, min(0.9999, 1.0 - raw))
    return 0.3 * (10.0 / 0.3) ** inv      # log_get(0.3, 10, 1.0 - raw)


def hz_to_raw(hz: float) -> float:
    return math.log(hz / 20.0) / math.log(1000.0)


def db_gain_to_raw(db: float) -> float:
    return (db + 15.0) / 30.0


def q_to_raw(q: float) -> float:
    inv = math.log(q / 0.3) / math.log(10.0 / 0.3)
    return 1.0 - inv


# ── biquad coefficient builders ───────────────────────────────────────────────

def _resp(b, a, freqs=FREQS) -> np.ndarray:
    w = 2 * math.pi * freqs / FS
    z1 = np.exp(-1j * w)
    z2 = np.exp(-2j * w)
    H = (b[0] + b[1] * z1 + b[2] * z2) / (a[0] + a[1] * z1 + a[2] * z2)
    return 20 * np.log10(np.maximum(np.abs(H), 1e-10))


def _peq(f0, gain_db, Q):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / FS
    alpha = math.sin(w0) / (2 * Q)
    c = math.cos(w0)
    return [1 + alpha * A, -2 * c, 1 - alpha * A], \
           [1 + alpha / A, -2 * c, 1 - alpha / A]


def _lshelf(f0, gain_db, Q=0.707):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / FS
    cosw = math.cos(w0)
    sqA = math.sqrt(A)
    alpha = math.sin(w0) / 2 * math.sqrt((A + 1 / A) * (1 / Q - 1) + 2)
    b = [A * ((A + 1) - (A - 1) * cosw + 2 * sqA * alpha),
         2 * A * ((A - 1) - (A + 1) * cosw),
         A * ((A + 1) - (A - 1) * cosw - 2 * sqA * alpha)]
    a = [(A + 1) + (A - 1) * cosw + 2 * sqA * alpha,
         -2 * ((A - 1) + (A + 1) * cosw),
         (A + 1) + (A - 1) * cosw - 2 * sqA * alpha]
    return b, a


def _hshelf(f0, gain_db, Q=0.707):
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * f0 / FS
    cosw = math.cos(w0)
    sqA = math.sqrt(A)
    alpha = math.sin(w0) / 2 * math.sqrt((A + 1 / A) * (1 / Q - 1) + 2)
    b = [A * ((A + 1) + (A - 1) * cosw + 2 * sqA * alpha),
         -2 * A * ((A - 1) + (A + 1) * cosw),
         A * ((A + 1) + (A - 1) * cosw - 2 * sqA * alpha)]
    a = [(A + 1) - (A - 1) * cosw + 2 * sqA * alpha,
         2 * ((A - 1) - (A + 1) * cosw),
         (A + 1) - (A - 1) * cosw - 2 * sqA * alpha]
    return b, a


def _hpf(f0, Q=0.707):
    w0 = 2 * math.pi * f0 / FS
    cosw = math.cos(w0)
    alpha = math.sin(w0) / (2 * Q)
    b = [(1 + cosw) / 2, -(1 + cosw), (1 + cosw) / 2]
    a = [1 + alpha, -2 * cosw, 1 - alpha]
    return b, a


def _lpf(f0, Q=0.707):
    w0 = 2 * math.pi * f0 / FS
    cosw = math.cos(w0)
    alpha = math.sin(w0) / (2 * Q)
    b = [(1 - cosw) / 2, 1 - cosw, (1 - cosw) / 2]
    a = [1 + alpha, -2 * cosw, 1 - alpha]
    return b, a


# ── public API ────────────────────────────────────────────────────────────────

def band_db(band_type: int, f0: float, gain_db: float, Q: float) -> np.ndarray:
    """Return dB response array for one EQ band."""
    f0 = max(20.0, min(19999.0, f0))
    Q = max(0.1, Q)
    if band_type == 0:   # LCut
        return _resp(*_hpf(f0, Q))
    elif band_type == 1: # LShelf
        return _resp(*_lshelf(f0, gain_db))
    elif band_type in (2, 3):  # PEQ / VEQ
        return _resp(*_peq(f0, gain_db, Q))
    elif band_type == 4: # HShelf
        return _resp(*_hshelf(f0, gain_db))
    elif band_type == 5: # HCut
        return _resp(*_lpf(f0, Q))
    return np.zeros(len(FREQS))


def eq_response(bands: list[dict]) -> list[float]:
    """
    Compute combined response for all bands.
    Each band: {type: int, f: float Hz, g: float dB, q: float}
    Returns list of 300 dB values aligned with FREQ_LIST.
    """
    total = np.zeros(len(FREQS))
    for b in bands:
        total += band_db(b['type'], b['f'], b['g'], b['q'])
    return np.clip(total, -30, 20).tolist()


def parse_band(snapshot: dict, ch: int, band: int) -> dict:
    """Extract one EQ band's display values from OSC state snapshot."""
    prefix = f'/ch/{ch:02d}/eq/{band}'
    raw_f = float(snapshot.get(f'{prefix}/f') or 0.5)
    raw_g = float(snapshot.get(f'{prefix}/g') or 0.5)
    raw_q = float(snapshot.get(f'{prefix}/q') or 0.5)
    raw_t = int(snapshot.get(f'{prefix}/type') or 2)
    return {
        'type': raw_t,
        'f':    raw_to_hz(raw_f),
        'g':    raw_to_db_gain(raw_g),
        'q':    raw_to_q(raw_q),
    }
