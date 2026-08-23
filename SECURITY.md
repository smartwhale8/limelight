# Security

## Reporting a vulnerability

Report privately through
[GitHub Security Advisories](https://github.com/smartwhale8/limelight/security/advisories/new)
rather than as a public issue. Include what an attacker gains, how to reproduce it, and any
affected versions.

This is a personal project with no paid maintenance commitment. Expect a first response
within a couple of weeks.

---

## The threat model

limelight controls lighting on a local network. Understanding what is and is not protected
matters more here than in most projects, because two of the weaknesses are in the hardware
and cannot be fixed in software.

### What an attacker gains

Control of a lamp. There is no camera, no microphone, and no path from the device to your
data. The realistic harms are nuisance, an inference about occupancy from usage patterns,
and the device being one more foothold on your network.

### The token is the only credential

A miIO device is protected by a single 16-byte token. There is no user, no password, and no
per-command authorisation. **Whoever holds the token controls the device completely.**

limelight stores it in `~/.config/limelight/config.json` at mode `0600`, written atomically
so a partial write cannot leave it readable. The token is never returned by any API
endpoint, and `POST /api/v1/discover` strips it from discovery results.

One exception is deliberate and documented: `GET /api/v1/info` returns the device's raw
self-description, which on some firmware **includes the token**. Do not log or display that
response. It exists for diagnostics.

---

## Two hardware weaknesses you should know about

Neither can be fixed by this or any other controller. They are properties of the device.

### 1. The device discloses its own token, without authentication

The miIO handshake is unencrypted by design, since it precedes key derivation. On the
firmware verified here, the device answers that handshake with its token in plaintext, to
any host on the network, with no credential required. `miIO.info` also returns it.

The practical consequence:

> **Anything that can send a UDP datagram to the device can obtain full control of it in a
> single round trip.**

The device's real perimeter is your Wi-Fi password, not the token. Mitigations, in order of
effectiveness:

- **Use WPA2 or WPA3 on your network, with a strong passphrase.** This is the actual
  control.
- **Put the device on an IoT VLAN or a separate SSID**, reachable from the machine running
  limelight and nothing else, if your router supports it.
- **Do not put it on a network shared with guests.** A guest with the Wi-Fi password can
  take the device.

### 2. Setup mode is an open network

While unprovisioned, the device broadcasts an **open, unencrypted** access point, and on
that network it discloses its token. Anyone in radio range during that window can adopt the
device, and can also read the Wi-Fi credentials that a provisioning command carries, since
`miIO.config_router` is encrypted only under a token that was just handed out in plaintext.

Keep the window short. The device stops advertising by itself after a period, and a reset
restarts it only when you choose.

---

## The service

### No authentication by default

The HTTP service requires no credential unless one is configured. On a private home network
this is a reasonable default and matches how the device itself behaves. Anything that can
reach the port can control the device.

To require a key:

```bash
export LIMELIGHT_API_KEY="$(openssl rand -hex 24)"
limelight serve
```

Clients then send `Authorization: Bearer <key>` or `X-API-Key: <key>`. Keys are compared
with `secrets.compare_digest`, so the comparison does not leak the value through response
timing.

Its limits, stated plainly:

- **It is a single shared secret**, not per-client identity. Anyone with the key is
  indistinguishable from anyone else with it.
- **It travels over plain HTTP.** Anyone able to observe your network traffic can read it.
  On a WPA2 or WPA3 network, other clients cannot read your traffic; on an open network they
  can.
- **`GET /api/v1/health` stays unauthenticated**, so a client can identify a service before
  pairing. It exposes the service name, version, device name and model, and whether a key
  is required. It exposes no state and no credential.

### Do not expose the port to the internet

The service binds `0.0.0.0` so a phone on your network can reach it. It is not built to face
the internet: plain HTTP, at most one shared secret, and no rate limiting.

For access from outside, use a VPN into your network (WireGuard or Tailscale). If you put a
reverse proxy in front of it for TLS, keep it on your own network and set an API key as
well.

### What the service does not do

- No telemetry, analytics, or external requests of any kind.
- No shell execution. Nothing accepts a command string.
- No file access beyond the configuration file.
- No credential appears in any log line.

---

## Hardening checklist

| Step | Effect |
|---|---|
| WPA2 or WPA3 with a strong passphrase | The main control, given the hardware weakness above |
| Device on an IoT VLAN or separate SSID | Limits which hosts can reach it |
| Set `LIMELIGHT_API_KEY` | Stops other devices on your network commanding the service |
| Keep `config.json` at `0600` | The default; verify after any manual edit |
| Do not forward the port | Use a VPN for outside access |
| Bind to one interface if you do not need phone access | `limelight serve --host 127.0.0.1` |
| Never post `limelight info` output unredacted | It can contain the token |

## Scope

In scope: token or key disclosure by the service, authentication bypass, anything permitting
command execution or file access, and dependency vulnerabilities that are reachable in
practice.

Out of scope, being documented properties of the hardware rather than defects here: the
device disclosing its own token, the open setup access point, and the absence of transport
encryption in miIO.
