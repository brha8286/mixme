import logging
import subprocess
import threading
import time

import numpy as np
import xair_api

log = logging.getLogger(__name__)

NUM_STRIPS = 16
_ALSA_DEVICE = 'hw:4,0'
_ALSA_CHANNELS = 18
_ALSA_RATE = 48000
_ALSA_CHUNK = 4800  # 100 ms at 48 kHz


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
            mixer.query(f'/ch/{i:02d}/config/name')
            mixer.query(f'/headamp/{i:02d}/gain')
            mixer.query(f'/headamp/{i:02d}/phantom')
        mixer.query('/lr/mix/fader')
        mixer.query('/lr/mix/on')
        mixer.query('/lr/config/name')

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
                    with self._lock:
                        # MR18's 18-ch USB capture enumerates starting at channel 6 and
                        # wraps to 1-5 at the end (confirmed empirically), not 1:1 by index.
                        for ch in range(1, NUM_STRIPS + 1):
                            self._state[f'/ch/{ch:02d}/meter'] = float(rms[(ch - 6) % 16])
                        self._state['/lr/meter'] = float(max(rms[16], rms[17]))

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

                while self._running:
                    mixer.send('/xremote')
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
        if self._alsa_proc:
            self._alsa_proc.terminate()
