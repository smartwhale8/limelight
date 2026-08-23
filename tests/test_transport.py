"""miIO transport: packet parsing, token disclosure, discovery and provisioning.

These tests run against a real UDP socket on the loopback interface rather than a mock,
because the thing under test is byte-level parsing of a wire protocol. A mock that
returns tidy dictionaries would prove nothing about offsets.

:class:`FakeMiioDevice` binds a loopback port and answers the handshake with a packet
built to the same layout the hardware uses, so an error in the field offsets fails here.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from lamplight.drivers import miio_transport as mt
from lamplight.drivers.base import DeviceUnreachable

EXAMPLE_TOKEN = bytes.fromhex("00112233445566778899aabbccddeeff")
WITHHELD = b"\xff" * 16
ZEROED = b"\x00" * 16
DEVICE_ID = 12345678
STAMP = 4242


def hello_reply(token: bytes, device_id: int = DEVICE_ID, stamp: int = STAMP) -> bytes:
    """Build a 32-byte handshake reply in the layout the hardware uses.

    Bytes 0..2 magic, 2..4 length, 4..8 unused, 8..12 device id, 12..16 uptime stamp,
    16..32 the token or a withheld marker.
    """
    return (b"\x21\x31" + (32).to_bytes(2, "big") + b"\x00" * 4
            + device_id.to_bytes(4, "big") + stamp.to_bytes(4, "big") + token)


class FakeMiioDevice:
    """A loopback UDP responder that answers handshakes like the real firmware."""

    def __init__(self, token: bytes = EXAMPLE_TOKEN, silent: bool = False,
                 truncated: bool = False, bad_magic: bool = False):
        self.token = token
        self.silent = silent
        self.truncated = truncated
        self.bad_magic = bad_magic
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.requests: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        self.sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(1024)
            except TimeoutError:
                continue
            except OSError:
                return
            self.requests.append(data)
            if self.silent:
                continue
            reply = hello_reply(self.token)
            if self.truncated:
                reply = reply[:20]
            if self.bad_magic:
                reply = b"\x00\x00" + reply[2:]
            try:
                self.sock.sendto(reply, addr)
            except OSError:
                return

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        self.sock.close()


@pytest.fixture
def device(monkeypatch):
    """Start a fake device and point the transport's port constant at it."""
    devices: list[FakeMiioDevice] = []

    def start(**kwargs) -> FakeMiioDevice:
        d = FakeMiioDevice(**kwargs)
        monkeypatch.setattr(mt, "MIIO_PORT", d.port)
        devices.append(d)
        return d

    yield start
    for d in devices:
        d.close()


# ------------------------------------------------------------------------ handshake

def test_handshake_recovers_a_disclosed_token(device):
    device()
    result = mt.handshake("127.0.0.1", tries=3)
    assert result["token"] == EXAMPLE_TOKEN.hex()
    assert result["token_disclosed"] is True
    assert result["device_id"] == DEVICE_ID
    assert result["stamp"] == STAMP


@pytest.mark.parametrize("withheld", [WITHHELD, ZEROED])
def test_handshake_reports_a_withheld_token(device, withheld):
    """A device bound to a vendor account answers with a filler value, not a token."""
    device(token=withheld)
    result = mt.handshake("127.0.0.1", tries=3)
    assert result["token"] is None
    assert result["token_disclosed"] is False
    assert result["device_id"] == DEVICE_ID, "identity is still readable"


def test_handshake_sends_the_documented_hello_packet(device):
    d = device()
    mt.handshake("127.0.0.1", tries=1)
    assert d.requests[0] == bytes.fromhex("21310020" + "ff" * 28)
    assert len(d.requests[0]) == 32


def test_handshake_gives_up_on_a_silent_device(device):
    device(silent=True)
    result = mt.handshake("127.0.0.1", tries=2, timeout=0.05)
    assert result["error"] == "no miIO reply"
    assert result["token_disclosed"] is False


def test_handshake_ignores_a_truncated_reply(device):
    device(truncated=True)
    result = mt.handshake("127.0.0.1", tries=2, timeout=0.05)
    assert "error" in result


def test_handshake_ignores_a_reply_with_the_wrong_magic(device):
    """Another service on port 54321 must not be mistaken for a miIO device."""
    device(bad_magic=True)
    result = mt.handshake("127.0.0.1", tries=2, timeout=0.05)
    assert "error" in result


def test_handshake_retries_and_reports_the_attempt_count(device):
    device()
    result = mt.handshake("127.0.0.1", tries=5)
    assert result["attempts"] == 1, "a responsive device should answer first time"


# ------------------------------------------------------------------------ discovery

def test_discover_finds_a_device_and_reports_its_token(device):
    device()
    found = mt.discover(subnet="127.0.0.", timeout=0.6)
    assert any(f["ip"] == "127.0.0.1" and f["device_id"] == DEVICE_ID for f in found)
    assert next(f for f in found if f["ip"] == "127.0.0.1")["token"] == EXAMPLE_TOKEN.hex()


def test_discover_filters_by_device_id(device):
    device()
    assert mt.discover(device_id=999999, subnet="127.0.0.", timeout=0.4) == []
    assert mt.discover(device_id=DEVICE_ID, subnet="127.0.0.", timeout=0.6) != []


def test_discover_reports_none_for_a_withheld_token(device):
    device(token=WITHHELD)
    found = mt.discover(subnet="127.0.0.", timeout=0.6)
    assert found and found[0]["token"] is None


def test_discover_returns_empty_when_nothing_answers(device):
    device(silent=True)
    assert mt.discover(subnet="127.0.0.", timeout=0.3) == []


# ------------------------------------------------------------------ construction

@pytest.mark.parametrize("bad", ["", "abc", "0" * 31, "0" * 33])
def test_a_malformed_token_is_rejected_at_construction(bad):
    """Catching this early gives a clear message instead of a decryption failure later."""
    with pytest.raises(ValueError, match="32 hexadecimal characters"):
        mt.MiioTransport("127.0.0.1", bad)


def test_a_valid_token_length_is_accepted():
    t = mt.MiioTransport("127.0.0.1", "0" * 32)
    assert t.address == "127.0.0.1"


def test_address_is_reported_from_the_transport():
    t = mt.MiioTransport("192.168.1.77", "a" * 32, device_id=5)
    assert t.address == "192.168.1.77"


# ---------------------------------------------------------------- retry and recovery

def test_send_raises_device_unreachable_after_exhausting_retries(monkeypatch):
    """A silent device must surface as DeviceUnreachable, not a library exception."""
    t = mt.MiioTransport("127.0.0.1", "0" * 32, retries=2)
    monkeypatch.setattr(mt, "MIIO_PORT", 1)          # nothing listens here
    monkeypatch.setattr(t, "_dev", _AlwaysFails())
    with pytest.raises(DeviceUnreachable, match="failed after 2 attempts"):
        t.send("get_prop", ["power"])


def test_rediscovery_is_skipped_without_a_device_id():
    """Without a stable identity there is nothing to match a moved device against."""
    t = mt.MiioTransport("127.0.0.1", "0" * 32, device_id=None)
    assert t.rediscover() is False


def test_rediscovery_updates_the_address(monkeypatch):
    t = mt.MiioTransport("192.168.1.10", "0" * 32, device_id=DEVICE_ID)
    monkeypatch.setattr(mt, "discover",
                        lambda *a, **k: [{"ip": "192.168.1.99", "device_id": DEVICE_ID}])
    assert t.rediscover() is True
    assert t.address == "192.168.1.99", "a moved device must be followed"


def test_send_records_the_time_of_the_last_success(monkeypatch):
    t = mt.MiioTransport("127.0.0.1", "0" * 32)
    monkeypatch.setattr(t, "_dev", _AlwaysWorks())
    before = time.time()
    t.send("set_power", ["on"])
    assert t.last_success is not None and t.last_success >= before


# ----------------------------------------------------------------------- provisioning

def test_configure_wifi_sends_the_documented_payload(monkeypatch):
    """The vendor library's helper crashes on this firmware; ours must send it plainly."""
    t = mt.MiioTransport("127.0.0.1", "0" * 32)
    sent = {}

    def capture(command, params=None):
        sent["command"] = command
        sent["params"] = params
        return 0                     # the real firmware answers with a bare integer

    monkeypatch.setattr(t, "send", capture)
    assert t.configure_wifi("HomeNetwork", "hunter2") == 0
    assert sent["command"] == "miIO.config_router"
    assert sent["params"] == {"ssid": "HomeNetwork", "passwd": "hunter2", "uid": 0}


def test_configure_wifi_defaults_to_no_account_binding(monkeypatch):
    """``uid=0`` provisions without binding, which is what keeps the token stable."""
    t = mt.MiioTransport("127.0.0.1", "0" * 32)
    sent = {}
    monkeypatch.setattr(t, "send", lambda c, p=None: sent.update(p or {}) or 0)
    t.configure_wifi("Net", "pass")
    assert sent["uid"] == 0


# ------------------------------------------------------------------------- doubles

class _AlwaysFails:
    """Stands in for ``miio.Device`` when every datagram is lost."""

    def send(self, command, params=None):
        from miio.exceptions import DeviceException
        raise DeviceException("no response from the device")

    def info(self):
        from miio.exceptions import DeviceException
        raise DeviceException("no response from the device")


class _AlwaysWorks:
    """Stands in for ``miio.Device`` on a healthy link."""

    def send(self, command, params=None):
        return ["ok"]
