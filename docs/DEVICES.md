# Adding a device

limelight supports one device today. The architecture assumes more, and adding one is a
new file plus one import. This walks through it.

## Before you start

You need the device's **model identifier**, the string it reports in `miIO.info`:

```bash
limelight adopt --ip <address> --token <token>    # fails, but usefully
```

The failure names what it found:

```
No driver for model 'philips.light.bulb'. Supported: {'philips.light.sread1': ...}.
See docs/DEVICES.md to add one.
```

Or ask directly:

```python
from limelight.drivers.miio_transport import MiioTransport
print(MiioTransport("192.168.1.42", "<token>").info())
```

## Case 1: another miIO device

The common case. The transport is done; you are describing a command set.

First establish which generation the device belongs to, because it decides how properties
are addressed. See [PROTOCOL.md](PROTOCOL.md#what-miio-is) for the background.

| | Legacy miIO | MIoT-Spec-V2 |
|---|---|---|
| Read | `send("get_prop", ["power", "bright"])` | `send("get_properties", [{"did": "p", "siid": 2, "piid": 1}])` |
| Write | `send("set_bright", [45])` | `send("set_properties", [{"did": "p", "siid": 2, "piid": 3, "value": 45}])` |
| Property names | Strings, learned per device | Numeric service and property ids from a published specification |

Probe for it, since a device answers only the form it implements:

```python
from limelight.drivers.miio_transport import MiioTransport
t = MiioTransport("192.168.1.42", "<token>")

try:
    print("legacy:", t.send("get_prop", ["power"]))
except Exception as exc:
    print("legacy unsupported:", exc)

try:
    print("miot:", t.send("get_properties", [{"did": "p", "siid": 2, "piid": 1}]))
except Exception as exc:
    print("miot unsupported:", exc)
```

Either way the driver is the only thing that changes: `MiioTransport` carries both, and a
MIoT driver simply issues different payloads from its `state()` and setter methods. For a
MIoT device, record the `siid` and `piid` pairs as module constants with the same care the
example below gives to property names.

The rest of this section uses the legacy form, which is what `philips.light.sread1` speaks.

### 1. Discover the property names

There is no registry, so the practical route is: check whether
[python-miio](https://github.com/rytilahti/python-miio) already has an integration for the
model and read its property list, then confirm against your device.

```python
from limelight.drivers.miio_transport import MiioTransport
t = MiioTransport("192.168.1.42", "<token>")

# Try a candidate list. Unsupported names typically return None rather than erroring.
props = ["power", "bright", "cct", "snm", "dv"]
print(dict(zip(props, t.send("get_prop", props), strict=False)))
```

Write down what you observe, including which names return `None`. That record is worth as
much as the code.

### 2. Write the driver

Create `limelight/drivers/<vendor>_<product>.py`:

```python
"""Driver for the Example Smart Bulb (``example.light.bulb``).

Verified against firmware 2.1.0. Transport is miIO over UDP 54321.

Command surface
---------------
====================  ====================  ==============================
Function              miIO method           Argument
====================  ====================  ==============================
Power                 ``set_power``         ``"on"`` / ``"off"``
Brightness            ``set_bright``        1..100
Colour temperature    ``set_cct``           1..100
====================  ====================  ==============================
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Capability, LightDriver, LightState, register

PROPS = ["power", "bright", "cct"]


@register
class ExampleBulb(LightDriver):
    """Example Smart Bulb."""

    model: ClassVar[str] = "example.light.bulb"
    display_name: ClassVar[str] = "Example Smart Bulb"
    brightness_range: ClassVar[tuple[int, int]] = (1, 100)
    capabilities: ClassVar[frozenset[Capability]] = frozenset({
        Capability.POWER,
        Capability.BRIGHTNESS,
        Capability.COLOR_TEMPERATURE,
    })

    def state(self) -> LightState:
        v = dict(zip(PROPS, self.transport.send("get_prop", PROPS), strict=False))
        return LightState(
            on=v.get("power") == "on",
            brightness=int(v.get("bright") or 0),
            color_temperature=int(v.get("cct") or 0),
            raw=dict(v),
        )

    def set_power(self, on: bool) -> Any:
        return self.transport.send("set_power", ["on" if on else "off"])

    def set_brightness(self, level: int) -> Any:
        return self.transport.send("set_bright", [self.clamp_brightness(level)])
```

Rules that matter:

- **Declare only what the device does.** An overclaimed capability produces a client
  control that fails. Anything not declared raises `OperationNotSupported`, which the API
  turns into a clean `400`.
- **Leave unsupported `LightState` fields as `None`.** The API omits them, which is how a
  client distinguishes "off" from "absent".
- **Use `strict=False` when zipping properties.** Some firmware returns fewer values than
  requested.
- **Clamp with `self.clamp_brightness()`** so bounds come from `brightness_range`.

### 3. Register it

Add one import to `limelight/drivers/__init__.py`. Importing the module runs the
`@register` decorator, which is what makes the model resolvable.

```python
from .example_bulb import ExampleBulb  # noqa: F401
```

Add it to `__all__` too.

### 4. Test it

Nothing here needs the device:

```python
from limelight.drivers.base import Capability, get_driver
from limelight.drivers.example_bulb import ExampleBulb
from .fakes import FakeTransport


def test_registered():
    assert get_driver("example.light.bulb") is ExampleBulb


def test_state_decodes():
    t = FakeTransport({"power": "on", "bright": 40, "cct": 60})
    s = ExampleBulb(t).state()
    assert (s.on, s.brightness, s.color_temperature) == (True, 40, 60)


def test_does_not_claim_what_it_lacks():
    assert not ExampleBulb(FakeTransport()).supports(Capability.EYECARE)
```

`FakeTransport` handles the commands this lamp uses. For a different command set, either
extend it or write a small local double: it is about eighty lines.

### 5. Document it

- Add a row to the supported devices table in [../README.md](../README.md).
- Add its command surface to [PROTOCOL.md](PROTOCOL.md), including anything you found that
  was wrong or undocumented.
- Note the firmware version you verified against.

## Case 2: a device that is not miIO

A Zigbee bulb, a Tuya device, an ESPHome node, or anything with an HTTP API. This needs a
transport as well as a driver, and it is still a contained job because nothing above
`drivers/` knows how bytes reach a device.

Implement the `Transport` protocol:

```python
class MyTransport:
    """Anything satisfying this protocol can back a driver."""

    @property
    def address(self) -> str:
        return self._host

    def send(self, command: str, params=None):
        """Issue a command; raise DeviceUnreachable on failure."""

    def info(self) -> dict:
        """Return a self-description including at least ``model``."""
```

Then a driver that speaks to it. Raise `DeviceUnreachable` from `base` for transport
failures, so the API maps them to `503` rather than a 500.

`Transport` is a `typing.Protocol`, so there is nothing to subclass. Structural conformance
is enough.

Two things to check before choosing this route:

1. **Command naming.** `LightDriver` methods take domain arguments such as
   `set_brightness(50)`. Whether that becomes a JSON-RPC call, an MQTT publish or a REST
   `PUT` is the transport's business.
2. **Device construction.** `device.build_driver()` currently constructs a `MiioTransport`
   unconditionally. Adding a second transport means giving it a way to choose, most simply
   a `transport` field in `DeviceConfig`. That is a small change, and worth making properly
   when the second transport arrives rather than guessing at it now.

## Case 3: a capability nothing has yet

To add, say, colour:

1. Add `COLOR = "color"` to `Capability` in `drivers/base.py`. **The string is public
   API**; it appears in `GET /api/v1/device`.
2. Add a default method on `LightDriver` raising `OperationNotSupported`.
3. Add the field to `LightState`, defaulting to `None`.
4. Implement it in the drivers that have it, and add the capability to their sets.
5. Add an endpoint in `server.py`, guarded with `guard(..., Capability.COLOR)`.
6. Add a control in `web.py` with `data-cap="color"`. Gating is automatic from there.
7. Document it in [API.md](API.md) and test it.

Adding a capability is backwards-compatible. Clients are required to ignore values they do
not recognise, so an older client simply will not show the new control.

## Supporting several devices at once

Not yet supported: the service handles exactly one device. The driver layer is already
device-agnostic, so the remaining work is configuration and routing, namely `DeviceConfig`
becoming a list and the API growing `/api/v1/devices/{id}/...`.

This is deliberately not half-built. Shipping a guess at that shape would mean changing a
versioned contract twice, which is exactly what versioning exists to avoid. See
[ROADMAP.md](ROADMAP.md).

## Contributing a driver

New drivers are welcome, particularly for other Xiaomi-ecosystem lights.

A pull request should carry the driver, a test using a fake transport, a documented command
surface, and the firmware version you verified against. Please note anything the device
does that the documentation does not predict: those findings are the most valuable part.

Do not include a real token, MAC address or network name anywhere. Use `0` × 32,
`AA:BB:CC:DD:EE:FF`, and `192.168.1.x`.
