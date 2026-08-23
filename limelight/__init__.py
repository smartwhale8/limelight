"""limelight: local control of Xiaomi-ecosystem lights over the miIO protocol.

Devices are addressed directly on the local network: JSON-RPC payloads carried over UDP
port 54321, encrypted with AES-128-CBC under a 16-byte per-device token. No cloud service
is involved.

Layers, lowest first
--------------------
``drivers.base``            The device contract: capabilities, transport protocol, and
                            the abstract :class:`~limelight.drivers.base.LightDriver`.
``drivers.miio_transport``  Encrypted UDP to miIO devices, with retry and rediscovery.
``drivers.philips_eyecare`` The concrete driver, including firmware quirk compensation.
``device``                  Builds a driver from stored configuration.
``config``                  Persistence of device details and schedules.
``scheduler``               Sunrise and fade ramps, and the daily schedule loop.
``server``                  Versioned HTTP API and the web interface.
``cli``                     Command line interface.

Everything above ``drivers`` depends only on the abstract driver, which is what allows a
second device type to be added without touching the service. See ``docs/ARCHITECTURE.md``
for the reasoning and ``docs/DEVICES.md`` for the procedure.
"""

__version__ = "2.0.0"

from .config import Config, DeviceConfig, Schedule, ServerConfig
from .device import (
    Lamp,
    LampUnreachable,
    UnsupportedModel,
    build_driver,
)
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
from .scheduler import RampStatus, Scheduler

__all__ = [
    "Capability", "Config", "DeviceConfig", "DeviceError", "DeviceUnreachable", "Lamp",
    "LampUnreachable", "LightDriver", "LightState", "MiioTransport",
    "OperationNotSupported", "RampStatus", "Schedule", "Scheduler", "ServerConfig",
    "UnsupportedModel", "__version__", "build_driver", "discover", "get_driver",
    "handshake", "supported_models",
]
