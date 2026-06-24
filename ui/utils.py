def fader_to_db(val: float) -> str:
    """Convert normalized OSC fader value (0.0–1.0) to a dB string."""
    if val >= 1.0:
        db = 10.0
    elif val >= 0.5:
        db = round((40 * val) - 30, 1)
    elif val >= 0.25:
        db = round((80 * val) - 50, 1)
    elif val >= 0.0625:
        db = round((160 * val) - 70, 1)
    elif val > 0:
        db = round((480 * val) - 90, 1)
    else:
        return '-∞'
    return f'{db:+.1f}' if db != 0 else '0.0'
