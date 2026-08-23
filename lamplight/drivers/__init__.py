"""Device drivers.

Importing this package registers every bundled driver, so
:func:`lamplight.drivers.base.get_driver` can resolve a model identifier without the
caller knowing which module implements it. A new driver is added by creating a module
here and importing it below; see ``docs/DEVICES.md``.
"""

from .base import (
    Capability,
    DeviceError,
    DeviceUnreachable,
    LightDriver,
    LightState,
    OperationNotSupported,
    Transport,
    get_driver,
    register,
    supported_models,
)
from .miio_transport import MiioTransport, discover, handshake
from .philips_eyecare import PhilipsEyecareLamp

__all__ = [
    "Capability",
    "DeviceError",
    "DeviceUnreachable",
    "LightDriver",
    "LightState",
    "MiioTransport",
    "OperationNotSupported",
    "PhilipsEyecareLamp",
    "Transport",
    "discover",
    "get_driver",
    "handshake",
    "register",
    "supported_models",
]
