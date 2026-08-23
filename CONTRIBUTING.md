# Contributing

Contributions are welcome. Drivers for other miIO lights are the most useful and the most
self-contained.

## Before you start

- For a bug or a small fix, open a pull request directly.
- For a new driver, read [docs/DEVICES.md](docs/DEVICES.md) first. It is one file, one
  test, and no API change.
- For anything that changes the HTTP API, **open an issue first**. The compatibility
  promise in [docs/API.md](docs/API.md) makes an API mistake expensive to undo.

## Setting up

```bash
git clone https://github.com/smartwhale8/limelight.git
cd limelight
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check .
```

Both must pass on a clean checkout. The full suite runs without hardware, so you can
develop and verify against `tests/fakes.FakeTransport` before touching a device.

[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) covers testing, protocol debugging, and the
known traps.

## What a good pull request contains

1. **Tests that run without hardware.** Use or extend `FakeTransport`. CI has no lamp.
2. **Documentation for anything user-visible.** A new endpoint belongs in
   [docs/API.md](docs/API.md); a device belongs in the README table and
   [docs/PROTOCOL.md](docs/PROTOCOL.md).
3. **A CHANGELOG entry** under `Unreleased`.
4. **`ruff check .` passing.** CI enforces it.
5. **The firmware version you verified against**, for anything touching a device.

## Conventions

**Measure, do not assume.** Every hardware claim in this repository came from a device and
records the numbers observed. If you cannot verify something, mark it unverified rather
than stating it.

**Document the traps.** Firmware defects, platform restrictions and upstream bugs cost time
to find. Write down what you found, with its numbers, so nobody pays twice.

**Respect the layering rule.** Nothing above `limelight/drivers/` may reference a specific
device, miIO command, or model string. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Docstrings record decisions, not signatures.** The signature already says what a function
takes. A docstring earns its place by recording why, a measurement, or a trap.

## Never commit a secret

A device token is a complete credential: whoever has it controls the device.

- Real tokens, MAC addresses, network names and personal IP addresses stay out of commits,
  tests, documentation, issues and pull requests.
- Use the placeholders this repository already uses: `0` × 32 for a token,
  `AA:BB:CC:DD:EE:FF` for a MAC, `192.168.1.x` for an address, and `YourNetwork` for an
  SSID.
- `.gitignore` blocks the obvious filenames, but it is not a substitute for checking your
  diff.

If you commit a token by accident, reset the device to regenerate it. Rewriting history is
not enough, because the value may already have been fetched.

## Tests

```bash
pytest                              # everything
pytest tests/test_drivers.py        # one file
pytest -k quirk                     # by name
pytest --cov --cov-report=term-missing
```

Test names are the documentation, so `D103` is disabled for `tests/`. Prefer
`test_eyecare_restores_brightness_the_firmware_moved` over `test_eyecare_2`, and give
assertions a message when a failure needs explaining.

Two things about ramp tests, which have caught people out:

- **Wall-clock time follows `duration_min`, not `STEP_SECONDS`.** The step interval sets
  granularity only. Use a small `duration_min`, around `0.01`.
- **Wait for completion.** Use the `wait_for_ramp` helper rather than sleeping and hoping.

## Commit messages

A short imperative subject, then a body explaining why if it is not obvious.

```
Add driver for philips.light.bulb

Verified against firmware 2.1.0. Colour temperature is exposed as `cct`
on a 1..100 scale rather than kelvin, which the API reports as-is.
```

Do not include generated attribution trailers.

## Reporting a bug

Include your `limelight --version`, Python version and platform, the model and firmware
from `limelight info`, what you expected, what happened, and debug output where relevant.

**Redact first.** `limelight info` includes the token on some firmware, and raw replies may
include your network name.

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Licence

Contributions are accepted under the [MIT Licence](LICENSE).
