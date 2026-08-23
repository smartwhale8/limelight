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
Fixed scene           ``set_user_scene``    1..3, the device rejects 4
Sleep timer           ``delay_off``         minutes, 0 cancels
Smart night light     ``enable_bl``         ``"on"`` / ``"off"``
Fatigue reminder      ``set_notifyuser``    ``"on"`` / ``"off"``
Read state            ``get_prop``          the property list in :data:`PROPS`
====================  ====================  ==========================================

Eyecare mode and brightness are coupled
---------------------------------------
Two behaviours, measured on the hardware, that a client has to respect:

1. **Enabling eyecare hands brightness to the mode.** ``set_eyecare on`` makes the lamp
   ramp to its own level over about three seconds. Observed 25 rising to 53 after one
   second and 70 after three. This is the feature working, not a defect.
2. **``set_bright`` cancels eyecare.** Sending a brightness while eyecare is on turns the
   mode off. There is no way to hold both.

The consequence is that brightness must **not** be re-applied after enabling eyecare. An
earlier version of this driver did exactly that, believing it was correcting a firmware
defect, and the effect was that eyecare switched on and immediately off again: the lamp's
base briefly showed the eye symbol and then reverted to the brightness markers.

``delay_off`` does not affect brightness at all. The apparent evidence that it did came
from issuing it during the eyecare ramp above and attributing the ramp to the wrong
command.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Capability, LightDriver, LightState, register

#: Properties readable in one ``get_prop`` call, in the order the firmware returns them.
PROPS = [
    "power",         # "on" | "off"
    "bright",        # 1..100, main light
    "notifystatus",  # "on" | "off", eye-fatigue reminder
    "ambstatus",     # "on" | "off", ambient light
    "ambvalue",      # 1..100, ambient brightness
    "eyecare",       # "on" | "off"
    "scene_num",     # 1..3
    "bls",           # "on" | "off", smart night light
    "dvalue",        # sleep timer, minutes remaining, 0 when unset
]

#: The device accepts 1, 2 and 3. Scene 4 is rejected with ``param error`` (-5001).
#:
#: The names are deliberately neutral. Setting a scene changes ``scene_num`` and nothing
#: else that is readable: brightness, eyecare and the ambient light are unchanged, and
#: that holds across a power cycle and with eyecare enabled. Whatever a scene alters is
#: not exposed through ``get_prop``, so naming them would be invention.
SCENES: dict[int, str] = {1: "Scene 1", 2: "Scene 2", 3: "Scene 3"}

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

    # ------------------------------------------------------------------------ writes

    def set_power(self, on: bool) -> Any:
        return self.transport.send("set_power", ["on" if on else "off"])

    def set_brightness(self, level: int) -> Any:
        """Set the main light.

        Note that this **cancels eyecare mode** if it is on. The hardware offers no way to
        hold both, so a client that sets brightness is implicitly leaving eyecare.
        """
        return self.transport.send("set_bright", [self.clamp_brightness(level)])

    def set_ambient(self, on: bool) -> Any:
        return self.transport.send("enable_amb", ["on" if on else "off"])

    def set_ambient_brightness(self, level: int) -> Any:
        return self.transport.send("set_amb_bright", [self.clamp_brightness(level)])

    def set_eyecare(self, on: bool) -> Any:
        """Switch eyecare mode.

        Enabling it hands brightness to the mode, which ramps to its own level over about
        three seconds. Do not re-apply brightness afterwards: that cancels the mode.
        """
        return self.transport.send("set_eyecare", ["on" if on else "off"])

    def set_scene(self, number: int) -> Any:
        """Select a fixed scene.

        Only 1, 2 and 3 are accepted; the device rejects anything else with
        ``param error``. Setting a scene changes no other readable property.
        """
        if number not in SCENES:
            raise ValueError(f"scene must be one of {sorted(SCENES)}")
        return self.transport.send("set_user_scene", [int(number)])

    def set_night_light(self, on: bool) -> Any:
        return self.transport.send("enable_bl", ["on" if on else "off"])

    def set_reminder(self, on: bool) -> Any:
        return self.transport.send("set_notifyuser", ["on" if on else "off"])

    def set_sleep_timer(self, minutes: int) -> Any:
        """Device cut-off after ``minutes``; 0 cancels it.

        The countdown runs on the device, so it survives this application exiting. It does
        not disturb brightness or any other setting.
        """
        minutes = max(0, int(minutes))
        return self.transport.send("delay_off", [minutes])
