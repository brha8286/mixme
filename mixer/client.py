import logging
import struct
import threading
import time

import xair_api

log = logging.getLogger(__name__)

NUM_STRIPS = 16


class MixerClient:
    def __init__(self):
        self.ip: str = ''
        self.status: str = 'Not connected'
        self._state: dict = {}
        self._lock = threading.Lock()
        self._mixer = None
        self._running = False
        self.connected = False

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

        # meter blob: parse into per-channel float entries
        if addr == '/meters/0':
            blob = data[0]
            if isinstance(blob, (bytes, bytearray)) and len(blob) >= NUM_STRIPS * 4:
                floats = struct.unpack_from(f'<{len(blob) // 4}f', blob)
                with self._lock:
                    for i in range(NUM_STRIPS):
                        self._state[f'/ch/{i + 1:02d}/meter'] = floats[i]
            return

        if self._mixer:
            self._mixer._info_response = list(data)
        val = data[0] if len(data) == 1 else list(data)
        with self._lock:
            self._state[addr] = val

    def _query_initial(self, mixer):
        for i in range(1, NUM_STRIPS + 1):
            mixer.query(f'/ch/{i:02d}/config/name')
            mixer.query(f'/headamp/{i:03d}/gain')
            mixer.query(f'/headamp/{i:03d}/phantom')
        mixer.query('/lr/config/name')

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

                while self._running:
                    mixer.send('/xremote')
                    time.sleep(8)
        except Exception as e:
            log.error('Mixer connection failed: %s', e)
            self.connected = False
            self.status = f'Error: {e}'

    def connect(self, ip: str):
        self.ip = ip
        self._state.clear()
        self.connected = False
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._running = False
