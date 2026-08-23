"""Driver for the Xiaomi Philips Eyecare Smart Lamp 2 (``philips.light.sread1``).

Hardware: ESP8266. Verified against firmware ``1.2.8``, MCU ``0026``, Wi-Fi
``1.4.0(30e0bd0)``. Transport is miIO over UDP 54321; the device exposes no TCP ports.

Command surface
---------------
====================  ====================  ==========================================
Function              miIO method           Argument
====================  ====================  ==========================================
Power                 ``set_power``         ``"on"`` / ``"off"``
Main brightness       ``set_bright``        1..100
Eyecare mode          ``set_eyecare``       ``"on"`` / ``"off"``
Ambient light         ``enable_amb``        ``"on"`` / ``"off"``
Ambient brightness    ``set_amb_bright``    1..100
Fixed scene           ``set_user_scene``    1..4
Sleep timer           ``delay_off``         minutes, 0 cancels
Smart night light     ``enable_bl``         ``"on"`` / ``"off"``
Fatigue reminder      ``set_notifyuser``    ``"on"`` / ``"off"``
Read state            ``get_prop``          the property list in :data:`PROPS`
====================  ====================  ==========================================

Firmware quirks, measured rather than assumed
---------------------------------------------
1. ``set_eyecare`` resets ``bright`` to a stored value. Observed 25 becoming 53.
2. ``delay_off`` also resets ``bright``. Observed 53 becoming 70.

Neither is documented by the vendor. :meth:`PhilipsEyecareLamp._preserve_brightness`
reads brightness before such a call and re-applies it if the firmware moved it, because
a user setting a sleep timer did not ask for a brightness change.
"""

from __future__ import annotations

import logging
import time
from typing import Any, ClassVar

from .base import Capability, LightDriver, LightState, Transport, register

log = logging.getLogger(__name__)

#: Properties readable in one ``get_prop`` call, in the order the firmware returns them.
PROPS = [
    "power",         # "on" | "off"
    "bright",        # 1..100, main light
    "notifystatus",  # "on" | "off", eye-fatigue reminder
    "ambstatus",     # "on" | "off", ambient light
    "ambvalue",      # 1..100, ambient brightness
    "eyecare",       # "on" | "off"
    "scene_num",     # 1..4
    "bls",           # "on" | "off", smart night light
    "dvalue",        # sleep timer, minutes remaining, 0 when unset
]

SCENES: dict[int, str] = {1: "Study", 2: "Office", 3: "Reading", 4: "Bedtime"}

#: Seconds to wait after a quirk-prone command before re-reading brightness.
QUIRK_SETTLE_SECONDS = 0.4


@register
class PhilipsEyecareLamp(LightDriver):
    """Philips Eyecare Smart Lamp 2."""

    model: ClassVar[str] = "philips.light.sread1"
    display_name: ClassVar[str] = "Philips Eyecare Smart Lamp 2"
    scenes: ClassVar[dict[int, str]] = SCENES
    brightness_range: ClassVar[tuple[int, int]] = (1, 100)
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.POWER,
        Capability.BRIGHTNESS,
        Capability.AMBIENT,
        Capability.AMBIENT_BRIGHTNESS,
        Capability.EYECARE,
        Capability.SCENES,
        Capability.NIGHT_LIGHT,
        Capability.REMINDER,
        Capability.SLEEP_TIMER,
    })

    def __init__(self, transport: Transport, compensate_quirks: bool = True):
        """``compensate_quirks=False`` disables brightness restoration, for protocol study."""
        super().__init__(transport)
        self.compensate_quirks = compensate_quirks

    # ------------------------------------------------------------------------- reads

    def state(self) -> LightState:
        # strict=False: some firmware returns fewer values than requested, and
        # LightState reads with .get() so a missing property becomes None.
        values = dict(zip(PROPS, self.transport.send("get_prop", PROPS), strict=False))
        scene = int(values.get("scene_num") or 1)
        return LightState(
            on=values.get("power") == "on",
            brightness=int(values.get("bright") or 0),
            ambient_on=values.get("ambstatus") == "on",
            ambient_brightness=int(values.get("ambvalue") or 0),
            eyecare=values.get("eyecare") == "on",
            scene=scene,
            scene_name=SCENES.get(scene),
            night_light=values.get("bls") == "on",
            reminder=values.get("notifystatus") == "on",
            sleep_timer_minutes=int(values.get("dvalue") or 0),
            raw=dict(values),
        )

    # ------------------------------------------------------------- quirk compensation

    def _preserve_brightness(self, call) -> Any:
        """Run ``call``, then undo any brightness change the firmware made unbidden."""
        if not self.compensate_quirks:
            return call()
        want = self.state().brightness
        reply = call()
        time.sleep(QUIRK_SETTLE_SECONDS)
        now = self.state().brightness
        if want and now != want:
            log.info("firmware moved brightness %s to %s, restoring", now, want)
            self.transport.send("set_bright", [int(want)])
        return reply

    # ------------------------------------------------------------------------ writes

    def set_power(self, on: bool) -> Any:
        return self.transport.send("set_power", ["on" if on else "off"])

    def set_brightness(self, level: int) -> Any:
        return self.transport.send("set_bright", [self.clamp_brightness(level)])

    def set_ambient(self, on: bool) -> Any:
        return self.transport.send("enable_amb", ["on" if on else "off"])

    def set_ambient_brightness(self, level: int) -> Any:
        return self.transport.send("set_amb_bright", [self.clamp_brightness(level)])

    def set_eyecare(self, on: bool) -> Any:
        # Quirk 1: this command resets main brightness.
        return self._preserve_brightness(
            lambda: self.transport.send("set_eyecare", ["on" if on else "off"]))

    def set_scene(self, number: int) -> Any:
        if number not in SCENES:
            raise ValueError(f"scene must be one of {sorted(SCENES)}")
        return self.transport.send("set_user_scene", [int(number)])

    def set_night_light(self, on: bool) -> Any:
        return self.transport.send("enable_bl", ["on" if on else "off"])

    def set_reminder(self, on: bool) -> Any:
        return self.transport.send("set_notifyuser", ["on" if on else "off"])

    def set_sleep_timer(self, minutes: int) -> Any:
        """Firmware cut-off after ``minutes``; 0 cancels it.

        Runs on the device, so it survives this application exiting. Quirk 2 applies.
        """
        minutes = max(0, int(minutes))
        return self._preserve_brightness(
            lambda: self.transport.send("delay_off", [minutes]))
