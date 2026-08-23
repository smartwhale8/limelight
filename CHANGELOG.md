# Changelog

All notable changes to this project are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The HTTP API
contract in [docs/API.md](docs/API.md) is what the major version protects.

## [Unreleased]

### Changed

- **The distribution name is `limelight-miio`.** PyPI refuses the bare name `limelight`,
  answering "this project name isn't allowed" at registration. No project of that name
  exists, so it sits on PyPI's prohibited list, which is not public and which nothing
  outside the registration form can inspect. Every availability check reported it free.

  Nothing else changes: `import limelight`, the `limelight` and `limelight-server`
  commands, the repository and the Android application id `com.smartwhale8.limelight` are
  all unaffected. Only the string after `pip install` differs, which is a normal split
  between distribution name and import name.

### Added

- Publishing to PyPI from the release workflow, authenticated with Trusted Publishing
  rather than an API token, so no long-lived secret is stored in the repository. A manual
  run can target TestPyPI instead, which matters because PyPI versions are immutable and a
  number cannot be reused once uploaded.

### Fixed

- Every link in the README is now absolute. PyPI resolves relative links against
  `pypi.org`, so all 21 of them would have 404'd on the package page.
- The licence is declared as the SPDX expression `MIT` rather than a file reference, so
  PyPI shows a licence chip instead of printing the entire MIT text in the sidebar.

### Removed

- `run.sh`. It duplicated `limelight serve`, which the package already installs, and was a
  shell script at the root of a Python project that only worked on macOS and Linux.

### Changed

- The one thing `run.sh` did that the service did not, printing the address a phone can
  reach, now lives in the service, so `limelight serve`, `limelight-server` and
  `python -m limelight.server` all print it. Binding to a single interface now says so
  instead of printing a LAN URL that would not work. `--quiet` suppresses the banner.
- The LAN address is now found by opening a UDP socket towards a non-routed address and
  reading the local end, which lets the kernel pick the outbound interface. The previous
  approach guessed at interface names, which differ across platforms.

## [2.0.1] - 2026-08-23

Three device behaviours were wrong in the previous release, all found by testing against
real hardware rather than by reasoning.

### Fixed

- **Eyecare mode could not be switched on.** Enabling it made the lamp's base flash the eye
  symbol and revert immediately to the brightness markers. The driver re-applied brightness
  straight after `set_eyecare`, and on this hardware `set_bright` cancels eyecare, so the
  mode was switched on and off in one operation. Both clients now leave brightness alone
  around eyecare.
- **Scene 4 failed with `param error`.** The device accepts 1, 2 and 3 only. The range of
  1 to 4 was asserted and never checked, and the four scene names were invented. They are
  now reported as "Scene 1" to "Scene 3", because setting a scene changes `scene_num` and
  nothing else readable, so a descriptive name would be invention.
- **A rejected command was retried three times and reported as "unreachable".** A device
  that answers with an error has been reached and has refused; retrying cannot help. Such
  errors now raise `DeviceCommandError` immediately, carrying the device's own code, and
  the API maps them to 400 rather than 503.
- **The sleep timer control clipped its own label.** Four equal-width buttons meant "Clear"
  did not fit its quarter of the row. Replaced in both clients with a slider and a cancel
  icon, which also covers every duration rather than three presets.

### Added

- **`tests/test_hardware.py`**, a suite that runs against a real adopted device. Deselected
  by default and never run in CI, invoked with `pytest -m hardware`. It captures the lamp's
  state and restores it afterwards, including when a test fails, and skips when no device is
  configured. Fourteen tests, covering reachability, control round trips, the eyecare
  coupling and the scene range.

  This exists because the bugs above were found with throwaway shell scripts that were
  discarded each time, so nothing stopped them regressing. Device findings now live as
  tests.

### Changed

- **Corrected a documented finding.** Previous releases described two firmware defects, in
  which `set_eyecare` and `delay_off` each reset brightness. The measurements were real and
  the interpretation was wrong. There is one behaviour: enabling eyecare hands brightness to
  the mode, which ramps to its own level over about three seconds, observed as 25 rising to
  53 then 70. The apparent second defect came from issuing `delay_off` during that ramp and
  crediting the ramp to the wrong command. `delay_off` disturbs nothing. The correction is
  recorded in `docs/PROTOCOL.md` rather than quietly removed.
- A sunrise or fade ramp switches eyecare off, because ramps step `set_bright`. Documented
  in `scheduler.py`.
- `docs/ROADMAP.md` now sets out exactly what a phone-side scheduled wake-up would
  require, including the parts that cannot be solved in code, so the cost is known before
  anyone starts.
- `ResourceWarning` is filtered. python-miio opens a UDP socket per call and closes none;
  measured over thirty consecutive commands, descriptors do not accumulate, because CPython
  reclaims each socket by refcounting. There is nothing callers can close.

## [2.0.0] - 2026-08-23

**The project is renamed from lamplight to limelight.** Entries below this one were written
under the old name.

The reason is concrete rather than cosmetic: `lamplight` is taken on PyPI by an unrelated
package, so `pip install lamplight` fetched an OpenAI wrapper rather than this project. The
distribution name would have had to differ from the import name forever, leaving two names
to explain and a trap for anyone who guessed. `limelight` is free, so the repository, the
distribution, the import name, the console script and the Android application id are now all
the same word.

The name is also apt: limelight was a real lighting technology, burning calcium oxide to
produce an intense white light, used to light theatre stages from the 1830s.

### Changed

- **Breaking: the import name is now `limelight`.** `import lamplight` no longer resolves.
- **Breaking: the console scripts are `limelight` and `limelight-server`.**
- **Breaking: the distribution name changed.** See 2.1.0: PyPI refuses the bare name
  `limelight`, so the distribution is `limelight-miio` while the import name, console
  scripts and Android id all remain `limelight`.
- **Breaking: the Android application id is `com.smartwhale8.limelight`**, so the app
  installs alongside an older build rather than upgrading it. Remove the old one.
- Configuration moved to `~/.config/limelight/`.
- Environment variables are `LIMELIGHT_CONFIG`, `LIMELIGHT_API_KEY`, `LIMELIGHT_PYTHON` and
  `LIMELIGHT_PORT`. The `LAMPLIGHT_` forms of the two configuration variables are still
  honoured.
- The `launchd` label is `io.github.smartwhale8.limelight` and the `systemd` unit is
  `limelight.service`. Reinstall them if you had them.

**The HTTP API is unchanged and remains at `/api/v1`.** The major version reflects the
rename of the package and its entry points, not a change to the wire contract, so a client
built against `/api/v1` keeps working.

### Added

- Automatic migration of a pre-rename configuration. On first run, `~/.config/lamplight/` is
  copied to `~/.config/limelight/` with `0600` permissions preserved, and the original is
  left in place. Without this an existing installation would look unconfigured and ask the
  user to re-adopt a device, which is worse than an error because the device token is not
  trivial to recover a second time.

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
- `limelight adopt --auto`, adopting a device that discloses its own token in one step.

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

[Unreleased]: https://github.com/smartwhale8/limelight/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/smartwhale8/limelight/releases/tag/v2.0.1
[2.0.0]: https://github.com/smartwhale8/limelight/releases/tag/v2.0.0
[1.1.1]: https://github.com/smartwhale8/limelight/releases/tag/v1.1.1
[1.1.0]: https://github.com/smartwhale8/limelight/releases/tag/v1.1.0
[1.0.0]: https://github.com/smartwhale8/limelight/releases/tag/v1.0.0
