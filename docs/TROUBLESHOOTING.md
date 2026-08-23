# Troubleshooting

Symptoms, causes, and fixes. Start with the first section, which resolves most cases.

## First checks

```bash
limelight status                 # can we reach the device at all?
limelight discover              # is it on the network, and where?
limelight info                  # what does it say about itself?
```

`limelight discover` is the single most useful command. It needs no token, so it separates
"the device is unreachable" from "the credential is wrong".

---

## The device cannot be reached

### `Device error: get_prop failed after 3 attempts`

The transport retried, attempted rediscovery, and gave up.

| Cause | Check | Fix |
|---|---|---|
| The address changed | `limelight discover` | It updates the stored address automatically |
| The device is powered off | Is the lamp lit or responsive to touch? | Power it on |
| The device dropped off Wi-Fi | Does `discover` find nothing at all? | Power-cycle it; if it does not return, re-provision |
| Wrong subnet configured | `limelight capabilities` shows the address | `limelight adopt --subnet 192.168.1.` |
| Client and device on different subnets | Compare your address with the device's | Guest networks and VLANs block this; use the same subnet |
| Wrong token | `discover` finds it but commands fail | Re-adopt with the correct token |

A wrong token presents exactly like an unreachable device: the payload cannot be decrypted,
so the device does not answer at all. If `discover` sees the device but every command times
out, suspect the token before the network.

### `discover` finds nothing

1. **Check the subnet prefix.** It must include the trailing dot: `192.168.1.`, not
   `192.168.1`. Find yours with `ip addr` or `ifconfig`.
2. **Check for client isolation.** Many routers block client-to-client traffic on guest
   networks, which stops discovery and control.
3. **Check for a firewall.** Discovery sends UDP to the broadcast address and to every host
   on the /24; a host firewall may block the replies.
4. **Consider that the device may be unprovisioned.** If it never joined your network it is
   broadcasting its own access point. See [ADOPTION.md](ADOPTION.md).

### Rediscovery warnings in the log

```
WARNING limelight.drivers.miio_transport: device unreachable at 192.168.1.42, rediscovering
```

This is normal in moderation. UDP has no delivery guarantee, so an occasional lost datagram
triggers a retry and a rediscovery, and the command then succeeds. Continuous warnings
indicate weak signal or genuine instability; check the `rssi` field in `limelight info`.

---

## Adoption problems

### `No driver for model 'x.y.z'`

The device works and the token is right, but no driver is registered for that model. See
[DEVICES.md](DEVICES.md); for a miIO light this is usually a short file.

### `a miIO token is 32 hexadecimal characters (16 bytes)`

The token is malformed. It is 32 hex characters with no spaces, dashes, or `0x` prefix.

### The handshake returns a withheld token

The device is bound to a cloud account, which regenerates the token. Options are listed in
[ADOPTION.md](ADOPTION.md#a-device-that-withholds-its-token); try the five-second reset
first.

### The setup access point never appears

It is advertised for a limited window after a reset and then stops. Hold the touch power
button for about five seconds until the indicator flashes yellow, and have everything ready
before you start.

### Nothing responds on the setup network

The setup network **advertises no default gateway**, so anything deriving the device address
from the routing table finds nothing. The device answers on `192.168.4.1`. Probe it
directly.

### The device never joins after provisioning

| Cause | Fix |
|---|---|
| Wrong Wi-Fi password | Reset and retry; a failed join is not destructive |
| 5 GHz-only SSID | The radio is 2.4 GHz only. Give it the 2.4 GHz network name. |
| Enterprise or captive-portal network | Not supported. Use a WPA2 personal network. |
| Hidden SSID | Unreliable on this firmware. Make it visible for setup. |

### `TypeError: 'int' object is not subscriptable`

From `python-miio`'s `Device.configure_wifi`. It indexes the reply as `send(...)[0]` while
this firmware answers with a bare integer.

**The command already took effect.** The exception is in the library's response handling,
after the device acted. Use `MiioTransport.configure_wifi`, which sends the command
directly.

---

## Service problems

### `No device configured`

Nothing has been adopted yet. Run `limelight adopt`. If you have adopted a device, check
that `LIMELIGHT_CONFIG` is not pointing somewhere unexpected.

### `Address already in use`

Another process holds the port.

```bash
lsof -i :8765            # find it
limelight serve --port 9000
```

If a `launchd` or `systemd` unit is installed, it is probably already running the service.

### The page loads but shows "unreachable"

The service is healthy and the device is not. Work through
[the device cannot be reached](#the-device-cannot-be-reached). The interface deliberately
renders a degraded view rather than an error, so controls remain visible while the device
is absent.

### A phone cannot reach the service

1. **Same network?** Phones switch to mobile data readily. Confirm the Wi-Fi network.
2. **Right address?** Use the machine's LAN address, not `localhost`. `./run.sh` prints it.
3. **Bound to loopback?** The default host is `0.0.0.0`. Check for `--host 127.0.0.1`.
4. **Host firewall?** macOS and Linux both may prompt or silently block inbound
   connections.

### `401 missing or invalid API key`

Authentication is enabled. Check `GET /api/v1/health`, which reports `auth_required`
without needing a key. Then send `Authorization: Bearer <key>`. In the browser, clear the
stored key and let the page prompt again:

```javascript
localStorage.removeItem("limelight_key"); location.reload();
```

Note that `LIMELIGHT_API_KEY` in the environment overrides the value in the configuration
file.

---

## Behaviour problems

### Brightness changes when I turn eyecare on

Expected. Eyecare mode sets its own brightness and ramps to it over about three seconds.
It is the mode working, not a fault.

### Eyecare turns itself off immediately

Something is sending a brightness command straight after enabling it. `set_bright` cancels
eyecare on this hardware, and there is no way to hold both.

If you see the lamp's base flash the eye symbol and revert to the brightness markers, that
is the symptom. Moving the brightness slider while eyecare is on does the same thing, by
design. Versions before 2.0.1 did it automatically and the mode could not be kept on at
all; upgrade.

### A scheduled sunrise did not happen

In order of likelihood:

1. **The service was not running.** `sunrise` and `fade_off` are driven by limelight, not
   the device. If the process was not running at the scheduled minute, nothing happened.
2. **The host was asleep.** Same consequence. A sleeping machine sends no datagrams.
3. **The schedule is disabled.** `limelight schedules` shows `[on ]` or `[off]`.
4. **Wrong weekday numbering.** Monday is 0 and Sunday is 6.
5. **The service started after the scheduled minute.** Schedules are evaluated live and are
   not replayed.

For a wake-up you depend on, use `kind: timer` where possible, since the device counts down
itself, and run the service on a machine that stays awake. See
[running it permanently](../README.md#running-it-permanently).

### A ramp stopped part-way

Any manual `power` or `brightness` command cancels a running ramp by design. A new ramp
also supersedes the previous one. Otherwise, check `last_error` in `GET /api/v1/state`.

### The sleep timer cleared itself

`delay_off` counts down on the device and resets on power loss. It is also cleared by
setting it to 0. It does not survive the device rebooting.

### A schedule fires an hour early or late

Times are the server's local time, with no timezone stored. After a daylight-saving change
the wall-clock time is honoured, which is usually what is wanted. If the host's timezone is
wrong, schedules shift with it.

---

## Platform notes

### macOS hides Wi-Fi network names

Every SSID appears as `<redacted>` and `networksetup -setairportnetwork` fails with
`-3900`, even for the network already joined. The calling process lacks Location Services
authorization. `sudo` alone does not lift it.

This is why adoption asks you to switch networks by hand. Nothing is broken.

### macOS sleeps and stops ramps

`caffeinate -s` while a ramp runs, or install the `launchd` agent and disable sleep in
System Settings if you rely on scheduled ramps.

### Linux and `systemd --user`

A user unit stops at logout unless lingering is enabled:

```bash
loginctl enable-linger "$USER"
```

---

## Getting diagnostics

```bash
limelight serve --log-level debug
limelight status --json --raw          # decoded state plus the raw device reply
limelight info                         # firmware, MAC, signal strength
```

Watch the wire, noting that payloads are encrypted but sizes and timing are visible:

```bash
sudo tcpdump -i any -n 'udp port 54321'
```

### Reporting a problem

Include the output of `limelight --version`, your Python version and platform, the firmware
and model from `limelight info`, what you expected, what happened, and any log lines at
`--log-level debug`.

**Redact before posting.** `limelight info` includes the token on some firmware, and the
raw reply may include your network name. Replace them with `<token>` and `<ssid>`.
