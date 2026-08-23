# Development guide

Setting up, running, testing, debugging the protocol, and releasing. Written to be
sufficient for someone, or something, encountering the codebase for the first time.

**Contents**

1. [Getting set up](#getting-set-up)
2. [Running it](#running-it)
3. [Working without hardware](#working-without-hardware)
4. [The test suite](#the-test-suite)
5. [Code style](#code-style)
6. [Debugging the protocol](#debugging-the-protocol)
7. [Common tasks](#common-tasks)
8. [Pitfalls](#pitfalls)
9. [Releasing](#releasing)
10. [Project conventions](#project-conventions)

---

## Getting set up

Python 3.11 or newer. The floor is 3.11 because the code uses `enum.StrEnum` and
`X | None` annotations at runtime.

```bash
git clone https://github.com/smartwhale8/limelight.git
cd limelight
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -c constraints.txt
```

`[dev]` brings the server extras, `pytest`, `pytest-cov`, `ruff`, and an HTTP client for
the test client.

### Why `-c constraints.txt`

`pyproject.toml` declares **abstract ranges**, which is what makes the package installable
alongside others. `constraints.txt` records the **concrete resolution** we build and test
against, so an install is reproducible and an upstream release cannot turn CI red for
reasons unrelated to a change here.

That is not hypothetical. An unpinned `starlette` release began requiring `httpx2`, and a
clean install failed at test collection while a local environment that happened to have
`httpx2` installed passed.

Regenerate it deliberately, never as a side effect of something else:

```bash
python -m venv /tmp/resolve
/tmp/resolve/bin/pip install -e ".[dev]"
/tmp/resolve/bin/pip freeze --exclude-editable > constraints.txt   # keep the header comment
rm -rf /tmp/resolve
```

### On the `python-miio` bound

`python-miio` is capped below `0.6`. It is a `0.x` project, so under semantic versioning the
**minor** version carries breaking changes, and `0.6` is a large refactor adding MIoT support
and an introspectable API.

Our surface is deliberately tiny: two imports and three calls, all inside
`limelight/drivers/miio_transport.py`. `tests/test_dependency_contract.py` asserts that
surface and also enforces that no other module imports `miio`, so a future migration has one
file to change and fails loudly rather than at runtime against a device.

Verify:

```bash
pytest -q          # the whole suite, no hardware needed
ruff check .
```

Both should pass on a clean checkout. If they do not, that is a bug worth an issue.

### Dependency layout

| Extra | Contents | Why separate |
|---|---|---|
| base | `python-miio` | The drivers and CLI work with nothing else |
| `[server]` | `fastapi`, `uvicorn` | Not needed to script a lamp |
| `[dev]` | `[server]`, `pytest`, `pytest-cov`, `ruff` | |

Keeping the server optional is deliberate. Someone embedding the driver in another program
should not have to install a web framework.

---

## Running it

```bash
limelight serve                     # reads host and port from configuration
limelight serve --port 9000
python -m limelight.server          # equivalent
limelight serve --quiet             # without the startup URLs
```

Then <http://localhost:8765>, plus `/docs` for interactive API documentation and
`/openapi.json` for the schema.

For iterating on `server.py` or `web.py`, use reload:

```bash
uvicorn limelight.server:app --reload --port 8765
```

Reload works because the module-level `app` is built lazily through a module
`__getattr__`. Importing `limelight.server` contacts no hardware.

### Configuration during development

Configuration lives in `~/.config/limelight/config.json`. Redirect it to keep experiments
away from a working setup:

```bash
export LIMELIGHT_CONFIG=/tmp/limelight-dev
limelight adopt --ip 192.168.1.42 --token <token>
```

The test suite sets this automatically for every test, so a run can never read or
overwrite a real token.

---

## Working without hardware

The whole suite, and most manual work, needs no lamp.

`tests/fakes.py` provides `FakeTransport`, an in-memory device that satisfies the
`Transport` protocol. It reproduces the real firmware's behaviour, **including its two
brightness defects**, on purpose: a fake that behaved better than the hardware would let
the compensation code rot unnoticed.

```python
import sys; sys.path.insert(0, ".")
from tests.fakes import FakeTransport
from limelight.drivers.philips_eyecare import PhilipsEyecareLamp

lamp = PhilipsEyecareLamp(FakeTransport())
lamp.turn_on()
lamp.set_brightness(40)
print(lamp.state())
print(lamp.transport.calls)      # every command sent, in order
```

To exercise the HTTP layer:

```python
from fastapi.testclient import TestClient
from limelight.config import Config, DeviceConfig
from limelight.server import create_app

cfg = Config(device=DeviceConfig(ip="192.168.1.50", token="0" * 32,
                                 model="philips.light.sread1"))
client = TestClient(create_app(cfg, lamp))
print(client.get("/api/v1/state").json())
```

`FakeTransport` options worth knowing:

| Option | Effect |
|---|---|
| `props={...}` | Set the starting state |
| `fail_after=N` | Every command past the Nth raises `DeviceUnreachable`, for error paths |
| `couple_eyecare=False` | Drop the eyecare/brightness coupling, to isolate something else |

---

## The test suite

```bash
pytest                              # everything
pytest tests/test_drivers.py        # one file
pytest -k eyecare                   # by name
pytest --cov --cov-report=term-missing
pytest -x -vv                       # stop at the first failure, verbose
```

| File | Covers |
|---|---|
| `test_hardware.py` | Real device behaviour. Deselected unless `-m hardware` is given |
| `test_dependency_contract.py` | The parts of python-miio we rely on, so an upgrade fails loudly |
| `test_drivers.py` | Driver behaviour, capabilities, and the eyecare/brightness coupling |
| `test_transport.py` | Wire protocol parsing, against a real loopback UDP socket |
| `test_scheduler.py` | Ramp arithmetic, cancellation, due-time evaluation |
| `test_config.py` | Validation, persistence, file permissions |
| `test_api.py` | Every endpoint, error codes, authentication, versioning |

### Conventions

**Names are the documentation.** `test_eyecare_restores_brightness_the_firmware_moved`
says what is guaranteed. `D103` is disabled for `tests/` for this reason.

**Assert on intent, with a message.** `assert levels == sorted(levels), "a sunrise must
never dim part-way through"` explains why a failure matters.

**Warnings are errors.** `filterwarnings = ["error"]` in `pyproject.toml`, with narrow
exemptions for `python-miio`'s own deprecations. A new warning from our code fails the
build.

### Two things to know before writing ramp tests

**Wall-clock time follows `duration_min`, not the step interval.** `STEP_SECONDS` only sets
granularity: steps are `duration_s / STEP_SECONDS`, each waiting `STEP_SECONDS`. Shrinking
`STEP_SECONDS` makes a ramp finer, not faster. Use a small `duration_min`, around `0.01`,
for a ramp that finishes in under a second.

**Wait for completion, do not sleep and hope.** Use the `wait_for_ramp` helper in
`test_scheduler.py`, which polls `ramp.active` with a timeout.

### The hardware suite

Everything else runs against a fake, which is what lets CI verify the project with no lamp.
A fake can only reproduce behaviour someone already understood, so it cannot catch a
misunderstanding of the device. `tests/test_hardware.py` closes that gap:

```bash
pytest -m hardware          # against the device in ~/.config/limelight
```

It is deselected by default and never runs in CI. It **changes the state of a real lamp**,
so a fixture captures everything first and restores it afterwards, including when a test
fails. It skips rather than fails when no device is adopted or the device is unreachable.

This suite exists because of a real bug. The driver used to re-apply brightness after
enabling eyecare, believing it was correcting a firmware defect; because `set_bright`
cancels eyecare, that made the mode impossible to switch on. Every probe that established
the true behaviour had been written ad hoc in a shell and thrown away, so nothing caught
the regression. Those probes are now tests.

Keep new findings here rather than in a scratch script. If you measure something about a
device, that measurement is worth more as a test than as a paragraph.

### Testing the transport

`test_transport.py` binds a real UDP socket on loopback and answers handshakes with
packets built to the hardware's layout, then monkeypatches `MIIO_PORT` to that port. This
is deliberately not a mock: the code under test is byte-offset parsing, and a mock
returning tidy dictionaries would prove nothing about offsets. If you change the packet
layout, these tests are what catch it.

---

## Code style

`ruff` is the authority. `ruff check .` must pass, and CI enforces it.

Beyond the linter:

**Docstrings say why, not what.** The signature says what. A docstring earns its place by
recording a decision, a measurement, or a trap.

```python
# Not useful
def set_sleep_timer(self, minutes: int):
    """Set the sleep timer."""

# Useful
def set_sleep_timer(self, minutes: int):
    """Device cut-off after ``minutes``; 0 cancels it.

    The countdown runs on the device, so it survives this application exiting. It does
    not disturb brightness or any other setting.
    """
```

**Record measurements with their numbers.** "Observed 25 becoming 53" is worth far more
than "resets brightness", because it lets the next reader confirm the behaviour still
holds.

**Separate the measurement from the interpretation.** Both are worth writing down, but
they are not the same thing and the second is where mistakes live. This project once
recorded two firmware defects that did not exist: the measurements were correct, but one
command was issued during another's ramp and the ramp was credited to the wrong command.
The compensation built on that reading then broke the feature it was meant to protect.

**Comment surprises inline.** Where code looks wrong but is right, say why:

```python
# strict=False: some firmware returns fewer values than requested, and
# LightState reads with .get() so a missing property becomes None.
values = dict(zip(PROPS, self.transport.send("get_prop", PROPS), strict=False))
```

**Never break the layering rule.** Nothing above `drivers/` may name a device, a miIO
command, or a model string. See [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Debugging the protocol

### Turn on debug logging

```bash
limelight serve --log-level debug
```

Or in a script:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

`MiioTransport.send` logs each failed attempt at `DEBUG` and each rediscovery at
`WARNING`. A `WARNING` about rediscovery is normal and means a datagram was lost.

### Talk to a device by hand

```bash
python -m limelight.cli info                       # miIO.info
python -m limelight.cli status --json --raw        # decoded plus the raw reply
python -m limelight.cli discover --subnet 192.168.1.
```

Raw commands, including undocumented ones:

```python
from limelight.config import Config
from limelight.device import build_driver

cfg = Config.load()
d = build_driver(cfg.device.ip, cfg.device.token, model=cfg.device.model)
print(d.transport.send("get_prop", ["power", "bright"]))
print(d.transport.send("miIO.ota_state", []))      # probe for something undocumented
```

An unsupported method raises a `python-miio` exception carrying the device's error code,
which is itself informative.

### Watch the wire

```bash
sudo tcpdump -i any -n -X 'udp port 54321'
```

Payloads are encrypted, but sizes, timing and retransmissions are visible, which is
usually enough to tell "the device is ignoring us" from "the datagram never left".

### Recover a token

`tools/adopt_softap.py` automates recovery over a device's setup access point. See
[ADOPTION.md](ADOPTION.md) for the procedure and its constraints.

---

## Common tasks

### Add a device

A new module in `limelight/drivers/`, one import, one test. Full walkthrough in
[DEVICES.md](DEVICES.md).

### Add a capability

1. Add a member to `Capability` in `drivers/base.py`. The string value is public API.
2. Add a default method on `LightDriver` that raises `OperationNotSupported`.
3. Add the field to `LightState` if it reads back, defaulting to `None`.
4. Implement it in drivers that have it, and add the capability to their set.
5. Add an endpoint in `server.py`, guarded with `guard(..., Capability.YOURS)`.
6. Add a control in `web.py` with a matching `data-cap` attribute.
7. Document it in [API.md](API.md) and add a test.

Adding a capability is backwards-compatible: clients ignore values they do not know.

### Add a schedule kind

1. Add it to `KINDS` in `config.py`, and to `SERVICE_DRIVEN_KINDS` if the service drives it.
2. Handle it in `Schedule.describe()`.
3. Handle it in `Scheduler._fire()`.
4. Add it to the `Literal` in `ScheduleBody` in `server.py`.
5. Add it to the `<select>` in `web.py`.
6. Document it in [API.md](API.md), and test `describe()` and `_fire()`.

### Change the API

Read the compatibility promise in [API.md](API.md) first. Adding a field or an endpoint is
fine. Removing or repurposing one is not, within a major version.

### Regenerate the client schema

```bash
limelight serve &
curl -s http://localhost:8765/openapi.json > openapi.json
```

---

## Pitfalls

Constraints that are not obvious from reading the code.

### Do not build the driver at import time

Constructing a driver at module scope makes the HTTP layer untestable, because importing it
then contacts hardware. `create_app()` takes an injected driver and the module-level `app`
is built lazily through a module `__getattr__`. Keep it that way.

### Route handlers stay synchronous

They are `def`, not `async def`, so FastAPI runs them in its thread pool. The driver
beneath blocks on UDP; an `async def` handler would block the event loop instead of a
worker.

### The vendor library's `configure_wifi` is broken on this firmware

`Device.configure_wifi` does `send(...)[0]`, and this firmware answers with a bare
integer, so it raises `TypeError` **after the device has already acted**. Use
`MiioTransport.configure_wifi`, which sends the command directly.

### One `get_prop`, not many

The device is a single-threaded ESP8266 on UDP. Read every property in one call. Nine
separate reads will drop datagrams and be slower.

### Never cache device state

The lamp has a physical touch control. Any cache is stale the moment somebody touches it.

### macOS hides Wi-Fi network names

On recent macOS, a process without Location Services authorization sees every SSID as
`<redacted>`, and `networksetup -setairportnetwork` fails with `-3900`. This is why
adoption asks the user to switch networks by hand rather than doing it automatically. It
is not a bug in the tooling and `sudo` alone does not fix it.

### The setup access point has no gateway

In setup mode the device serves `192.168.4.0/24` and answers on `192.168.4.1`, but
advertises no default route. Deriving the address from the routing table finds nothing.
Probe `.1` directly or sweep the subnet.

---

## Releasing

Versions follow [semantic versioning](https://semver.org/). The API contract in
[API.md](API.md) is what the major number protects.

1. Update `__version__` in `limelight/__init__.py` and `version` in `pyproject.toml`.
   They must match; a test could usefully enforce that.
2. Move the `Unreleased` entries in [CHANGELOG.md](../CHANGELOG.md) under the new version
   with a date.
3. `pytest && ruff check .`
4. Verify against real hardware. The suite cannot prove the protocol still works.
5. Commit, tag `vX.Y.Z`, and push the tag.
6. `python -m build` if publishing a distribution.

Pushing a `v*` tag triggers `.github/workflows/release.yml`, which builds the Android APK
and the Python distribution and attaches both to a GitHub Release. The APK is deliberately
not committed to the repository: at roughly 16 MB per build it would grow the history
without bound.

### What each number means here

| Change | Bump |
|---|---|
| A new driver, endpoint, capability or schedule kind | Minor |
| A bug fix, or a documentation change | Patch |
| Removing or repurposing an API field, or dropping `/api` | Major |
| Raising the Python floor | Minor, or major if it strands a supported platform |
| Raising the `python-miio` cap to 0.6 | Minor at least; verify against hardware first |

---

## Project conventions

**Measure, do not assume.** Every claim about the hardware in this repository came from a
device and says so. If you cannot measure it, mark it unverified.

**Document the traps.** Firmware defects, platform restrictions and library bugs all cost
time to find. Each one found here is written down, with its numbers, so nobody pays twice.

**Secrets stay out of the tree.** The token lives in `~/.config/limelight/config.json` at
mode `0600`. `.gitignore` blocks the obvious filenames. Never put a real token, MAC
address or network name in a commit, a test fixture or a document. Use `0` × 32,
`AA:BB:CC:DD:EE:FF`, and `192.168.1.x`.

**State limitations plainly.** The `service_driven` flag exists because a sunrise that
silently fails when a laptop sleeps is worse than no sunrise at all. When something cannot
be relied on, say so in the API, the interface and the documentation.
