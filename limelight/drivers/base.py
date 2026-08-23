"""Device abstraction: the contract every limelight driver implements.

Purpose
-------
This module defines the boundary that lets a device type be added without touching the
service, the scheduler or the interface. Three pieces do that work:

:class:`Capability`
    What a device can actually do. The HTTP API and the web interface interrogate this
    rather than assuming, so a device without an ambient light simply does not render
    ambient controls, and calling an unsupported operation is a clean 400 rather than a
    protocol error.

:class:`Transport`
    How bytes reach the device. It is a protocol, not a class to inherit, so a driver can
    be exercised against a fake in tests with no hardware and no network. See
    ``tests/fakes.py``.

:class:`LightDriver`
    The operations a light exposes. Unsupported operations raise
    :class:`OperationNotSupported`, which the API layer turns into a 400.

Adding a device is documented in ``docs/DEVICES.md``.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable


class DeviceError(RuntimeError):
    """Base class for every device-level failure."""


class DeviceUnreachable(DeviceError):
    """The device did not answer after retries and rediscovery."""


class OperationNotSupported(DeviceError):
    """The device has no such capability."""


class DeviceCommandError(DeviceError):
    """The device rejected the command and reported an error code.

    Distinct from :class:`DeviceUnreachable` because it is permanent: the device was
    reached, understood the request and refused it. Retrying cannot help, and the API maps
    it to a client error rather than a gateway failure.

    ``code`` is the device's own error number, for example ``-5001`` for a bad parameter.
    """

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class Capability(enum.StrEnum):
    """Discrete features a light may support.

    Values are the strings the HTTP API publishes, so they are part of the public
    contract and must not be renamed without a major version bump.
    """

    POWER = "power"
    BRIGHTNESS = "brightness"
    COLOR_TEMPERATURE = "color_temperature"
    COLOR = "color"
    AMBIENT = "ambient"
    AMBIENT_BRIGHTNESS = "ambient_brightness"
    EYECARE = "eyecare"
    SCENES = "scenes"
    NIGHT_LIGHT = "night_light"
    REMINDER = "reminder"
    SLEEP_TIMER = "sleep_timer"


@runtime_checkable
class Transport(Protocol):
    """Anything that can carry a command to a device and return its reply."""

    def send(self, command: str, params: list | dict | None = None) -> Any:
        """Issue one command and return the decoded reply, or raise :class:`DeviceError`."""
        ...

    def info(self) -> dict:
        """Return the device's self-description as a plain dictionary."""
        ...

    @property
    def address(self) -> str:
        """The current network address, which may change if the device is re-addressed."""
        ...


@dataclass
class LightState:
    """A normalised snapshot of a light.

    Fields a device does not support stay ``None``, which is how the interface tells
    "off" apart from "absent". ``raw`` keeps the untranslated device reply for debugging
    and is never part of the API contract.
    """

    on: bool = False
    brightness: int | None = None
    ambient_on: bool | None = None
    ambient_brightness: int | None = None
    eyecare: bool | None = None
    scene: int | None = None
    scene_name: str | None = None
    night_light: bool | None = None
    reminder: bool | None = None
    sleep_timer_minutes: int | None = None
    color_temperature: int | None = None
    raw: dict = field(default_factory=dict)

    def as_dict(self, include_raw: bool = False) -> dict:
        """Serialise for the API, omitting unsupported fields."""
        out = {k: v for k, v in {
            "on": self.on,
            "brightness": self.brightness,
            "ambient_on": self.ambient_on,
            "ambient_brightness": self.ambient_brightness,
            "eyecare": self.eyecare,
            "scene": self.scene,
            "scene_name": self.scene_name,
            "night_light": self.night_light,
            "reminder": self.reminder,
            "sleep_timer_minutes": self.sleep_timer_minutes,
            "color_temperature": self.color_temperature,
        }.items() if v is not None}
        out["on"] = self.on          # always present, even when False
        if include_raw:
            out["raw"] = self.raw
        return out


class LightDriver(ABC):
    """The operations limelight expects of a light.

    Subclasses declare :attr:`model`, :attr:`display_name` and :attr:`capabilities`, then
    implement the operations their capability set claims. The default implementations
    raise :class:`OperationNotSupported`, so a driver only writes what its device can do.
    """

    #: Device model identifier, as reported by the device itself. Used for registry lookup.
    model: ClassVar[str] = ""
    #: Human-readable product name.
    display_name: ClassVar[str] = ""
    #: What this driver supports.
    capabilities: ClassVar[frozenset[Capability]] = frozenset()
    #: Scene number to name, empty when the device has no scenes.
    scenes: ClassVar[dict[int, str]] = {}
    #: Inclusive brightness bounds, as the device defines them.
    brightness_range: ClassVar[tuple[int, int]] = (1, 100)

    def __init__(self, transport: Transport):
        self.transport = transport

    # ------------------------------------------------------------------ introspection

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def require(self, capability: Capability) -> None:
        if not self.supports(capability):
            raise OperationNotSupported(
                f"{self.display_name or self.model} does not support {capability.value}")

    @property
    def address(self) -> str:
        return self.transport.address

    def describe(self) -> dict:
        """Return the static device description served by the API's ``/device`` endpoint."""
        return {
            "model": self.model,
            "display_name": self.display_name,
            "capabilities": sorted(c.value for c in self.capabilities),
            "scenes": {str(k): v for k, v in self.scenes.items()},
            "brightness_range": list(self.brightness_range),
            "address": self.address,
        }

    def info(self) -> dict:
        return self.transport.info()

    # ------------------------------------------------------------------------- reads

    @abstractmethod
    def state(self) -> LightState:
        """Read the device's present state."""

    # ------------------------------------------------------------------------ writes

    @abstractmethod
    def set_power(self, on: bool) -> Any:
        """Switch the light on or off."""

    def turn_on(self) -> Any:
        return self.set_power(True)

    def turn_off(self) -> Any:
        return self.set_power(False)

    def set_brightness(self, level: int) -> Any:
        raise OperationNotSupported("brightness")

    def set_ambient(self, on: bool) -> Any:
        raise OperationNotSupported("ambient")

    def set_ambient_brightness(self, level: int) -> Any:
        raise OperationNotSupported("ambient_brightness")

    def set_eyecare(self, on: bool) -> Any:
        raise OperationNotSupported("eyecare")

    def set_scene(self, number: int) -> Any:
        raise OperationNotSupported("scenes")

    def set_night_light(self, on: bool) -> Any:
        raise OperationNotSupported("night_light")

    def set_reminder(self, on: bool) -> Any:
        raise OperationNotSupported("reminder")

    def set_sleep_timer(self, minutes: int) -> Any:
        raise OperationNotSupported("sleep_timer")

    # ------------------------------------------------------------------- convenience

    def clamp_brightness(self, level: int) -> int:
        low, high = self.brightness_range
        return max(low, min(high, int(level)))


# --------------------------------------------------------------------------- registry

_REGISTRY: dict[str, type[LightDriver]] = {}


def register(driver: type[LightDriver]) -> type[LightDriver]:
    """Class decorator recording a driver against its model identifier."""
    if not driver.model:
        raise ValueError(f"{driver.__name__} must declare a model identifier")
    _REGISTRY[driver.model] = driver
    return driver


def get_driver(model: str) -> type[LightDriver] | None:
    """Return the driver for ``model``, or None when the model is unknown."""
    return _REGISTRY.get(model)


def supported_models() -> dict[str, str]:
    """Model identifier to display name, for every registered driver."""
    return {m: d.display_name for m, d in sorted(_REGISTRY.items())}
