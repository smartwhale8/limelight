# The miIO protocol

Complete wire-protocol reference, verified against a Philips Eyecare Smart Lamp 2 on
firmware 1.2.8, MCU 0026, Wi-Fi 1.4.0.

[README.md](../README.md#how-it-works) introduces these concepts in order and is the place
to start. This document is the exhaustive version, with byte-level detail and worked
examples.

## Overview

| | |
|---|---|
| Transport | UDP, port 54321 |
| Open TCP ports | None. The device runs no HTTP server, no telnet, nothing. |
| Payload | JSON-RPC, encrypted |
| Cipher | AES-128-CBC with PKCS#7 padding |
| Credential | A 16-byte per-device token |
| Radio | 2.4 GHz only. 5 GHz is not supported by the hardware. |
| Controller | ESP8266 |

Control is entirely local. The device will talk to a vendor cloud if it is bound to an
account, but nothing in this protocol requires that, and lamplight never does it.

## Packet layout

Every datagram, in both directions, begins with a 32-byte header.

```
 offset  size  field
 ------  ----  ---------------------------------------------------------------
      0     2  magic, always 0x2131
      2     2  total packet length, header included, big-endian
      4     4  unknown; zero in practice
      8     4  device id, big-endian. Stable for the life of the device.
     12     4  uptime stamp, seconds since the device booted
     16    16  MD5 checksum, or the token during a handshake
     32     n  encrypted payload, absent on a handshake
```

The device id at offset 8 is the only stable identity a device has. Addresses come from
DHCP and move; the device id does not. lamplight uses it to find a device again after it
changes address.

## The handshake, and how a token is recovered

A "hello" is a 32-byte packet with no payload and every byte of the checksum field set to
`0xff`:

```
21 31 00 20 ff ff ff ff ff ff ff ff ff ff ff ff
ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff
```

No encryption is involved, so **no credential is needed to send it**. That is what makes
discovery possible, and it is also the mechanism by which a token can be read.

The reply carries the device id and uptime. Bytes 16 to 32 contain one of:

| Value | Meaning |
|---|---|
| A 16-byte token | The firmware is disclosing its token in plaintext |
| `ff` × 16 | Withheld |
| `00` × 16 | Withheld |

Firmware that discloses its token does so **to any host on the network, without
authentication**. On this model, disclosure happens both in setup mode and after
provisioning, and `miIO.info` returns the token in its response as well. This is both the
adoption mechanism and a weakness; see [../SECURITY.md](../SECURITY.md).

Whether a token is disclosed depends on the firmware and on whether the device has been
bound to a vendor account. Binding regenerates the token, which is why lamplight
provisions with `uid=0`, deliberately avoiding a binding.

```python
import socket

HELLO = bytes.fromhex("21310020" + "ff" * 28)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2)
s.sendto(HELLO, ("192.168.1.42", 54321))
reply, _ = s.recvfrom(1024)

device_id = int.from_bytes(reply[8:12], "big")
token = reply[16:32]
disclosed = token not in (b"\xff" * 16, b"\x00" * 16)
```

## Encryption

Derive the key and IV from the token:

```
key = md5(token)                # 16 bytes
iv  = md5(key + token)          # 16 bytes
```

Then AES-128-CBC with PKCS#7 padding over the JSON payload.

The checksum at offset 16 is computed over the whole packet with the token substituted
into the checksum field:

```
checksum = md5(header[0:16] + token + encrypted_payload)
```

Build the header with the token in place, hash it, then overwrite that field with the
result.

`python-miio` implements all of this. lamplight does not reimplement the crypto; it uses
that library for framing and adds retry, rediscovery and locking on top.

## Payload format

Request:

```json
{"id": 1, "method": "get_prop", "params": ["power", "bright"]}
```

Response:

```json
{"result": ["off", 70], "id": 1}
```

Notes drawn from measurement:

- `id` must increase. Reusing one gets the request ignored.
- The uptime stamp in a request must be close to the device's own. `python-miio` handles
  this by re-handshaking periodically, which is why a long-lived connection needs one.
- Errors come back as `{"error": {"code": -5001, "message": "..."}}`.
- **Not every reply is a list.** `miIO.config_router` answers with a bare integer on this
  firmware. `python-miio`'s `Device.configure_wifi` indexes the reply as `send(...)[0]`
  and therefore raises `TypeError: 'int' object is not subscriptable`, *after the device
  has already acted on the command*. Send the command directly to avoid the exception.

## Command set: `philips.light.sread1`

### Reading state

One `get_prop` call returns everything, in the order requested:

```json
{"id": 1, "method": "get_prop",
 "params": ["power","bright","notifystatus","ambstatus","ambvalue",
            "eyecare","scene_num","bls","dvalue"]}
```

| Property | Type | Meaning |
|---|---|---|
| `power` | `"on"` / `"off"` | Main light |
| `bright` | 1–100 | Main brightness |
| `notifystatus` | `"on"` / `"off"` | Eye-fatigue reminder |
| `ambstatus` | `"on"` / `"off"` | Ambient light in the base |
| `ambvalue` | 1–100 | Ambient brightness |
| `eyecare` | `"on"` / `"off"` | Eyecare mode |
| `scene_num` | 1–4 | Fixed scene |
| `bls` | `"on"` / `"off"` | Smart night light |
| `dvalue` | 0–n | Sleep timer, minutes remaining, 0 when unset |

Some firmware returns fewer values than requested. lamplight zips with `strict=False` and
reads with `.get()`, so a short reply yields `None` rather than an exception.

### Writing state

| Function | Method | Params | Reply |
|---|---|---|---|
| Power | `set_power` | `["on"]` / `["off"]` | `["ok"]` |
| Main brightness | `set_bright` | `[1..100]` | `["ok"]` |
| Eyecare mode | `set_eyecare` | `["on"]` / `["off"]` | `["ok"]` |
| Ambient light | `enable_amb` | `["on"]` / `["off"]` | `["ok"]` |
| Ambient brightness | `set_amb_bright` | `[1..100]` | `["ok"]` |
| Fixed scene | `set_user_scene` | `[1..4]` | `["ok"]` |
| Sleep timer | `delay_off` | `[minutes]`, 0 cancels | `["ok"]` |
| Smart night light | `enable_bl` | `["on"]` / `["off"]` | `["ok"]` |
| Fatigue reminder | `set_notifyuser` | `["on"]` / `["off"]` | `["ok"]` |

Scenes are: 1 Study, 2 Office, 3 Reading, 4 Bedtime.

### Device methods

| Method | Params | Purpose |
|---|---|---|
| `miIO.info` | `[]` | Model, firmware, MAC, network, and on this firmware the token |
| `miIO.config_router` | `{"ssid","passwd","uid"}` | Hand over Wi-Fi credentials |

A representative `miIO.info` reply, with identifiers replaced:

```json
{
  "life": 35,
  "token": "<32 hex characters>",
  "mac": "AA:BB:CC:DD:EE:FF",
  "fw_ver": "1.2.8",
  "hw_ver": "ESP8266",
  "model": "philips.light.sread1",
  "mcu_fw_ver": "0026",
  "wifi_fw_ver": "1.4.0(30e0bd0)",
  "ap": {"rssi": 31, "ssid": "<network name>", "bssid": "AA:BB:CC:11:22:33"},
  "netif": {"localIp": "192.168.1.42", "mask": "255.255.255.0", "gw": "192.168.1.1"},
  "mmfree": 12280
}
```

## Firmware defects

Both were found by measurement and are compensated for in
`drivers/philips_eyecare.py`.

### Brightness is reset by unrelated commands

| Command | Effect on `bright` |
|---|---|
| `set_eyecare` | Reset to a stored value. Observed 25 becoming 53. |
| `delay_off` | Reset to a stored value. Observed 53 becoming 70. |

Neither is documented. A user setting a sleep timer has not asked for a brightness change,
so the driver reads brightness first and restores it afterwards if the firmware moved it.

### The setup access point advertises no gateway

In setup mode the device serves DHCP on `192.168.4.0/24`, hands the client `192.168.4.2`,
and answers on `192.168.4.1`, but **advertises no default gateway**. Code that derives the
device address from the routing table finds nothing. Probe the `.1` host directly, or
sweep the subnet.

This is worth knowing because it looks exactly like a dead device.

## What is not supported

Verified absent on this model, so a client should not offer them:

- Colour and colour temperature. The lamp is fixed white.
- Native gradual transitions. There is no fade or transition parameter on any command;
  `delay_off` is a hard cut-off. Ramps must be driven by the controller.
- Any TCP service. Port scans of 22, 23, 80, 443, 1883, 6668, 8080 and 8443 all come back
  closed.
- Push or subscription. State must be polled.

## Further reading

- [python-miio](https://github.com/rytilahti/python-miio), the reference implementation
- [python-miio: legacy token extraction](https://python-miio.readthedocs.io/en/latest/legacy_token_extraction.html)
- [OpenMiHome](https://github.com/OpenMiHome/mihome-binary-protocol), independent protocol notes
