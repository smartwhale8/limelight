# Roadmap

Planned work, in rough order. Nothing here is a commitment to a date.

Items marked **contract-affecting** change the HTTP API. They are grouped so that a client
generated today keeps working, per the compatibility promise in [API.md](API.md).

---

## 1.x: additive work, no breaking changes

### Android client

A first version exists in [`../android/`](../android/). It speaks miIO **directly to the
lamp** rather than going through this service, so it works with nothing else running.
Discovery, connection and every device operation are implemented; sunrise ramps and
schedules are not, because they need a host awake at the scheduled moment.

Its codec was verified by translating the Kotlin into Python and comparing bytes with
`python-miio`. That comparison caught a real defect, a missing null terminator on the JSON
payload, which would have failed against the firmware while looking correct.

The notes below remain relevant to a client that talks to this service instead, which is
the route to schedules and ramps on a phone.

What already exists for it:

| Need | Provided by |
|---|---|
| A stable contract | `/api/v1`, with the promise in [API.md](API.md) |
| Generated models | `GET /openapi.json`, consumable by openapi-generator |
| Feature detection | `GET /api/v1/device` → `capabilities` |
| Service identification | `GET /api/v1/health`, unauthenticated, reports `service` |
| Pairing | Optional bearer token, with `auth_required` advertised |
| One-call refresh | `GET /api/v1/state` returns everything a screen needs |
| Honest limitations | `service_driven` marks ramps that need the server running |

Client-side notes are collected in
[API.md § Notes for the Android client](API.md#notes-for-the-android-client), including the
cleartext-HTTP configuration Android requires and the weekday numbering difference between
Python and `java.time`.

### Scheduled wake-up on the phone

Not planned for now, and recorded here so the cost is known when it is wanted. The app has
no ramp, schedule or alarm code at all today; the lamp's own sleep timer is included
because the device counts it down itself.

The difficulty is not the ramp, which is a loop sending `set_bright`. It is that Android
is hostile to a twenty-minute network operation starting at a fixed time on a sleeping
phone. Everything below is required, not optional:

| Requirement | Why | Cost |
|---|---|---|
| `AlarmManager.setExactAndAllowWhileIdle` | Only exact alarms survive Doze. `setRepeating` is inexact and may drift by many minutes. | Small |
| `SCHEDULE_EXACT_ALARM` permission | Android 12 and later require it, and 13 and later require the **user** to grant it in system settings. The app must detect refusal and explain. | Small, plus an onboarding screen |
| A foreground service | The ramp runs for twenty minutes. A background service is killed. A foreground service needs a persistent notification the user cannot dismiss. | Medium |
| `FOREGROUND_SERVICE` and `FOREGROUND_SERVICE_SPECIAL_USE` | Android 14 requires a declared service type, and "special use" needs a justification at Play review if it is ever published. | Small, plus review risk |
| Battery-optimisation exemption | Without it, some devices defer the alarm anyway. Requesting it shows a system dialog and Play restricts the justification. | Small, plus review risk |
| `WifiLock` held during the ramp | Phones commonly drop Wi-Fi when the screen is off. Without it, the datagrams go nowhere. | Small |
| Handling OEM battery managers | Xiaomi, Samsung, Huawei and others kill background work regardless of the platform APIs. There is no programmatic fix, only instructing the user per manufacturer. | Ongoing, and never fully solved |

Two consequences worth weighing before starting:

**It cannot be made fully reliable.** The last row has no engineering answer. An alarm that
works on one phone and silently does not on another is arguably worse than no alarm,
because the user stops setting a real one.

**The phone must be on the same Wi-Fi at the moment it fires.** Away for a night, or on
mobile data, and nothing happens. The Python service on a machine that never leaves the
house does not have that problem.

If it is built anyway, the honest design is: schedule with an exact alarm, run the ramp in
a foreground service holding a `WifiLock`, and state plainly in the interface that the
alarm depends on the phone being at home, awake and unrestricted. A `service_driven`-style
warning, as the HTTP API already carries.

**The alternative that does work today** is the Python service on an always-on host. It
runs unchanged on a Raspberry Pi, and `packaging/systemd/install.sh` installs it. That is
one evening of setup against an open-ended fight with battery management.

Server-side work that would help, none of it breaking:

- **mDNS advertisement**, so a client finds the service without the user typing an address.
  Publish `_limelight._tcp.local` carrying the port, device name and `auth_required`.
- **A pairing flow** better than typing a 48-character key. A short-lived code displayed by
  the server and exchanged for a token would be materially easier on a phone.
- **Long-poll or server-sent events** for state, to cut battery cost. The device offers no
  push, so the server would still poll; the saving is on the phone's radio.
- **A widget-shaped endpoint**, a minimal response for a home-screen widget that wants power
  and brightness only.

### More devices

Each is a driver plus a test, with no API change. Candidates, roughly by likely demand:

| Model | Product | Notes |
|---|---|---|
| `philips.light.sread2` | Eyecare lamp 3 | Expected to be close to `sread1` |
| `philips.light.bulb` | Zhirui bulb | Adds colour temperature |
| `philips.light.ceiling` | Zhirui ceiling light | Colour temperature, scenes |
| `philips.light.moonlight` | Bedside lamp | Adds full colour |
| `yeelink.light.*` | Yeelight range | Well documented, large installed base |

The first colour-capable driver exercises `Capability.COLOR` and
`Capability.COLOR_TEMPERATURE`, which are declared but unused. Expect the `LightState`
colour representation to need a decision at that point: HSV, RGB, or both.

### Smaller additions

- **A `sunset` schedule kind**, ramping down to a floor without powering off.
- **Astronomical times**, so a schedule can fire relative to local sunrise or sunset. Needs
  a location and a solar calculation, and is a common request for lighting.
- **Ramp curves.** Linear is what exists. A perceptual curve would look more even to the
  eye, since perceived brightness is not linear in the reported value.
- **A `--dry-run` flag** on the CLI, printing the datagrams that would be sent.
- **A version consistency test**, asserting that `__version__` matches `pyproject.toml`.
- **Prometheus metrics**, for anyone already running monitoring.

---

## 2.0: contract-affecting

Grouped deliberately, so a client faces one migration rather than several.

### Multiple devices

The service handles exactly one device. The driver layer is already device-agnostic; the
work is in configuration and routing.

Intended shape:

- `DeviceConfig` becomes a list, each entry with a stable local id.
- Routes become `/api/v1/devices/{id}/...`, with the present unversioned-device routes kept
  as an alias for the default device through the 1.x line.
- Schedules gain a device reference, defaulting to the only device when there is one.
- Groups, so one command can address several devices, which is where scenes across a room
  become possible.

This is deliberately not half-built. A guess at the shape would mean changing a versioned
contract twice.

### Removing the unversioned `/api` alias

`/api/...` currently mirrors `/api/v1/...` for the 0.x web interface. It disappears in 2.0.

---

## Beyond lights

The driver contract is written in terms of a *light*: `LightDriver`, `LightState`,
`Capability` members such as `BRIGHTNESS` and `SCENES`. Extending to other device classes
means a shallower base than `LightDriver`.

A plausible decomposition, when a second device class actually exists:

```
DeviceDriver          identity, capabilities, state, transport
├── LightDriver       power, brightness, colour, scenes
├── SensorDriver      read-only measurements
├── SwitchDriver      power only, possibly multi-channel
└── ClimateDriver     setpoints, modes
```

`Transport` needs no change: it already carries opaque commands and knows nothing about
lights.

Two decisions that should not be made speculatively:

1. **State representation.** `LightState` is a flat dataclass, which suits one device class.
   Several classes may want a capability-keyed mapping instead, and that changes the API's
   `state` object.
2. **Whether this remains one project.** A general device framework and a lamp controller
   are different things. Splitting the driver contract into a library that limelight
   consumes is the alternative, and it is the better one if a second device class arrives
   from a different protocol family.

Neither is worth deciding before there is a real second device to design against.

---

## Explicitly not planned

| Not planned | Why |
|---|---|
| Cloud relay or remote access | Reach the network over a VPN. A relay means running an internet-facing service and holding credentials. |
| HTTPS with self-signed certificates | Certificate handling on a phone is worse than the problem it solves on a home network. A reverse proxy handles this if wanted. |
| Vendor account integration | Binding a device to a cloud account regenerates its token and removes the local-only property this depends on. |
| Firmware updates | OTA is initiated through vendor infrastructure. Attempting it independently risks bricking a device with no recovery path. |
| Colour on `philips.light.sread1` | The hardware is fixed white. No command exposes colour. |
| Sub-second scheduling | The device is a microcontroller on UDP. A one-minute granularity matches what lighting needs. |

---

## Contributing to any of this

Drivers are the most useful contribution and the most self-contained: one file, one test,
no API change. See [DEVICES.md](DEVICES.md) and [../CONTRIBUTING.md](../CONTRIBUTING.md).

For anything contract-affecting, open an issue before writing code. The compatibility
promise means an API mistake is expensive to undo.
