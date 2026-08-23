# Adoption: recovering a token and provisioning a device

A miIO device is protected by a single 16-byte token. Without it you cannot issue a
command; with it you have full control. This document covers getting one.

There are two situations, and the easy one is common.

## Situation 1: the device is on your network and discloses its token

Firmware that has never been bound to a vendor account answers an unauthenticated
handshake with its token in plaintext. If that is your case, adoption takes one command:

```bash
lamplight discover --subnet 192.168.1.
lamplight adopt --auto --name "Desk lamp"
```

`discover` reports which devices disclose a token:

```
  192.168.1.42  device_id=12345678  (token disclosed)
```

If it says `token withheld`, go to situation 2.

`--auto` refuses to guess when more than one device discloses a token, and prints the
exact flags for each so you can choose.

## Situation 2: the device is unprovisioned, or withholds its token

An unprovisioned device is not on your network at all. It broadcasts its own Wi-Fi access
point, waiting to be set up, and on that network it will disclose its token.

The access point name embeds the model and a per-unit suffix:

```
philips-light-sread1_miapXXXX
     |          |        |
     |          |        +-- per-unit discriminator
     |          +----------- model, philips.light.sread1
     +---------------------- vendor
```

`_miap` marks a Xiaomi miIO setup access point. Any SSID of that shape is a device waiting
for adoption.

### Procedure

**1. Put the device into setup mode.**

On the Philips Eyecare Smart Lamp 2, hold the touch power button for about five seconds,
until the indicator turns **yellow and flashes**. That clears the stored network
configuration and restarts the access point.

The access point is advertised for a limited window and then goes quiet, so do not
prepare afterwards. Have everything ready first.

**2. Start the adoption tool before switching networks.**

```bash
python tools/adopt_softap.py --home-ssid "YourNetwork"
```

It waits for your machine to land on the device's network, does the whole exchange, and
waits for you to come back before exiting. It never changes your network itself; see
[why](#why-you-switch-networks-by-hand).

To provision the device onto your Wi-Fi in the same pass, supply the password through a
file so it never enters your shell history:

```bash
# zsh
read -rs "?Wi-Fi password: " P && printf '%s' "$P" > /tmp/wifi_pass && unset P
# bash
read -rsp "Wi-Fi password: " P && printf '%s' "$P" > /tmp/wifi_pass && unset P

chmod 600 /tmp/wifi_pass
python tools/adopt_softap.py --home-ssid "YourNetwork" --password-file /tmp/wifi_pass
```

The tool deletes that file once provisioning succeeds.

**3. Join the device's access point** from your operating system's Wi-Fi menu. It is open,
so no password is involved. Ignore the "no internet" warning, which is correct.

**4. Wait, then switch back.** The tool prints `DONE ON THE DEVICE NETWORK` when it is safe
to reselect your normal network.

Between steps 3 and 4 it recovers the token, writes it to disk before attempting anything
else, records the device's self-description, and if given a password sends
`miIO.config_router` so the device joins your network permanently.

**5. Adopt it.**

```bash
lamplight discover --subnet 192.168.1.
lamplight adopt --ip <address> --token <token from the tool>
```

### Doing it by hand

The whole token recovery is a dozen lines, worth knowing in case the tool does not suit
your platform. While joined to the device's access point:

```python
import socket

HELLO = bytes.fromhex("21310020" + "ff" * 28)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2)
s.sendto(HELLO, ("192.168.4.1", 54321))       # the device answers on .1
reply, _ = s.recvfrom(1024)

print("device id:", int.from_bytes(reply[8:12], "big"))
token = reply[16:32]
print("token:", token.hex() if token != b"\xff" * 16 else "withheld")
```

Then hand over your Wi-Fi credentials:

```python
from lamplight.drivers.miio_transport import MiioTransport

t = MiioTransport("192.168.4.1", token.hex())
print(t.configure_wifi("YourNetwork", "your-password", uid=0))
```

The device reboots and joins your network. It no longer broadcasts its access point.

## Provisioning does not lock you out

`uid=0` provisions the device **without binding it to a vendor account**. That distinction
matters:

| | |
|---|---|
| **Provisioning** | Handing over Wi-Fi credentials. Does not change the token. |
| **Binding** | Registering the device against a vendor cloud account. **Regenerates the token.** |

A vendor setup flow performs both in one step, so a device configured that way holds a
token that was generated during binding.

Measured on this lamp after provisioning with `uid=0`: the handshake still discloses the
same token, `miIO.info` still returns it, and the stored token still authenticates. Nothing
was closed off.

The one action that will lock you out is pairing the device in a vendor app later. That
binds an account, rotates the token, and your stored one stops working. Recovery means the
five-second reset and a fresh extraction.

## Constraints and failure modes

| Symptom | Cause | What to do |
|---|---|---|
| No access point appears | The advertising window expired | Hold the button five seconds again |
| Access point appears, then vanishes | Same, or the device joined a remembered network | Reset again and work faster |
| Handshake returns `ff` × 16 | The device is bound to an account | See [below](#a-device-that-withholds-its-token) |
| No reply at all on the setup network | Probing the gateway instead of `.1` | The setup network advertises **no gateway**; probe `192.168.4.1` |
| Device never joins after provisioning | Wrong password, or a 5 GHz-only SSID | The radio is **2.4 GHz only**. Reset and retry. |
| `TypeError: 'int' object is not subscriptable` | `python-miio`'s `configure_wifi` | Harmless: the command already took effect. Use `MiioTransport.configure_wifi`. |

A wrong Wi-Fi password is recoverable. The device fails to associate and returns to
broadcasting its access point.

### The 2.4 GHz requirement

The ESP8266 has no 5 GHz radio. If your router publishes both bands under one SSID, the
device finds the 2.4 GHz side by itself. If the bands have separate names, give it the
2.4 GHz one.

### A device that withholds its token

If the handshake returns `ff` × 16, the device has been bound. Options, in order of
preference:

1. **Reset and re-extract.** The five-second hold clears the network configuration, and on
   many devices the binding with it. Try this first; it costs nothing.
2. **Extract from a vendor app installation.** If the device was set up on a phone you
   control, the token is in that app's local database. See
   [python-miio's notes on legacy token extraction](https://python-miio.readthedocs.io/en/latest/legacy_token_extraction.html).
3. **Read it from the vendor cloud.** With the account credentials the device is bound to,
   the token can be retrieved through the vendor API. `python-miio` ships tooling for this.
4. **A serial console.** The ESP8266 exposes UART. This means opening the device and is a
   last resort.

## Why you switch networks by hand

On recent macOS, a process without Location Services authorization cannot read Wi-Fi
network names at all: every SSID reads as `<redacted>`, and `networksetup
-setairportnetwork` fails with `-3900` even for the network you are already on. `sudo`
alone does not lift the restriction.

Rather than asking you to grant Location access to a terminal, `tools/adopt_softap.py`
watches for the subnet to change and does its work when it sees you arrive. It also waits
for you to return to your normal network before exiting, so that whatever launched it has
connectivity again by the time it finishes.

On Linux this restriction does not apply, and `nmcli` can join the access point directly:

```bash
nmcli device wifi connect "philips-light-sread1_miapXXXX"
```

## Where the token ends up

`~/.config/lamplight/config.json`, mode `0600`.

That file is the only thing standing between the network and your device. It is outside
the repository, and `.gitignore` blocks the obvious filenames in case a copy strays in.
Never commit one, and never paste one into an issue.

Also worth knowing, and covered in [../SECURITY.md](../SECURITY.md): on this firmware the
device hands its token to anyone on the network who asks. Protecting the token on your
disk is good practice, but the device's real perimeter is your Wi-Fi password.
