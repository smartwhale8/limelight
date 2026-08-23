"""A fake miIO device, so the suite runs with no hardware and no network.

:class:`FakeTransport` implements :class:`~lamplight.drivers.base.Transport` against an
in-memory property dictionary. It reproduces the two firmware defects the real lamp has,
because a fake that behaves better than the hardware would let the compensation code rot
undetected:

1. ``set_eyecare`` resets ``bright`` to :data:`QUIRK_BRIGHTNESS`.
2. ``delay_off`` resets ``bright`` to :data:`QUIRK_BRIGHTNESS`.

It also records every command in :attr:`FakeTransport.calls`, which is how tests assert
on what was sent rather than only on the resulting state.
"""

from __future__ import annotations

from typing import Any

from lamplight.drivers.base import DeviceUnreachable, Transport

#: The value the real firmware snaps brightness to after a quirk-prone command.
QUIRK_BRIGHTNESS = 70

DEFAULT_PROPS: dict[str, Any] = {
    "power": "off",
    "bright": 50,
    "notifystatus": "off",
    "ambstatus": "off",
    "ambvalue": 41,
    "eyecare": "off",
    "scene_num": 1,
    "bls": "on",
    "dvalue": 0,
}

DEFAULT_INFO = {
    "model": "philips.light.sread1",
    "fw_ver": "1.2.8",
    "hw_ver": "ESP8266",
    "mac": "AA:BB:CC:DD:EE:FF",
    "token": "0" * 32,
    "netif": {"localIp": "192.168.1.50", "mask": "255.255.255.0", "gw": "192.168.1.1"},
}


class FakeTransport(Transport):
    """An in-memory stand-in for :class:`~lamplight.drivers.miio_transport.MiioTransport`."""

    def __init__(self, props: dict | None = None, ip: str = "192.168.1.50",
                 fail_after: int | None = None, quirks: bool = True):
        """``fail_after`` makes every command past that count raise, to test error paths."""
        self.props = dict(props or DEFAULT_PROPS)
        self._ip = ip
        self.calls: list[tuple[str, Any]] = []
        self.fail_after = fail_after
        self.quirks = quirks
        self.info_calls = 0

    @property
    def address(self) -> str:
        return self._ip

    def info(self) -> dict:
        self.info_calls += 1
        return dict(DEFAULT_INFO)

    # ------------------------------------------------------------------ commands

    def send(self, command: str, params: list | dict | None = None) -> Any:
        self.calls.append((command, params))
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise DeviceUnreachable(f"{command} failed (fake transport)")

        p = params or []

        if command == "get_prop":
            return [self.props.get(name) for name in p]
        if command == "set_power":
            self.props["power"] = p[0]
        elif command == "set_bright":
            self.props["bright"] = int(p[0])
        elif command == "set_amb_bright":
            self.props["ambvalue"] = int(p[0])
        elif command == "enable_amb":
            self.props["ambstatus"] = p[0]
        elif command == "enable_bl":
            self.props["bls"] = p[0]
        elif command == "set_notifyuser":
            self.props["notifystatus"] = p[0]
        elif command == "set_user_scene":
            self.props["scene_num"] = int(p[0])
        elif command == "set_eyecare":
            self.props["eyecare"] = p[0]
            if self.quirks:                      # quirk 1
                self.props["bright"] = QUIRK_BRIGHTNESS
        elif command == "delay_off":
            self.props["dvalue"] = int(p[0])
            if self.quirks:                      # quirk 2
                self.props["bright"] = QUIRK_BRIGHTNESS
        elif command == "miIO.config_router":
            return 0                             # the real firmware answers with an int
        else:
            raise DeviceUnreachable(f"unknown command {command}")
        return ["ok"]

    # ------------------------------------------------------------------- helpers

    def commands(self) -> list[str]:
        """Just the command names, in order."""
        return [c for c, _ in self.calls]

    def sent(self, command: str) -> list[Any]:
        """Every parameter list sent for ``command``."""
        return [p for c, p in self.calls if c == command]
