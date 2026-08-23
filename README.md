<div align="center">

# lamplight

**Local control for Xiaomi-ecosystem smart lights over the miIO protocol.**

[![CI](https://github.com/smartwhale8/lamplight/actions/workflows/ci.yml/badge.svg)](https://github.com/smartwhale8/lamplight/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

lamplight controls a smart light directly over your local network. It provides a web
interface, a versioned JSON API, and a command line tool. It contacts no external service:
every command is a UDP datagram sent from your machine to the device.

## Contents

- [What it does](#what-it-does)
- [Supported devices](#supported-devices)
- [How it works](#how-it-works) — the concepts, from networking up
- [Install](#install)
- [Adopting a device](#adopting-a-device)
- [Running the service](#running-the-service)
- [Command line](#command-line)
- [Authentication](#authentication)
- [Timed behaviour and its one limitation](#timed-behaviour-and-its-one-limitation)
- [Running it permanently](#running-it-permanently)
- [Documentation](#documentation)

## What it does

|  | |
|---|---|
| **Web interface** | Any browser, including a phone on the same network. Dark and light themes. |
| **JSON API** | Versioned at `/api/v1`, with an OpenAPI schema for generating clients. |
| **Command line** | Every function scriptable, suitable for cron or other automation. |
| **Sunrise wake-up** | Gradual brightness ramp over any duration. |
| **Fade to sleep** | Gradual dim to off. |
| **Sleep timer** | The device's own countdown, which continues if lamplight stops. |
| **Schedules** | Recurring actions per weekday, with the next firings listed. |
| **Device control** | Power, brightness, eyecare mode, ambient light, four scenes, night light, fatigue reminder. |

## Supported devices

| Model | Product | Verified on |
|---|---|---|
| `philips.light.sread1` | Philips Eyecare Smart Lamp 2 | Firmware 1.2.8, MCU 0026, Wi-Fi 1.4.0 |

Hardware details for that model:

| Property | Value |
|---|---|
| Controller | ESP8266 |
| Radio | 2.4 GHz only; the chip has no 5 GHz support |
| Transport | UDP port 54321 |
| Open TCP ports | None. Ports 22, 23, 80, 443, 1883, 6668, 8080 and 8443 are all closed. |
| Encryption | AES-128-CBC, key derived from a 16-byte device token |
| Lights | Main LED panel and a separate ambient LED in the base |
| Brightness range | 1 to 100, both lights |
| Scenes | 4 fixed: Study, Office, Reading, Bedtime |
| Colour | None. Fixed white, no colour temperature control. |
| Native transitions | None. Every command takes effect immediately. |
| State notification | None. State must be polled. |

Adding another miIO light is a new file in `lamplight/drivers/`. See
[docs/DEVICES.md](docs/DEVICES.md).

---

## How it works

This section explains the mechanism from the network layer up. If you only want to use the
software, skip to [Install](#install).

### What miIO is

**miIO** is the local control protocol spoken by devices in Xiaomi's smart home ecosystem.
The name is a contraction of *Mi* and *IO*. It is a proprietary protocol that Xiaomi has
never published; everything known about it publicly comes from reverse engineering, and
[python-miio](https://github.com/rytilahti/python-miio) is the reference implementation.

Two things about it are worth understanding before anything else.

**The brand on the box does not determine the protocol.** Xiaomi operates an ecosystem
programme in which partner manufacturers build hardware that registers with the Mi Home
application. A device from that programme speaks miIO regardless of whose logo it carries,
which is why a Philips-branded lamp is addressed by the same protocol as a Xiaomi air
purifier. Every such device has a model identifier in `vendor.category.model` form:

```
philips.light.sread1
   |      |      |
   |      |      +-- model, this specific product
   |      +--------- category, a light
   +---------------- vendor within the ecosystem programme
```

That identifier, not the brand name, is what selects a driver in this project.

**There are two generations of the protocol**, and they differ in how properties are
addressed:

| | Legacy miIO | MIoT-Spec-V2 |
|---|---|---|
| Reading | `get_prop` with string property names | `get_properties` with numeric `siid` and `piid` |
| Writing | Device-specific methods such as `set_bright` | `set_properties`, and `action` for commands |
| Discoverability | None. Property names must be learned per device. | Self-describing, published as a URN specification |
| Used by | Older devices, including this lamp | Newer devices |

Xiaomi intends MIoT-Spec-V2 to replace the legacy profile. **Both ride the same encrypted
UDP transport described below**, so the transport layer in this project serves either, and
only the driver differs. This lamp is a legacy device and uses `get_prop`.

Separately, these devices also talk to Xiaomi's cloud over HTTPS when bound to an account.
lamplight never uses that path, and never binds an account.

### Wi-Fi access points, and the two modes a device can be in

An **access point** is the radio that other devices associate with to form a Wi-Fi
network. Your router runs one; its network name is the SSID you select from a list.

A smart device can be in either of two modes:

**Infrastructure mode** is the normal state. The device joins your router's access point
as a client. Your router's DHCP server assigns it an address on your subnet, such as
`192.168.1.42`, and from then on any machine on that network can address it directly.

**SoftAP mode**, or "software access point", is the setup state. A device with no stored
Wi-Fi credentials cannot join a network, so it runs an access point *of its own* and waits
for you to connect to it. This is how it can be configured before it has any network
access. Its SSID encodes what it is:

```
philips-light-sread1_miapXXXX
     |          |        |
     |          |        +-- per-unit discriminator
     |          +----------- model: philips.light.sread1
     +---------------------- vendor
```

`_miap` marks a Xiaomi miIO setup access point. An SSID of that shape is a device waiting
to be adopted.

Two practical consequences of SoftAP mode:

1. **Your machine loses internet while joined to it.** The device is not a router; it
   provides no route to anywhere else.
2. **This device's SoftAP serves DHCP on `192.168.4.0/24`, hands the client `192.168.4.2`,
   answers on `192.168.4.1`, and advertises no default gateway.** Code that derives the
   device's address from the routing table finds nothing and concludes the device is dead.
   Probe `192.168.4.1` directly.

SoftAP mode is advertised for a limited window after a reset and then stops, so the device
does not broadcast an open network indefinitely.

### Addressing: why the device id matters more than the IP

Addresses come from DHCP and change. Every miIO device also has a **device id**, a 32-bit
integer fixed for the life of the hardware.

lamplight stores both. When a command fails repeatedly it re-runs discovery, matches on the
device id, and updates the address. This is why `lamplight adopt` records the device id and
why a lamp that moves from `.42` to `.99` keeps working without intervention.

### The protocol: miIO over UDP

Commands travel as **UDP datagrams to port 54321**. UDP is connectionless: each datagram is
sent independently, with no handshake, no ordering guarantee, and no delivery
acknowledgement. That has one consequence worth internalising:

> A lost datagram is indistinguishable from a dead device.

So every command is retried with increasing backoff before being reported as a failure, and
a `WARNING` in the log about rediscovery usually means one datagram was dropped, not that
anything is broken.

Every datagram, in both directions, opens with a 32-byte header:

```
 offset  size  field
 ------  ----  -------------------------------------------------------------
      0     2  magic, always 0x2131
      2     2  total packet length, header included, big-endian
      4     4  unknown; zero in practice
      8     4  device id, big-endian
     12     4  uptime stamp, seconds since the device booted
     16    16  MD5 checksum, or the token during a handshake
     32     n  encrypted payload; absent on a handshake
```

### Authentication: the token

Access is controlled by a single **token**: 16 bytes, written as 32 hexadecimal characters.
There is no username, no password, and no per-command permission. Possession of the token
is complete control of the device.

The token is not transmitted with each command. It is the seed for the encryption:

```
key = md5(token)                              # 16 bytes
iv  = md5(key + token)                        # 16 bytes
payload = AES-128-CBC(key, iv, json_bytes)    # PKCS#7 padding
```

The checksum at offset 16 is computed over the packet with the token substituted into that
field:

```
checksum = md5(header[0:16] + token + encrypted_payload)
```

A device that cannot decrypt a payload simply does not answer, so a wrong token presents
as an unreachable device rather than as an authentication error.

### The handshake, and how a token is obtained

Before any encrypted exchange, a client sends a **hello**: a 32-byte packet with no
payload and every byte of the checksum field set to `0xff`.

```
21 31 00 20 ff ff ff ff ff ff ff ff ff ff ff ff
ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
```

No encryption is involved, so **no credential is needed to send it**. The reply carries the
device id and uptime stamp. Bytes 16 to 32 hold one of:

| Value | Meaning |
|---|---|
| 16 bytes of data | The firmware is disclosing its token in plaintext |
| `ff` × 16 | Withheld |
| `00` × 16 | Withheld |

This is how a token is obtained without vendor software. Two facts govern whether it works:

- Firmware **discloses** its token when the device has never been bound to a vendor cloud
  account. On the model above, disclosure happens both in SoftAP mode and after
  provisioning, and `miIO.info` also returns the token in its response.
- **Binding** a device to a vendor account regenerates the token. Provisioning and binding
  are separate operations, which is why lamplight provisions with `uid=0` and never binds.

The handshake also serves as discovery. Sending a hello to every address on a `/24` and
collecting the replies enumerates the miIO devices on a network, with no credentials.

The uptime stamp matters for a long-lived client: a request whose stamp is far from the
device's own is ignored, so the handshake is repeated periodically to stay synchronised.

### Query and response

The payload is JSON-RPC. A read requests several properties in one call and receives their
values in the order asked:

```jsonc
// query
{"id": 1, "method": "get_prop",
 "params": ["power", "bright", "eyecare", "dvalue"]}

// response
{"result": ["on", 70, "off", 0], "id": 1}
```

Reading everything in one datagram rather than one per property is not an optimisation
detail. The device is a single-threaded microcontroller on a connectionless transport, and
nine separate reads will drop datagrams.

A write names a method and its arguments:

```jsonc
// query
{"id": 2, "method": "set_bright", "params": [45]}

// response
{"result": ["ok"], "id": 2}
```

Rules the transport enforces:

- **`id` must increase.** A reused id is ignored.
- **Errors arrive as** `{"error": {"code": -5001, "message": "..."}}`.
- **Not every reply is a list.** `miIO.config_router` answers with a bare integer on this
  firmware, which is why `python-miio`'s `Device.configure_wifi` raises
  `TypeError: 'int' object is not subscriptable` *after the device has already acted*.

#### The command set for `philips.light.sread1`

Readable properties, all available from one `get_prop`:

| Property | Type | Meaning |
|---|---|---|
| `power` | `"on"` / `"off"` | Main light |
| `bright` | 1–100 | Main brightness |
| `notifystatus` | `"on"` / `"off"` | Eye-fatigue reminder |
| `ambstatus` | `"on"` / `"off"` | Ambient light |
| `ambvalue` | 1–100 | Ambient brightness |
| `eyecare` | `"on"` / `"off"` | Eyecare mode |
| `scene_num` | 1–4 | Fixed scene |
| `bls` | `"on"` / `"off"` | Smart night light |
| `dvalue` | 0–n | Sleep timer, minutes remaining, 0 when unset |

Writable methods:

| Function | Method | Argument |
|---|---|---|
| Power | `set_power` | `["on"]` / `["off"]` |
| Main brightness | `set_bright` | `[1..100]` |
| Eyecare mode | `set_eyecare` | `["on"]` / `["off"]` |
| Ambient light | `enable_amb` | `["on"]` / `["off"]` |
| Ambient brightness | `set_amb_bright` | `[1..100]` |
| Fixed scene | `set_user_scene` | `[1..4]` |
| Sleep timer | `delay_off` | `[minutes]`, 0 cancels |
| Smart night light | `enable_bl` | `["on"]` / `["off"]` |
| Fatigue reminder | `set_notifyuser` | `["on"]` / `["off"]` |

Device-level methods:

| Method | Argument | Purpose |
|---|---|---|
| `miIO.info` | `[]` | Model, firmware, MAC, network state, and on this firmware the token |
| `miIO.config_router` | `{"ssid","passwd","uid"}` | Provide Wi-Fi credentials |

#### Two firmware defects

Measured, undocumented, and compensated for in the driver:

| Command | Undocumented side effect |
|---|---|
| `set_eyecare` | Resets `bright`. Observed 25 becoming 53. |
| `delay_off` | Resets `bright`. Observed 53 becoming 70. |

A user setting a sleep timer has not asked for a brightness change, so the driver reads
brightness first and restores it if the firmware moved it.

### Capabilities: how clients avoid hard-coding a feature set

Devices differ. Rather than every client knowing which features which model has, each
driver declares a capability set, and the API publishes it:

```console
$ curl -s http://localhost:8765/api/v1/device | jq '.capabilities'
[
  "ambient", "ambient_brightness", "brightness", "eyecare",
  "night_light", "power", "reminder", "scenes", "sleep_timer"
]
```

Three things follow from that list:

1. **Clients build their interface from it.** The web interface tags each control with a
   `data-cap` attribute and hides any whose capability is absent.
2. **Unsupported operations fail cleanly.** Calling `/api/v1/sleep_timer` on a device
   without that capability returns HTTP 400 with an explanatory message, not a protocol
   error.
3. **Unsupported state fields are omitted entirely.** In `GET /api/v1/state`, only `on` is
   guaranteed. An absent key means the device has no such feature, which is how a client
   distinguishes "off" from "not present".

Capability strings are public API. New ones may be added, and clients are required to
ignore values they do not recognise, so an older client keeps working against a newer
device.

### Putting it together

```mermaid
sequenceDiagram
    participant C as Client<br/>(browser, phone, curl)
    participant S as lamplight<br/>HTTP service
    participant D as Driver<br/>+ transport
    participant L as Lamp<br/>UDP 54321

    C->>S: GET /api/v1/device
    S->>C: capabilities, scenes, brightness range
    Note over C: build the interface from capabilities

    C->>S: GET /api/v1/state
    S->>D: state()
    D->>L: get_prop [power, bright, ...]  (encrypted)
    L->>D: [on, 70, ...]
    D->>S: LightState
    S->>C: state + schedules + ramp + next runs

    C->>S: POST /api/v1/brightness {"level": 45}
    S->>D: set_brightness(45)
    D->>L: set_bright [45]  (encrypted)
    L->>D: ["ok"]
    S->>C: {"ok": true, "result": ["ok"]}
```

Full protocol reference in [docs/PROTOCOL.md](docs/PROTOCOL.md); the HTTP contract in
[docs/API.md](docs/API.md).

---

## Install

Python 3.11 or newer.

```bash
git clone https://github.com/smartwhale8/lamplight.git
cd lamplight
python -m venv .venv && source .venv/bin/activate
pip install -e ".[server]"
```

## Adopting a device

**Adoption** means recording a device's address and token so lamplight can command it.

If the device is already on your network and discloses its token, this is one step:

```bash
lamplight discover --subnet 192.168.1.
lamplight adopt --auto --name "Desk lamp"
```

`discover` reports which devices disclose a token:

```
  192.168.1.42  device_id=12345678  (token disclosed)
```

If it reports `token withheld`, or the device is unprovisioned and broadcasting its own
SoftAP, follow [docs/ADOPTION.md](docs/ADOPTION.md), which covers recovering the token over
the setup access point and handing the device your Wi-Fi credentials. Then:

```bash
lamplight adopt --ip 192.168.1.42 --token 0123456789abcdef0123456789abcdef
```

Settings are written to `~/.config/lamplight/config.json` at mode `0600`, because that file
holds the token.

## Running the service

```bash
lamplight serve
```

Open <http://localhost:8765>, or `http://<your-machine-ip>:8765` from a phone on the same
network. `/docs` serves interactive API documentation and `/openapi.json` the schema.

## Command line

```bash
lamplight status                          # current device state
lamplight on --brightness 60
lamplight off
lamplight brightness 35
lamplight scene 3                         # 1 Study, 2 Office, 3 Reading, 4 Bedtime
lamplight eyecare on
lamplight ambient on --level 50
lamplight timer 45                        # device countdown; survives lamplight exiting
lamplight sunrise --minutes 20 --target 100
lamplight fade --minutes 30
lamplight schedules
lamplight capabilities                    # what this device supports
lamplight info                            # raw miIO.info
lamplight models                          # drivers available
```

## Authentication

lamplight requires no authentication by default. Anything that can reach the port can
control the device.

To require a key:

```bash
export LAMPLIGHT_API_KEY="$(openssl rand -hex 24)"
lamplight serve
```

Clients then send `Authorization: Bearer <key>`, or `X-API-Key: <key>`. The web interface
prompts once and stores it. `GET /api/v1/health` stays unauthenticated so a client can
identify a service before pairing, and its `auth_required` field reports whether a key is
needed.

The key is a shared secret over plain HTTP. It identifies a client on a trusted network. Do
not forward the port to the internet; reach it through a VPN into your network instead.

A separate consideration applies to the device itself: this firmware discloses its token to
any unauthenticated request on the local network, so the device's real perimeter is your
Wi-Fi password. See [SECURITY.md](SECURITY.md).

## Timed behaviour and its one limitation

The device firmware implements exactly one timed feature: `delay_off`, a hard cut-off after
N minutes. **Gradual wake-up and gradual fade-out do not exist in the hardware.** lamplight
produces them by stepping `set_bright` every five seconds, which has a consequence:

- A `sunrise` or `fade_off` ramp progresses **only while lamplight is running**. If the
  host sleeps, the ramp stops where it was.
- A `timer` schedule uses the device's own countdown and survives lamplight exiting, a
  reboot, or the host sleeping.

The API and the interface both mark which is which, through the `service_driven` field. For
a wake-up you depend on, run lamplight on a machine that stays awake.

| Schedule kind | Behaviour | Survives lamplight stopping |
|---|---|---|
| `sunrise` | On at 1%, ramping to the target over the duration | No |
| `fade_off` | Ramp down to 1% over the duration, then off | No |
| `on` | On, applying brightness, scene and ambient | Yes, it is instant |
| `off` | Off | Yes, it is instant |
| `timer` | Set the device countdown | **Yes**, the device tracks it |

## Running it permanently

So that schedules fire without the service being started by hand.

**macOS**, using `launchd`:

```bash
./packaging/launchd/install.sh
```

**Linux**, using `systemd`:

```bash
./packaging/systemd/install.sh
```

Each script prints what it will do before doing it, and each has a matching
`uninstall.sh`.

## Documentation

| Document | Contents |
|---|---|
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | miIO on the wire, packet layout, crypto, full command set |
| [docs/API.md](docs/API.md) | The HTTP contract, with captured responses |
| [docs/ADOPTION.md](docs/ADOPTION.md) | Token recovery and provisioning, step by step |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layers, threading, state, and the reasoning |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Setup, testing, debugging, releasing |
| [docs/DEVICES.md](docs/DEVICES.md) | Adding support for another device |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Symptoms, causes, fixes |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned work, including the Android client |

## Contributing

Issues and pull requests are welcome, particularly drivers for other miIO lights. See
[CONTRIBUTING.md](CONTRIBUTING.md). The test suite runs without hardware, so a contribution
can be verified before it touches a device.

## Acknowledgements

Built on [python-miio](https://github.com/rytilahti/python-miio), which implements the miIO
transport and cryptography.

## License

[MIT](LICENSE).

lamplight is not affiliated with, endorsed by, or connected to Xiaomi, Signify, or Philips.
Product names identify the hardware the software controls.
