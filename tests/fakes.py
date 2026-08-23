"""A fake miIO device, so the suite runs with no hardware and no network.

:class:`FakeTransport` implements :class:`~limelight.drivers.base.Transport` against an
in-memory property dictionary. It reproduces the real coupling between eyecare mode and
brightness, measured on the hardware, because a fake that behaved more conveniently than
the device would hide exactly the bug this models:

1. ``set_eyecare on`` hands brightness to the mode, which moves it to
   :data:`EYECARE_BRIGHTNESS`.
2. ``set_bright`` **cancels eyecare**. There is no way to hold both.

An earlier driver re-applied brightness after enabling eyecare, believing it was
correcting a firmware defect. The effect was that eyecare switched on and immediately off
again. Modelling rule 2 here is what makes that a test failure rather than a bug report.

It also records every command in :attr:`FakeTransport.calls`, which is how tests assert
on what was sent rather than only on the resulting state.
"""

from __future__ import annotations

from typing import Any

from limelight.drivers.base import DeviceUnreachable, Transport

#: The level eyecare mode ramps brightness to on the real hardware.
EYECARE_BRIGHTNESS = 70

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
    """An in-memory stand-in for :class:`~limelight.drivers.miio_transport.MiioTransport`."""

    def __init__(self, props: dict | None = None, ip: str = "192.168.1.50",
                 fail_after: int | None = None, couple_eyecare: bool = True):
        """``fail_after`` makes every command past that count raise, to test error paths.

        ``couple_eyecare=False`` drops the eyecare/brightness coupling, for tests that
        want to isolate something else.
        """
        self.props = dict(props or DEFAULT_PROPS)
        self._ip = ip
        self.calls: list[tuple[str, Any]] = []
        self.fail_after = fail_after
        self.couple_eyecare = couple_eyecare
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
            if self.couple_eyecare:
                # Measured: setting brightness cancels eyecare on the real device.
                self.props["eyecare"] = "off"
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
            if self.couple_eyecare and p[0] == "on":
                # Measured: the mode takes brightness to its own level.
                self.props["bright"] = EYECARE_BRIGHTNESS
        elif command == "delay_off":
            # Measured: this disturbs nothing else.
            self.props["dvalue"] = int(p[0])
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
