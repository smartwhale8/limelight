"""miIO transport: encrypted UDP to Xiaomi-ecosystem devices, with retry and recovery.

Protocol
--------
A miIO device accepts JSON-RPC payloads as single UDP datagrams on port 54321. Each
payload is encrypted with AES-128-CBC where the key is ``md5(token)`` and the IV is
``md5(key + token)``. The 16-byte ``token`` is the device's only credential.
``python-miio`` implements the framing and crypto; this module adds the operational
behaviour a long-running service needs.

Behaviour added here
--------------------
*Retry.* A lost datagram is indistinguishable from a dead device over UDP, so commands
are retried with increasing backoff before being declared failed.

*Rediscovery.* Addresses come from DHCP and move. On repeated failure the transport
re-runs discovery, matches the device by its stable device id, and updates its address.

*Serialisation.* One lock guards all access. These devices tolerate no concurrency, and
the scheduler thread and the web request threads share a single transport.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
import time
from typing import Any

from miio import Device
from miio.exceptions import DeviceException

from .base import DeviceUnreachable, Transport

log = logging.getLogger(__name__)

MIIO_PORT = 54321

#: An unencrypted miIO hello. The reply carries the device id and, on firmware that
#: discloses it, the token. Discovery needs no credential because this exchange precedes
#: encryption. See ``docs/PROTOCOL.md``.
HELLO = bytes.fromhex("21310020" + "ff" * 28)


def discover(device_id: int | None = None, subnet: str = "192.168.1.",
             timeout: float = 4.0) -> list[dict]:
    """Return miIO devices answering on ``subnet``, optionally filtered by device id.

    Sends the hello datagram to every host on the /24 and to the broadcast address.
    ``token`` is populated only for devices whose firmware discloses it; treat its
    presence as a finding, not a guarantee.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.02)
    for i in range(1, 255):
        # A host that cannot be routed to is normal on a sweep; keep going.
        with contextlib.suppress(OSError):
            s.sendto(HELLO, (f"{subnet}{i}", MIIO_PORT))
    with contextlib.suppress(OSError):
        s.sendto(HELLO, ("255.255.255.255", MIIO_PORT))

    found: dict[str, dict] = {}
    s.settimeout(timeout)
    end = time.time() + timeout + 1
    while time.time() < end:
        try:
            data, addr = s.recvfrom(1024)
        except TimeoutError:
            break
        if len(data) >= 32 and data[:2] == b"\x21\x31":
            did = int.from_bytes(data[8:12], "big")
            if device_id is not None and did != device_id:
                continue
            tok = data[16:32]
            found[addr[0]] = {
                "ip": addr[0],
                "device_id": did,
                "token": tok.hex() if tok not in (b"\xff" * 16, b"\x00" * 16) else None,
            }
    s.close()
    return list(found.values())


def handshake(ip: str, tries: int = 8, timeout: float = 1.5) -> dict:
    """Send the hello datagram to one host and decode the reply.

    Used during adoption to recover a token from a device that discloses one. Returns a
    dictionary with ``token_disclosed`` set accordingly; never raises on a silent host.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        for attempt in range(1, tries + 1):
            try:
                s.sendto(HELLO, (ip, MIIO_PORT))
                data, _ = s.recvfrom(1024)
            except TimeoutError:
                continue
            except OSError as exc:
                return {"error": f"socket: {exc}"}
            if len(data) >= 32 and data[:2] == b"\x21\x31":
                tok = data[16:32]
                disclosed = tok not in (b"\xff" * 16, b"\x00" * 16)
                return {
                    "device_id": int.from_bytes(data[8:12], "big"),
                    "stamp": int.from_bytes(data[12:16], "big"),
                    "token": tok.hex() if disclosed else None,
                    "token_disclosed": disclosed,
                    "raw32": data[:32].hex(),
                    "attempts": attempt,
                }
        return {"error": "no miIO reply", "attempts": tries, "token_disclosed": False}
    finally:
        s.close()


class MiioTransport(Transport):
    """A :class:`~lamplight.drivers.base.Transport` over miIO, safe for use from any thread."""

    def __init__(self, ip: str, token: str, device_id: int | None = None,
                 subnet: str = "192.168.1.", retries: int = 3):
        if len(token) != 32:
            raise ValueError("a miIO token is 32 hexadecimal characters (16 bytes)")
        self._ip = ip
        self.token = token
        self.device_id = device_id
        self.subnet = subnet
        self.retries = max(1, retries)
        self._lock = threading.RLock()
        self._dev = Device(ip, token)
        self.last_success: float | None = None

    @property
    def address(self) -> str:
        return self._ip

    # ------------------------------------------------------------------- recovery

    def rediscover(self) -> bool:
        """Locate the device again by device id. Returns True when an address was found."""
        if self.device_id is None:
            return False
        log.warning("device unreachable at %s, rediscovering by id %s", self._ip, self.device_id)
        for cand in discover(self.device_id, self.subnet):
            if cand["ip"] != self._ip:
                log.warning("device moved from %s to %s", self._ip, cand["ip"])
            self._ip = cand["ip"]
            self._dev = Device(self._ip, self.token)
            return True
        return False

    # -------------------------------------------------------------------- commands

    def send(self, command: str, params: list | dict | None = None) -> Any:
        if params is None:
            params = []
        last: Exception | None = None
        with self._lock:
            for attempt in range(1, self.retries + 1):
                try:
                    reply = self._dev.send(command, params)
                    self.last_success = time.time()
                    return reply
                except DeviceException as exc:
                    last = exc
                    log.debug("%s failed (%d/%d): %r", command, attempt, self.retries, exc)
                    if attempt < self.retries:
                        time.sleep(0.4 * attempt)
                        if attempt == self.retries - 1:
                            self.rediscover()
        raise DeviceUnreachable(f"{command} failed after {self.retries} attempts: {last!r}")

    def info(self) -> dict:
        with self._lock:
            try:
                return self._dev.info().raw
            except DeviceException as exc:
                raise DeviceUnreachable(f"miIO.info failed: {exc!r}") from exc

    # ------------------------------------------------------------------ provisioning

    def configure_wifi(self, ssid: str, password: str, uid: int = 0) -> Any:
        """Hand the device Wi-Fi credentials with ``miIO.config_router``.

        ``uid=0`` provisions without binding the device to a cloud account, which keeps the
        token stable. Binding regenerates it.

        This deliberately does not use ``python-miio``'s ``Device.configure_wifi``, which
        indexes the reply as ``send(...)[0]`` and therefore raises ``TypeError`` against
        firmware that answers with a bare integer. The command itself succeeds; only that
        library's response handling fails.
        """
        return self.send("miIO.config_router",
                         {"ssid": ssid, "passwd": password, "uid": uid})
