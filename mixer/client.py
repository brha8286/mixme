import logging
import math
import subprocess
import threading
import time

import numpy as np
import xair_api

from .pipewire import SinkMonitorMeters

log = logging.getLogger(__name__)

NUM_STRIPS = 16
_ALSA_DEVICE = 'hw:4,0'
_ALSA_CHANNELS = 18
_ALSA_RATE = 48000
_ALSA_CHUNK = 4800  # 100 ms at 48 kHz


def _fader_gain(val: float) -> float:
    """Normalized fader (0.0–1.0) → linear amplitude gain (X-Air fader taper).

    Inverse of ui.utils.fader_to_db; kept here so the meter thread has no UI import.
    """
    if val <= 0:
        return 0.0
    if val >= 0.5:
        db = 40 * val - 30
    elif val >= 0.25:
        db = 80 * val - 50
    elif val >= 0.0625:
        db = 160 * val - 70
    else:
        db = 480 * val - 90
    return 10 ** (db / 20)


class MixerClient:
    def __init__(self):
        self.ip: str = ''
        self.status: str = 'Not connected'
        self._state: dict = {}
        self._lock = threading.Lock()
        self._mixer = None
        self._running = False
        self.connected = False
        self._alsa_proc: subprocess.Popen | None = None
        self._usb_meters = SinkMonitorMeters()

    def get(self, addr: str):
        with self._lock:
            return self._state.get(addr)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def send(self, addr: str, val):
        if self._mixer:
            self._mixer.send(addr, val)
        with self._lock:
            self._state[addr] = val

    def _on_message(self, addr: str, *data):
        if not data:
            return
        if self._mixer:
            self._mixer._info_response = list(data)
        val = data[0] if len(data) == 1 else list(data)
        with self._lock:
            self._state[addr] = val

    def _query_initial(self, mixer):
        for i in range(1, NUM_STRIPS + 1):
            mixer.query(f'/ch/{i:02d}/mix/fader')
            mixer.query(f'/ch/{i:02d}/mix/on')
            mixer.query(f'/ch/{i:02d}/mix/lr')
            mixer.query(f'/ch/{i:02d}/config/name')
            mixer.query(f'/headamp/{i:02d}/gain')
            mixer.query(f'/headamp/{i:02d}/phantom')
            mixer.query(f'/ch/{i:02d}/preamp/rtnsw')   # USB return on/off
        mixer.query('/lr/mix/fader')
        mixer.query('/lr/mix/on')
        mixer.query('/lr/config/name')

    # The three helpers below read _state directly and must be called with the
    # lock already held (the meter loop holds it for the whole update).

    def _num(self, addr: str, default: float = 0.0) -> float:
        try:
            return float(self._state[addr])
        except (KeyError, TypeError, ValueError):
            return default

    def _lr_contribution(self, ch: int, level: float) -> float:
        """Power a channel's post-fader signal adds to the LR bus.

        USB capture taps inputs pre-fader, so fader/mute/LR-assign are applied
        here. Pan and channel EQ/dynamics are not modelled.
        """
        if self._state.get(f'/ch/{ch:02d}/mix/on') == 0:      # muted
            return 0.0
        if self._state.get(f'/ch/{ch:02d}/mix/lr') == 0:      # not assigned to LR
            return 0.0
        return (level * _fader_gain(self._num(f'/ch/{ch:02d}/mix/fader'))) ** 2

    def _lr_gain(self) -> float:
        if self._state.get('/lr/mix/on') == 0:
            return 0.0
        return _fader_gain(self._num('/lr/mix/fader'))

    def _alsa_meter_loop(self):
        """Read 18-ch USB audio from MR18 and compute RMS levels per channel."""
        frame_bytes = _ALSA_CHANNELS * 4  # S32_LE = 4 bytes/sample
        chunk_bytes = _ALSA_CHUNK * frame_bytes

        while self._running:
            try:
                proc = subprocess.Popen(
                    ['arecord', '-D', _ALSA_DEVICE,
                     '-c', str(_ALSA_CHANNELS),
                     '-r', str(_ALSA_RATE),
                     '-f', 'S32_LE', '-q', '--'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._alsa_proc = proc
                log.info('ALSA meter reader started on %s', _ALSA_DEVICE)

                while self._running:
                    raw = proc.stdout.read(chunk_bytes)
                    if len(raw) < chunk_bytes:
                        break
                    samples = np.frombuffer(raw, dtype='<i4').reshape(_ALSA_CHUNK, _ALSA_CHANNELS)
                    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2, axis=0)) / 2 ** 31
                    # Fetched before taking our own lock — SinkMonitorMeters has one too.
                    usb = self._usb_meters.levels
                    with self._lock:
                        # The 18-ch USB capture is rotated by a constant +10: mixer
                        # channel N arrives at index (N + 10) % 18, and the aux input
                        # (17/18) lands at indices 9/10. The rotation is mod *18* — the
                        # frame width — not mod 16; a previous mod-16 version happened to
                        # agree for ch 1-5 and was wrong for ch 6-16.
                        # No index carries the LR mix (the stream is inputs only), so LR
                        # is summed in software below.
                        lr_power = 0.0
                        for ch in range(1, NUM_STRIPS + 1):
                            level = float(rms[(ch + 10) % 18])
                            # A USB-fed channel is silent in the capture stream (the
                            # send taps ahead of the USB-return switch), so use what
                            # we send to sink channel N instead — assumed 1:1 with
                            # mixer channel N, which is how rtnsrc ships by default.
                            if self._state.get(f'/ch/{ch:02d}/preamp/rtnsw') == 1 and ch <= len(usb):
                                level = usb[ch - 1]
                            self._state[f'/ch/{ch:02d}/meter'] = level
                            lr_power += self._lr_contribution(ch, level)
                        self._state['/lr/meter'] = min(1.0, math.sqrt(lr_power) * self._lr_gain())

            except Exception as e:
                log.warning('ALSA meter error: %s', e)
            finally:
                if self._alsa_proc:
                    self._alsa_proc.terminate()
                    self._alsa_proc = None

            if self._running:
                time.sleep(2)  # retry after error

    def _run(self):
        try:
            self.status = 'Connecting…'
            with xair_api.connect('MR18', ip=self.ip) as mixer:
                self._mixer = mixer
                mixer.server.dispatcher.set_default_handler(self._on_message)

                mixer.send('/xremote')
                time.sleep(0.5)

                self._query_initial(mixer)

                self.connected = True
                self.status = f'Connected · {self.ip}'
                self._running = True
                log.info('Connected to MR18 at %s', self.ip)

                threading.Thread(
                    target=self._alsa_meter_loop, daemon=True
                ).start()
                self._usb_meters.start()

                while self._running:
                    mixer.send('/xremote')
                    # Re-query the USB-return switches: a reply dropped during the
                    # startup burst would otherwise leave those channels metering
                    # from the analog tap, which is silent for USB-fed channels.
                    for i in range(1, NUM_STRIPS + 1):
                        mixer.query(f'/ch/{i:02d}/preamp/rtnsw')
                    time.sleep(8)
        except Exception as e:
            log.error('Mixer connection failed: %s', e)
            self.connected = False
            self._running = False
            self.status = f'Error: {e}'

    def connect(self, ip: str):
        if self._running:
            return  # already connected, ignore duplicate calls
        self.ip = ip
        self._state.clear()
        self.connected = False
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._running = False
        self._usb_meters.stop()
        if self._alsa_proc:
            self._alsa_proc.terminate()
