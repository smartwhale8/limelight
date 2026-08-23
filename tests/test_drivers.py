"""Driver behaviour, including the firmware quirk compensation.

The quirk tests are the most valuable in the suite. They encode hardware behaviour that
is not documented anywhere by the vendor and was only found by measurement, so a
regression here would be silent and confusing.
"""

from __future__ import annotations

import pytest

from lamplight.drivers.base import (
    Capability,
    LightState,
    OperationNotSupported,
    get_driver,
    supported_models,
)
from lamplight.drivers.philips_eyecare import PROPS, SCENES, PhilipsEyecareLamp

from .fakes import QUIRK_BRIGHTNESS, FakeTransport

# ------------------------------------------------------------------------- registry

def test_driver_is_registered_under_its_model():
    assert get_driver("philips.light.sread1") is PhilipsEyecareLamp


def test_unknown_model_is_not_registered():
    assert get_driver("acme.light.nonexistent") is None


def test_supported_models_reports_display_name():
    assert supported_models()["philips.light.sread1"] == "Philips Eyecare Smart Lamp 2"


# ---------------------------------------------------------------------------- reads

def test_state_decodes_every_property(driver, transport):
    transport.props.update({"power": "on", "bright": 42, "eyecare": "on",
                            "ambstatus": "on", "ambvalue": 30, "scene_num": 3,
                            "bls": "off", "notifystatus": "on", "dvalue": 12})
    s = driver.state()
    assert (s.on, s.brightness, s.eyecare) == (True, 42, True)
    assert (s.ambient_on, s.ambient_brightness) == (True, 30)
    assert (s.scene, s.scene_name) == (3, "Reading")
    assert (s.night_light, s.reminder, s.sleep_timer_minutes) == (False, True, 12)


def test_state_requests_properties_in_firmware_order(driver, transport):
    driver.state()
    assert transport.sent("get_prop") == [PROPS]


def test_state_as_dict_omits_unsupported_fields():
    # A device reporting nothing but power must not advertise a brightness of None.
    d = LightState(on=True).as_dict()
    assert d == {"on": True}


def test_state_as_dict_keeps_on_when_false():
    assert LightState(on=False).as_dict()["on"] is False


# --------------------------------------------------------------------------- writes

@pytest.mark.parametrize("on,expected", [(True, "on"), (False, "off")])
def test_set_power(driver, transport, on, expected):
    driver.set_power(on)
    assert transport.sent("set_power") == [[expected]]


def test_brightness_is_clamped_to_the_device_range(driver, transport):
    driver.set_brightness(500)
    driver.set_brightness(-7)
    assert transport.sent("set_bright") == [[100], [1]]


def test_set_scene_rejects_out_of_range(driver):
    with pytest.raises(ValueError, match="scene must be one of"):
        driver.set_scene(9)


@pytest.mark.parametrize("number", sorted(SCENES))
def test_every_documented_scene_is_accepted(driver, transport, number):
    driver.set_scene(number)
    assert [number] in transport.sent("set_user_scene")


def test_sleep_timer_never_goes_negative(driver, transport):
    driver.set_sleep_timer(-5)
    assert transport.sent("delay_off") == [[0]]


# ----------------------------------------------------------------- quirk compensation

def test_eyecare_restores_brightness_the_firmware_moved(driver, transport):
    """Quirk 1: set_eyecare resets bright. The driver must put it back."""
    driver.set_brightness(25)
    driver.set_eyecare(True)
    assert transport.props["eyecare"] == "on"
    assert transport.props["bright"] == 25, "brightness should survive enabling eyecare"


def test_sleep_timer_restores_brightness_the_firmware_moved(driver, transport):
    """Quirk 2: delay_off resets bright. The driver must put it back."""
    driver.set_brightness(25)
    driver.set_sleep_timer(30)
    assert transport.props["dvalue"] == 30
    assert transport.props["bright"] == 25, "brightness should survive a sleep timer"


def test_compensation_can_be_disabled_for_protocol_study(transport):
    lamp = PhilipsEyecareLamp(transport, compensate_quirks=False)
    lamp.set_brightness(25)
    lamp.set_eyecare(True)
    assert transport.props["bright"] == QUIRK_BRIGHTNESS


def test_compensation_issues_no_correction_when_firmware_behaves():
    quiet = FakeTransport(quirks=False)
    lamp = PhilipsEyecareLamp(quiet)
    lamp.set_brightness(25)
    quiet.calls.clear()
    lamp.set_eyecare(True)
    # Two reads bracket the call; no corrective write should follow.
    assert quiet.sent("set_bright") == []


# --------------------------------------------------------------------- capabilities

def test_declared_capabilities_match_the_hardware(driver):
    assert driver.capabilities == frozenset({
        Capability.POWER, Capability.BRIGHTNESS, Capability.AMBIENT,
        Capability.AMBIENT_BRIGHTNESS, Capability.EYECARE, Capability.SCENES,
        Capability.NIGHT_LIGHT, Capability.REMINDER, Capability.SLEEP_TIMER,
    })


def test_colour_is_not_claimed(driver):
    """This lamp is white-only; claiming colour would mislead a client."""
    assert not driver.supports(Capability.COLOR)
    with pytest.raises(OperationNotSupported):
        driver.require(Capability.COLOR)


def test_describe_publishes_the_client_contract(driver):
    d = driver.describe()
    assert d["model"] == "philips.light.sread1"
    assert d["brightness_range"] == [1, 100]
    assert d["scenes"]["1"] == "Study"
    assert "eyecare" in d["capabilities"]
