import socket
import threading
import time

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

PORT = 10024


def _build_xinfo() -> bytes:
    return OscMessageBuilder(address='/xinfo').build().dgram


def _parse_response(data: bytes, src_ip: str) -> dict | None:
    try:
        msg = OscMessage(data)
        params = msg.params
        return {
            'ip':       params[0] if len(params) > 0 else src_ip,
            'name':     params[1] if len(params) > 1 else '',
            'model':    params[2] if len(params) > 2 else 'Unknown',
            'firmware': params[3] if len(params) > 3 else '',
        }
    except Exception:
        return None


class DiscoveryScanner:
    """
    Continuously broadcasts /xinfo and collects mixer responses.
    Results accumulate in .mixers (keyed by IP) until stop() is called.
    """

    def __init__(self):
        self.mixers: dict[str, dict] = {}
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        sock.bind(('', 0))
        msg = _build_xinfo()

        try:
            while not self._stop.is_set():
                sock.sendto(msg, ('255.255.255.255', PORT))
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline and not self._stop.is_set():
                    try:
                        data, addr = sock.recvfrom(512)
                        info = _parse_response(data, addr[0])
                        if info:
                            self.mixers[info['ip']] = info
                    except socket.timeout:
                        break
        finally:
            sock.close()
