#!/usr/bin/env python3
"""Recover a token from a device in setup mode, and optionally provision it.

An unprovisioned miIO device runs its own Wi-Fi access point, and on that network it
answers an unauthenticated handshake with its token in plaintext. This tool performs that
exchange and, if given a password, hands the device your Wi-Fi credentials so it joins your
network permanently.

Why this waits instead of switching networks itself
---------------------------------------------------
On recent macOS, a process without Location Services authorization cannot read Wi-Fi
network names: every SSID reads as ``<redacted>`` and ``networksetup -setairportnetwork``
fails with ``-3900`` even for the network already joined. Rather than requiring that
authorization, this tool watches for the subnet to change and acts when it sees you arrive.

It also waits for you to return to your normal network before exiting, so whatever launched
it has connectivity again by the time it finishes.

Usage
-----
    python tools/adopt_softap.py --home-ssid "YourNetwork"
    python tools/adopt_softap.py --home-ssid "YourNetwork" --password-file /tmp/wifi_pass

Supply the password through a file rather than an argument, so it appears neither in your
shell history nor in ``ps`` output. The file is deleted once provisioning succeeds.

Sequence
--------
1. Wait for this machine to join the device's access point.
2. Handshake on UDP 54321 and record the token. It is written to disk before anything else
   is attempted, because it is the irreplaceable artefact.
3. Read the device's self-description, and scan for any other control surface.
4. If a password was supplied, send ``miIO.config_router``. The device then reboots and
   drops its access point.
5. Wait for this machine to return to the home subnet, then locate the device there and
   confirm the token still authenticates.

Only step 4 changes anything on the device.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# Allow running straight from a checkout, without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limelight.drivers.base import DeviceError
from limelight.drivers.miio_transport import (
    HELLO,
    MIIO_PORT,
    MiioTransport,
    handshake,
)
from limelight.drivers.philips_eyecare import PROPS

#: miIO setup networks hand out 192.168.4.x and answer here, advertising no gateway.
DEFAULT_SOFTAP_HOST = "192.168.4.1"


# --------------------------------------------------------------------- shell helpers

def sh(*args: str, timeout: int = 20) -> str:
    """Run a command and return its combined output, never raising."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except Exception as exc:
        return f"<error {exc}>"


def current_ipv4(iface: str) -> str | None:
    """Return the interface's IPv4 address, or None. Works on macOS and Linux."""
    out = sh("ipconfig", "getifaddr", iface)
    if re.fullmatch(r"[0-9.]{7,15}", out or ""):
        return out
    out = sh("sh", "-c", f"ip -4 -o addr show dev {iface} 2>/dev/null | awk '{{print $4}}'")
    m = re.search(r"([0-9.]{7,15})/", out or "")
    return m.group(1) if m else None


def default_gateway() -> str | None:
    """Return the default gateway, or None. A miIO setup network advertises none."""
    m = re.search(r"gateway:\s*([0-9.]+)", sh("route", "-n", "get", "default"))
    if m:
        return m.group(1)
    m = re.search(r"default via ([0-9.]+)", sh("ip", "route", "show", "default"))
    return m.group(1) if m else None


def mac_of(ip: str) -> str | None:
    sh("ping", "-c", "1", "-W", "600", ip)
    m = re.search(r"([0-9a-f]{1,2}(?::[0-9a-f]{1,2}){5})", sh("arp", "-n", ip), re.I)
    return m.group(1) if m else None


# ------------------------------------------------------------------ network probing

def sweep(prefix: str, timeout: float = 4.0) -> list[dict]:
    """Hello every host on a /24 plus the broadcast address, and collect responders."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.02)
    for i in range(1, 255):
        # An unroutable host is normal on a sweep; keep going.
        with contextlib.suppress(OSError):
            s.sendto(HELLO, (f"{prefix}{i}", MIIO_PORT))
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
            tok = data[16:32]
            found[addr[0]] = {
                "ip": addr[0],
                "device_id": int.from_bytes(data[8:12], "big"),
                "token": tok.hex() if tok not in (b"\xff" * 16, b"\x00" * 16) else None,
            }
    s.close()
    return list(found.values())


def scan_tcp(ip: str) -> list[int]:
    """Report open TCP ports. This hardware has none; anything found is worth knowing."""
    open_ports = []
    for port in (22, 23, 80, 443, 1883, 6668, 8080, 8443):
        s = socket.socket()
        s.settimeout(0.7)
        if s.connect_ex((ip, port)) == 0:
            open_ports.append(port)
        s.close()
    return open_ports


# --------------------------------------------------------------------------- runner

class Adoption:
    """Drives the adoption sequence and records everything it learns."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.report: dict = {"log": [], "token_captured": False,
                             "provisioned": False, "verified_on_home_network": False}
        self.out_dir = Path(args.output).expanduser()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.out_dir / "device_token.json"
        self.report_file = self.out_dir / "adoption_report.json"

    # ------------------------------------------------------------------ plumbing

    def log(self, msg: str, **kw) -> None:
        self.report["log"].append({"msg": msg, **kw})
        print(f">>> {msg}" + (f"  {kw}" if kw else ""), flush=True)
        self.save()

    def save(self) -> None:
        self.report_file.write_text(json.dumps(self.report, indent=2, default=str))

    def address(self) -> str | None:
        return current_ipv4(self.args.interface)

    def on_home_network(self) -> bool:
        ip = self.address()
        return bool(ip) and ip.startswith(self.args.home_subnet)

    def on_setup_network(self) -> bool:
        ip = self.address()
        return (bool(ip)
                and not ip.startswith(self.args.home_subnet)
                and not ip.startswith("169.254."))

    def wait_for(self, predicate, seconds: int, label: str) -> bool:
        end = time.time() + seconds
        last = None
        while time.time() < end:
            if predicate():
                return True
            cur = self.address()
            if cur != last:
                print(f"    [{label}] address is now {cur}", flush=True)
                last = cur
            time.sleep(1)
        return False

    def password(self) -> str | None:
        """Read the Wi-Fi password, if a file was given. Re-read late, not at startup."""
        if not self.args.password_file:
            return None
        p = Path(self.args.password_file).expanduser()
        if not p.exists():
            return None
        return p.read_text().strip() or None

    # -------------------------------------------------------------------- stages

    def banner(self) -> None:
        enabled = "ENABLED" if self.args.password_file else "DISABLED (no --password-file)"
        print("=" * 74)
        print("  ADOPTION - waiting for you to join the device's setup access point")
        print("=" * 74)
        print("  1. Put the device into setup mode. On the Philips Eyecare Smart Lamp 2,")
        print("     hold the touch power button for about 5 seconds, until the indicator")
        print("     turns YELLOW and FLASHES.")
        print("  2. From your Wi-Fi menu, join the device's access point. The name looks")
        print("     like  philips-light-sread1_miapXXXX  and it is open, with no password.")
        print("  3. Do nothing else. This tool detects the change and proceeds.")
        print(f"  Provisioning onto '{self.args.home_ssid}' is {enabled}.")
        print("=" * 74, flush=True)

    def capture_token(self, host: str) -> dict:
        """Handshake, and persist the token immediately if one is disclosed."""
        hs = handshake(host, tries=self.args.tries)
        self.report["handshake"] = {k: v for k, v in hs.items() if k != "raw32"}
        self.log("handshake", **self.report["handshake"])

        if not hs.get("token_disclosed"):
            # Some units answer only on the .1 host even when DHCP says otherwise.
            for cand in sweep(".".join((self.address() or "192.168.4.1").split(".")[:3]) + "."):
                alt = handshake(cand["ip"], tries=3)
                if alt.get("token_disclosed"):
                    self.log("token disclosed by another host", ip=cand["ip"])
                    return alt | {"host": cand["ip"]}
            return hs | {"host": host}
        return hs | {"host": host}

    def persist_token(self, hs: dict) -> None:
        payload = {
            "token": hs["token"],
            "device_id": hs["device_id"],
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "captured_from": hs["host"],
        }
        self.token_file.write_text(json.dumps(payload, indent=2))
        os.chmod(self.token_file, 0o600)
        self.report["token_captured"] = True
        self.log("TOKEN CAPTURED and written to disk",
                 file=str(self.token_file), device_id=hs["device_id"])

    def interrogate(self, host: str, token: str) -> None:
        try:
            transport = MiioTransport(host, token)
            self.report["info"] = {k: v for k, v in transport.info().items() if k != "token"}
            self.report["properties"] = dict(
                zip(PROPS, transport.send("get_prop", PROPS), strict=False))
            self.log("interrogated the device",
                     model=self.report["info"].get("model"),
                     firmware=self.report["info"].get("fw_ver"))
        except DeviceError as exc:
            self.report["interrogation_error"] = str(exc)
            self.log("interrogation failed", error=str(exc))

    def provision(self, host: str, token: str, password: str) -> None:
        """Hand over Wi-Fi credentials. This reboots the device."""
        try:
            transport = MiioTransport(host, token)
            self.log("sending miIO.config_router", ssid=self.args.home_ssid)
            reply = transport.configure_wifi(self.args.home_ssid, password, uid=0)
            self.report["config_router_reply"] = reply
            # This firmware answers 0 for success; older units answer ["ok"].
            self.report["provisioned"] = reply in (0, ["ok"], "ok")
            self.log("config_router replied", reply=reply,
                     provisioned=self.report["provisioned"])
        except DeviceError as exc:
            self.report["config_router_error"] = str(exc)
            self.log("config_router failed", error=str(exc))

    def verify_on_home_network(self, device_id: int, token: str) -> None:
        """Find the device on the home subnet and confirm the token still works."""
        for attempt in range(1, self.args.verify_attempts + 1):
            time.sleep(self.args.verify_interval)
            responders = sweep(self.args.home_subnet, timeout=4)
            self.log("sweeping the home network", attempt=attempt,
                     responders=[r["ip"] for r in responders])
            matches = [r for r in responders if r["device_id"] == device_id] or responders
            if not matches:
                continue
            ip = matches[0]["ip"]
            self.report["home_address"] = ip
            try:
                transport = MiioTransport(ip, token)
                state = dict(zip(PROPS, transport.send("get_prop", PROPS), strict=False))
                self.report["home_state"] = state
                self.report["verified_on_home_network"] = True
                self.log("device located and token verified", ip=ip)
            except DeviceError as exc:
                self.log("found the device but the token did not authenticate",
                         ip=ip, error=str(exc))
            return

    # ----------------------------------------------------------------------- run

    def run(self) -> int:
        self.banner()
        self.report["home_address_at_start"] = self.address()

        if not self.wait_for(self.on_setup_network, self.args.timeout, "waiting"):
            self.report["error"] = "timed out waiting for the setup network"
            self.log("TIMED OUT waiting for the setup access point")
            return 2

        time.sleep(4)  # let DHCP and routing settle
        client_ip, gateway = self.address(), default_gateway()
        self.report.update({"client_address": client_ip, "gateway": gateway})
        self.log("joined the setup network", client=client_ip, gateway=gateway)

        # The setup network advertises no gateway, so fall back to the known host.
        host = gateway or self.args.softap_host
        self.report["device_mac"] = mac_of(host)

        hs = self.capture_token(host)
        host = hs.get("host", host)
        self.report["setup_address"] = host

        if hs.get("token_disclosed"):
            self.persist_token(hs)
        else:
            self.report["error"] = "the device did not disclose a token"
            self.log("NO TOKEN DISCLOSED - the device is probably bound to an account",
                     hint="see docs/ADOPTION.md")

        self.report["open_tcp_ports"] = scan_tcp(host)
        self.log("tcp scan", open_ports=self.report["open_tcp_ports"])

        if self.report["token_captured"]:
            self.interrogate(host, hs["token"])
            password = self.password()
            if password:
                self.provision(host, hs["token"], password)
            else:
                self.log("no password supplied, leaving the device in setup mode")

        print("=" * 74)
        print(f"  DONE ON THE DEVICE NETWORK. Rejoin '{self.args.home_ssid}' now.")
        print("=" * 74, flush=True)

        if not self.wait_for(self.on_home_network, self.args.timeout, "returning"):
            self.report["error_return"] = "did not return to the home subnet"
            self.log("did not detect a return to the home network")
            return 3

        self.log("back on the home network", address=self.address())

        if self.report["provisioned"]:
            self.verify_on_home_network(hs["device_id"], hs["token"])

        if self.args.password_file:
            p = Path(self.args.password_file).expanduser()
            if p.exists():
                p.unlink()
                self.log("deleted the Wi-Fi password file", file=str(p))

        self.save()
        self.summarise(hs)
        return 0 if self.report["token_captured"] else 1

    def summarise(self, hs: dict) -> None:
        print()
        print("=" * 74)
        if self.report["token_captured"]:
            print("  Token recovered.")
            print(f"    token file   {self.token_file}")
            print(f"    device id    {hs['device_id']}")
            if self.report.get("verified_on_home_network"):
                print(f"    home address {self.report['home_address']}")
                print()
                print("  Adopt it with:")
                print(f"    limelight adopt --ip {self.report['home_address']} "
                      f"--token {hs['token']}")
            elif self.report["provisioned"]:
                print("  Provisioned, but not yet located on the home network.")
                print("  It may still be joining. Try:  limelight discover")
            else:
                print("  Not provisioned. The device is still in setup mode.")
                print("  Re-run with --password-file to hand it your Wi-Fi credentials.")
        else:
            print("  No token recovered.")
            print("  The device is probably bound to a cloud account. See docs/ADOPTION.md")
            print("  for the recovery options.")
        print(f"    full report  {self.report_file}")
        print("=" * 74, flush=True)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home-ssid", required=True,
                    help="the Wi-Fi network the device should join, 2.4 GHz")
    ap.add_argument("--password-file",
                    help="file holding the Wi-Fi password; deleted after use. "
                         "Omit to recover the token without provisioning.")
    ap.add_argument("--home-subnet", default="192.168.1.",
                    help="your subnet prefix including the trailing dot "
                         "(default: %(default)s)")
    ap.add_argument("--interface", default="en0",
                    help="wireless interface to watch (default: %(default)s; "
                         "often wlan0 on Linux)")
    ap.add_argument("--softap-host", default=DEFAULT_SOFTAP_HOST,
                    help="address the device answers on in setup mode "
                         "(default: %(default)s)")
    ap.add_argument("--output", default=".",
                    help="directory for the token and report files (default: %(default)s)")
    ap.add_argument("--timeout", type=int, default=1200,
                    help="seconds to wait for each network change (default: %(default)s)")
    ap.add_argument("--tries", type=int, default=10,
                    help="handshake attempts (default: %(default)s)")
    ap.add_argument("--verify-attempts", type=int, default=12,
                    help="sweeps of the home network after provisioning "
                         "(default: %(default)s)")
    ap.add_argument("--verify-interval", type=int, default=10,
                    help="seconds between those sweeps (default: %(default)s)")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if not args.home_subnet.endswith("."):
        args.home_subnet += "."
    try:
        return Adoption(args).run()
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
