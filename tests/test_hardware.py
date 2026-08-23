"""Tests that run against a real, adopted device.

Everything else in this suite runs against :class:`tests.fakes.FakeTransport`, which is
what lets CI verify the project with no hardware. That coverage is necessary but not
sufficient: a fake can only reproduce behaviour someone already understood, so it cannot
catch a misunderstanding of the device itself.

This file exists because of one such misunderstanding. Earlier versions documented two
firmware defects, in which ``set_eyecare`` and ``delay_off`` each reset brightness, and
compensated for them by re-applying brightness. The measurements were real, but the
interpretation was wrong, and because ``set_bright`` cancels eyecare the compensation
made the mode impossible to switch on. Every probe that established this was written ad
hoc in a shell and thrown away, so nothing stopped it regressing. These tests are those
probes, kept.

Running them
------------
They are deselected by default and never run in CI, which has no lamp::

    pytest -m hardware              # against the device in ~/.config/limelight
    pytest -m hardware -v           # with the measured values printed

They **change the state of a real lamp** while they run: switching it on, moving
brightness, toggling eyecare and setting a sleep timer. The :func:`preserved_state`
fixture captures everything first and restores it afterwards, including when a test
fails, so the lamp is left as it was found.

They skip rather than fail when no device is configured or the device is unreachable, so
``pytest -m hardware`` on a machine with no lamp is a no-op rather than a false alarm.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from limelight.device import build_driver
from limelight.drivers.base import DeviceError
from limelight.drivers.miio_transport import discover, handshake

pytestmark = pytest.mark.hardware

#: How long to let a mode settle before reading back. Eyecare ramps for about three
#: seconds, so a shorter wait reads an intermediate value and invites the same
#: misreading that produced the bug this file guards against.
SETTLE_SECONDS = 4.0


def _real_config() -> dict | None:
    """Read the actual configuration, bypassing the test isolation in ``conftest``.

    ``conftest.isolated_config`` redirects configuration to a temporary directory for
    every test, which is right for the offline suite and wrong here: these tests need the
    device that is genuinely adopted on this machine.
    """
    path = Path.home() / ".config" / "limelight" / "config.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text()).get("device")
    except (OSError, json.JSONDecodeError):
        return None


@pytest.fixture(scope="module")
def device_config() -> dict:
    cfg = _real_config()
    if not cfg or not cfg.get("token"):
        pytest.skip("no device adopted; run 'limelight adopt' first")
    return cfg


@pytest.fixture(scope="module")
def lamp(device_config):
    """Return a driver for the adopted device, or skip when it cannot be reached."""
    try:
        driver = build_driver(
            device_config["ip"],
            device_config["token"],
            model=device_config.get("model", ""),
            device_id=device_config.get("device_id"),
            subnet=device_config.get("subnet", "192.168.1."),
        )
        driver.state()
    except DeviceError as exc:
        pytest.skip(f"device unreachable: {exc}")
    return driver


@pytest.fixture(autouse=True)
def preserved_state(lamp):
    """Capture the lamp's state, and put it back afterwards however the test ends.

    Without this, a failing test would leave someone's lamp switched on at an arbitrary
    brightness with a sleep timer running.
    """
    before = lamp.state()
    try:
        yield before
    finally:
        # Order matters. Clear the timer first, then restore the mode, then brightness,
        # then power, so nothing re-triggers something already restored.
        for restore in (
            lambda: lamp.set_sleep_timer(before.sleep_timer_minutes or 0),
            lambda: lamp.set_eyecare(bool(before.eyecare)),
            lambda: lamp.set_brightness(before.brightness or 50),
            lambda: lamp.set_ambient(bool(before.ambient_on)),
            lambda: lamp.set_power(before.on),
        ):
            try:
                restore()
                time.sleep(0.6)
            except DeviceError:
                pass          # a lost datagram during cleanup must not mask the result


# --------------------------------------------------------------------- reachability

def test_device_answers_an_unauthenticated_handshake(device_config):
    """Discovery needs no credential, so this separates 'unreachable' from 'wrong token'."""
    result = handshake(device_config["ip"], tries=5)
    assert result.get("device_id") == device_config["device_id"]


def test_device_is_found_by_discovery(device_config):
    """The sweep must find it by device id, which is how a DHCP move is survived."""
    found = discover(device_config["device_id"], device_config.get("subnet", "192.168.1."))
    assert found, "discovery did not find the adopted device on its subnet"
    assert found[0]["device_id"] == device_config["device_id"]


def test_token_authenticates(lamp):
    state = lamp.state()
    assert state.brightness is not None


def test_model_matches_what_was_adopted(lamp, device_config):
    assert lamp.model == device_config["model"]


# --------------------------------------------------------------------- basic control

def test_power_round_trip(lamp):
    lamp.set_power(True)
    time.sleep(1.5)
    assert lamp.state().on is True
    lamp.set_power(False)
    time.sleep(1.5)
    assert lamp.state().on is False


def test_brightness_round_trip(lamp):
    lamp.set_power(True)
    time.sleep(1)
    lamp.set_brightness(35)
    time.sleep(1.5)
    assert lamp.state().brightness == 35


def test_sleep_timer_round_trip(lamp):
    lamp.set_sleep_timer(20)
    time.sleep(1.5)
    assert lamp.state().sleep_timer_minutes == 20
    lamp.set_sleep_timer(0)
    time.sleep(1.5)
    assert lamp.state().sleep_timer_minutes == 0


# ------------------------------------------------- eyecare and brightness coupling

def test_enabling_eyecare_stays_on(lamp):
    """Regression: the driver used to cancel eyecare the instant it was enabled.

    The symptom on the device was distinctive: the base flashed the eye symbol and
    reverted immediately to the brightness markers.
    """
    lamp.set_power(True)
    time.sleep(1)
    lamp.set_eyecare(False)
    time.sleep(1)
    lamp.set_brightness(25)
    time.sleep(1)

    lamp.set_eyecare(True)
    time.sleep(SETTLE_SECONDS)

    assert lamp.state().eyecare is True, (
        "eyecare was cancelled after being enabled. Something is sending a brightness "
        "command after set_eyecare, which this hardware treats as leaving the mode."
    )


def test_eyecare_takes_brightness_to_its_own_level(lamp):
    """Measured behaviour: the mode ramps brightness rather than leaving it alone.

    This is what an earlier version mistook for a firmware defect.
    """
    lamp.set_power(True)
    time.sleep(1)
    lamp.set_eyecare(False)
    time.sleep(1)
    lamp.set_brightness(25)
    time.sleep(1)
    assert lamp.state().brightness == 25

    lamp.set_eyecare(True)
    time.sleep(SETTLE_SECONDS)

    settled = lamp.state().brightness
    assert settled != 25, "eyecare is expected to take control of brightness"
    assert settled > 25, f"expected the mode to raise brightness, saw {settled}"


def test_setting_brightness_cancels_eyecare(lamp):
    """The coupling a client must respect: the two cannot be held together."""
    lamp.set_power(True)
    time.sleep(1)
    lamp.set_eyecare(True)
    time.sleep(SETTLE_SECONDS)
    assert lamp.state().eyecare is True

    lamp.set_brightness(30)
    time.sleep(1.5)

    state = lamp.state()
    assert state.eyecare is False, "set_bright is expected to cancel eyecare"
    assert state.brightness == 30


def test_sleep_timer_does_not_disturb_brightness(lamp):
    """The second 'firmware defect' that turned out not to exist.

    The original observation came from issuing delay_off during the eyecare ramp above and
    crediting that ramp to the wrong command. With eyecare off, delay_off changes nothing
    but the countdown.
    """
    lamp.set_power(True)
    time.sleep(1)
    lamp.set_eyecare(False)
    time.sleep(1)
    lamp.set_brightness(25)
    time.sleep(1.5)

    lamp.set_sleep_timer(30)
    time.sleep(SETTLE_SECONDS)

    state = lamp.state()
    assert state.sleep_timer_minutes == 30
    assert state.brightness == 25, (
        f"delay_off should not move brightness, but it read {state.brightness}"
    )


# ------------------------------------------------------------------------ scenes

def test_only_three_scenes_are_accepted(lamp):
    """Measured: the device takes 1, 2 and 3, and rejects 4 with param error (-5001).

    An earlier version offered four scenes with invented names, so selecting the fourth
    failed against the hardware.
    """
    for number in (1, 2, 3):
        lamp.set_scene(number)
        time.sleep(1.2)
        assert lamp.state().scene == number


def test_scene_four_is_refused_by_the_device(lamp):
    """The driver must reject it locally; this proves the device would too."""
    from limelight.drivers.base import DeviceCommandError

    with pytest.raises(ValueError):
        lamp.set_scene(4)

    # And confirm the device itself refuses, so the local guard is not merely a guess.
    with pytest.raises(DeviceCommandError) as caught:
        lamp.transport.send("set_user_scene", [4])
    assert caught.value.code == -5001


def test_a_rejected_command_is_not_retried(lamp):
    """A permanent device error must fail fast, not be retried as a lost datagram."""
    from limelight.drivers.base import DeviceCommandError

    started = time.monotonic()
    with pytest.raises(DeviceCommandError):
        lamp.transport.send("set_user_scene", [4])
    elapsed = time.monotonic() - started
    assert elapsed < 2.0, (
        f"a rejected command took {elapsed:.1f}s, which suggests it was retried"
    )
