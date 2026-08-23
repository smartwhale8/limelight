# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The HTTP API
contract in [docs/API.md](docs/API.md) is what the major version protects.

## [Unreleased]

Nothing yet.

## [1.1.1] - 2026-08-23

### Fixed

- The Python source distribution was 16 MB, because the release workflow builds the Android
  APK before packing the sdist and hatchling does not honour nested `.gitignore` files, so
  `android/app/build` was swept in. The sdist now uses an explicit include list, so its
  contents no longer depend on what happens to be on disk. It is 97 KB.

## [1.1.0] - 2026-08-23

> **Artifacts withdrawn.** The published build carried a 16 MB source distribution that had
> Android build output swept into it. The release was deleted and superseded by 1.1.1. The
> tag remains, because the commit it points at is real and the changes below shipped; only
> the artifacts were faulty. Use 1.1.1.

### Added

- **Android client** in `android/`, speaking miIO directly to the lamp over UDP rather than
  through the HTTP service, so it works with nothing else running. Discovery, connection and
  every device operation are implemented. No third-party runtime dependency: `javax.crypto`,
  `java.net` and `org.json` only.
- `constraints.txt`, recording the exact versions the project is built and tested against.
  CI installs with `-c`, so a red build means a change here broke something rather than an
  upstream release having shipped.
- `tests/test_dependency_contract.py`, asserting the two imports and three calls we rely on
  from python-miio, and enforcing that no module outside the transport imports it.
- A release workflow: a `v*` tag builds the Android APK and the Python distribution and
  attaches both to a GitHub Release.
- A test asserting that `__version__` and the `pyproject.toml` version agree.

### Changed

- **python-miio capped below 0.6.** It is a 0.x project, so the minor version carries
  breaking changes, and 0.6 is a large refactor adding MIoT support and an introspectable
  API. 0.5.12 is the current stable release and the last of the 0.5 line.
- **CI matrix narrowed** from 3.11, 3.12 and 3.13 to 3.11 and 3.14: the declared floor, and
  the version actually used for development, which had not been tested at all.
- CI now compiles the Android client on GitHub's runners, which carry the Android SDK.
- README's protocol tutorial condensed from 323 lines to 167, deferring byte-level detail to
  `docs/PROTOCOL.md`, which already covered the same ground in more depth.

### Fixed

- The Kotlin codec omitted the null terminator that the reference implementation appends to
  the JSON before encrypting. Found by comparing bytes against python-miio; the packets
  looked correct and would have failed against the firmware.

## [1.0.0] - 2026-08-23

First release.

### Added

**Device layer**

- miIO transport over UDP 54321, with AES-128-CBC payloads, per-command retry with
  backoff, and automatic rediscovery by device id when a DHCP address changes.
- Driver contract (`LightDriver`, `Capability`, `LightState`) with a model registry, so a
  device type can be added without touching the service.
- `Transport` as a `typing.Protocol`, allowing the whole suite to run against an in-memory
  fake with no hardware and no network.
- Driver for `philips.light.sread1`, the Philips Eyecare Smart Lamp 2: power, brightness,
  eyecare mode, ambient light and its brightness, four fixed scenes, smart night light,
  eye-fatigue reminder, and the device's own sleep timer.
- Compensation for two undocumented firmware defects, where `set_eyecare` and `delay_off`
  each reset brightness as a side effect.
- Handshake-based discovery and token recovery, which needs no credential.
- `configure_wifi`, sending `miIO.config_router` directly rather than through
  `python-miio`'s helper, which raises `TypeError` against this firmware because it indexes
  a reply that arrives as a bare integer.

**Service**

- HTTP API versioned at `/api/v1`, with an OpenAPI schema at `/openapi.json` and
  interactive documentation at `/docs`.
- Capability negotiation through `GET /api/v1/device`, so clients build an interface from
  data rather than assumptions, and unsupported operations return HTTP 400.
- `GET /api/v1/state` returning device state, schedules, ramp progress and next firings in
  one call.
- `GET /api/v1/health`, unauthenticated, for service identification before pairing.
- Optional bearer-token authentication, disabled by default, accepting `Authorization:
  Bearer` or `X-API-Key`, compared with `secrets.compare_digest`.
- Optional CORS configuration.
- `create_app()` factory with an injected driver, and a lazily built module-level `app`, so
  importing the module contacts no hardware.

**Behaviour**

- Sunrise ramps and fade-to-off ramps, driven by the service because the hardware has no
  native transitions, cancellable and superseded by any manual command.
- Recurring schedules with per-weekday selection and five kinds: `sunrise`, `fade_off`,
  `on`, `off`, and `timer`.
- A `service_driven` flag on every ramp and schedule, distinguishing behaviour that needs
  the service running from the device's own countdown, which does not.

**Interfaces**

- Self-contained single-page web interface with no external requests, capability gating,
  dark and light themes, and sliders that commit on release rather than per pixel.
- Command line covering discovery, adoption, every device function, foreground ramps,
  schedule listing, capability inspection, and running the service.
- `lamplight adopt --auto`, adopting a device that discloses its own token in one step.

**Project**

- 157 tests, all running without hardware. Coverage: 100% of the driver and configuration
  layers, 91% of the scheduler, 86% of the service.
- Transport tests exercising real UDP against a loopback stand-in that answers with
  hardware-layout packets, so a byte-offset error fails the build.
- Documentation: protocol reference, HTTP contract with captured responses, adoption
  procedure, architecture, development guide, device-porting guide, troubleshooting, and
  roadmap.
- CI on Python 3.11 through 3.13, running `ruff` and the suite.
- `launchd` and `systemd` units for running the service permanently.

### Security

- The configuration file, which holds the device token, is written atomically at mode
  `0600`.
- The token is never returned by any API endpoint, and is stripped from discovery results.
- [SECURITY.md](SECURITY.md) documents two hardware weaknesses that cannot be fixed in
  software: the device discloses its own token to any unauthenticated request on the local
  network, and its setup access point is open and unencrypted.

[Unreleased]: https://github.com/smartwhale8/lamplight/compare/v1.1.1...HEAD
[1.1.1]: https://github.com/smartwhale8/lamplight/releases/tag/v1.1.1
[1.1.0]: https://github.com/smartwhale8/lamplight/releases/tag/v1.1.0
[1.0.0]: https://github.com/smartwhale8/lamplight/releases/tag/v1.0.0
