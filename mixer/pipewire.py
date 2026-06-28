import logging
import math
import os
import re
import subprocess
import threading
import time

log = logging.getLogger(__name__)

_PW_ENV = {
    **os.environ,
    'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}',
    'PIPEWIRE_RUNTIME_DIR': f'/run/user/{os.getuid()}',
}


def _wpctl(*args, timeout: float = 2.0) -> str:
    result = subprocess.run(
        ['wpctl', *args],
        capture_output=True, text=True, env=_PW_ENV, timeout=timeout,
    )
    return result.stdout


def _find_shairport_stream_id() -> int | None:
    """Return the wpctl node ID of the active shairport-sync audio stream."""
    in_streams = False
    for line in _wpctl('status').splitlines():
        if 'Streams:' in line:
            in_streams = True
            continue
        if in_streams:
            # A new top-level section (Video, Settings, etc.) ends the Audio Streams block
            if line and not line[0].isspace():
                break
            m = re.match(r'\s{6,8}(\d+)\.\s+Shairport Sync', line)
            if m:
                return int(m.group(1))
    return None


class AirPlayControl:
    """Finds the shairport-sync PipeWire stream and applies a persistent volume/mute to it."""

    def __init__(self):
        self._volume: float = 1.0   # 0.0–1.5; 1.0 = 0 dB
        self._muted: bool = False
        self._active: bool = False
        self._lock = threading.Lock()
        self._running = False

    @property
    def volume(self) -> float:
        with self._lock:
            return self._volume

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @staticmethod
    def vol_to_db(vol: float) -> str:
        if vol <= 0:
            return '-∞'
        db = 20 * math.log10(max(vol, 1e-9))
        return f'{db:+.1f}'

    def set_volume(self, volume: float):
        with self._lock:
            self._volume = max(0.0, min(1.5, volume))
        self._apply()

    def set_muted(self, muted: bool):
        with self._lock:
            self._muted = muted
        self._apply()

    def _apply(self):
        try:
            stream_id = _find_shairport_stream_id()
            with self._lock:
                self._active = stream_id is not None
                vol = self._volume
                muted = self._muted
            if stream_id is not None:
                _wpctl('set-volume', str(stream_id), str(round(vol, 3)))
                _wpctl('set-mute',   str(stream_id), '1' if muted else '0')
        except Exception as e:
            log.debug('AirPlay apply error: %s', e)

    def start(self):
        self._running = True
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            self._apply()
            time.sleep(3)
