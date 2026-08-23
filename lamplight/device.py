"""Device construction: turn stored configuration into a working driver.

This module is the seam between configuration and hardware. Everything above it (the
scheduler, the HTTP service, the CLI) depends only on
:class:`~lamplight.drivers.base.LightDriver`, so adding a device type changes nothing but
the registry lookup here.

Names from the pre-driver layout are re-exported for compatibility, since the 0.x CLI and
external scripts referred to ``Lamp`` and ``LampUnreachable`` directly.
"""

from __future__ import annotations

import logging

from .drivers.base import (
    Capability,
    DeviceError,
    DeviceUnreachable,
    LightDriver,
    LightState,
    OperationNotSupported,
    get_driver,
    supported_models,
)
from .drivers.miio_transport import MiioTransport, discover, handshake
from .drivers.philips_eyecare import SCENES, PhilipsEyecareLamp

log = logging.getLogger(__name__)

#: Retained so existing callers keep working. New code should use ``DeviceUnreachable``.
LampUnreachable = DeviceUnreachable
Lamp = PhilipsEyecareLamp

__all__ = [
    "SCENES",
    "Capability",
    "DeviceError",
    "DeviceUnreachable",
    "Lamp",
    "LampUnreachable",
    "LightDriver",
    "LightState",
    "MiioTransport",
    "OperationNotSupported",
    "build_driver",
    "discover",
    "handshake",
    "supported_models",
]


class UnsupportedModel(DeviceError):
    """No driver is registered for the configured model."""


def build_driver(ip: str, token: str, model: str = "", device_id: int | None = None,
                 subnet: str = "192.168.1.", retries: int = 3) -> LightDriver:
    """Construct the driver for a device.

    When ``model`` is empty the device is asked what it is via ``miIO.info``, which costs
    one round trip and removes the need to record the model by hand. An unrecognised
    model raises :class:`UnsupportedModel` listing what is available, rather than
    failing later with a confusing protocol error.
    """
    transport = MiioTransport(ip, token, device_id=device_id, subnet=subnet, retries=retries)

    if not model:
        info = transport.info()
        model = info.get("model", "")
        log.info("device at %s identifies as %s", ip, model or "an unknown model")

    driver_cls = get_driver(model)
    if driver_cls is None:
        raise UnsupportedModel(
            f"No driver for model {model!r}. Supported: {supported_models()}. "
            f"See docs/DEVICES.md to add one."
        )
    return driver_cls(transport)
