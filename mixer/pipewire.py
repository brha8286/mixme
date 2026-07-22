import json
import logging
import math
import os
import re
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

MR18_SINK = 'alsa_output.usb-MIDAS_MR18_1C921437-00.multichannel-output'
_PW_RATE = 48000
_PW_CHUNK = 4800  # 100 ms at 48 kHz, matching the ALSA meter loop
_PW_NODE = 'mr18-meter'  # our capture stream's node name, so we can verify its links
_PW_VERIFY_EVERY = 20    # chunks between link checks (20 × 100 ms = 2 s)

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


def sink_channels(name: str) -> int | None:
    """Channel count of a PipeWire sink, or None if that sink isn't present.

    The MR18 sink disappears whenever something (e.g. Ardour on the raw ALSA
    backend) holds the USB device exclusively.
    """
    try:
        out = subprocess.run(
            ['pw-dump'], capture_output=True, text=True, env=_PW_ENV, timeout=5,
        ).stdout
        for obj in json.loads(out):
            props = (obj.get('info') or {}).get('props') or {}
            if props.get('node.name') == name:
                return int(props['audio.channels'])
    except Exception as e:
        log.debug('sink_channels(%s) failed: %s', name, e)
    return None


def _linked_to_sink(sink: str, node: str) -> bool:
    """True if `node`'s inputs are actually linked to `sink`'s monitor ports.

    Must be checked continuously, not just at startup: when a target sink
    disappears, PipeWire silently re-attaches the capture to the *default*
    sink's monitor rather than ending the stream, and we would then report an
    unrelated device's audio as MR18 USB-return levels. `node.dont-reconnect`
    does not prevent this (tested — the stream survived its target's death).
    """
    try:
        out = subprocess.run(
            ['pw-link', '-l', sink, node],
            capture_output=True, text=True, env=_PW_ENV, timeout=3,
        ).stdout
        return bool(out.strip())
    except Exception as e:
        log.debug('link check failed: %s', e)
        return False


class SinkMonitorMeters:
    """Per-channel RMS of what this machine sends to a PipeWire sink.

    The MR18 taps each channel for its USB send at the *analog preamp*, before
    the USB-return switch — so a channel fed from USB (AirPlay, a DAW) is
    silent in the USB capture stream no matter how loud it actually is.
    Monitoring the sink recovers those levels: what we send to sink channel N
    is what mixer channel N hears when its USB return is switched on.
    """

    def __init__(self, sink: str = MR18_SINK):
        self.sink = sink
        self._levels: list[float] = []
        self._lock = threading.Lock()
        self._running = False
        self._proc: subprocess.Popen | None = None

    @property
    def levels(self) -> list[float]:
        """RMS per sink channel (index 0 = channel 1); empty when not monitoring."""
        with self._lock:
            return list(self._levels)

    def start(self):
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()

    def _clear(self):
        with self._lock:
            self._levels = []

    def _run(self):
        while self._running:
            channels = sink_channels(self.sink)
            if not channels:
                self._clear()
                time.sleep(3)   # sink absent — someone else holds the device
                continue

            chunk_bytes = _PW_CHUNK * channels * 4  # f32
            try:
                proc = subprocess.Popen(
                    ['pw-record', '--raw', '--format', 'f32',
                     '--rate', str(_PW_RATE), '--channels', str(channels),
                     '--target', self.sink,
                     '-P', f'{{ stream.capture.sink=true node.name={_PW_NODE} }}',
                     '-'],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=_PW_ENV,
                )
                self._proc = proc
                log.info('PipeWire monitor started on %s (%d ch)', self.sink, channels)

                ticks = 0
                while self._running:
                    raw = proc.stdout.read(chunk_bytes)
                    if len(raw) < chunk_bytes:
                        break
                    ticks += 1
                    if ticks % _PW_VERIFY_EVERY == 0 and not _linked_to_sink(self.sink, _PW_NODE):
                        log.info('monitor no longer linked to %s — restarting', self.sink)
                        break
                    samples = np.frombuffer(raw, dtype='<f4').reshape(_PW_CHUNK, channels)
                    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2, axis=0))
                    with self._lock:
                        self._levels = [float(v) for v in rms]

            except Exception as e:
                log.warning('PipeWire monitor error: %s', e)
            finally:
                if self._proc:
                    self._proc.terminate()
                    self._proc = None
                self._clear()

            if self._running:
                time.sleep(2)


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
