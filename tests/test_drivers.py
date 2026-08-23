"""Driver behaviour, including the coupling between eyecare mode and brightness.

The eyecare tests are the most valuable in the suite. They encode hardware behaviour found
only by measurement, and one of them is a regression test for a real bug: an earlier driver
re-applied brightness after enabling eyecare, which cancelled the mode, so eyecare could
not be switched on at all.
"""

from __future__ import annotations

import pytest

from limelight.drivers.base import (
    Capability,
    LightState,
    OperationNotSupported,
    get_driver,
    supported_models,
)
from limelight.drivers.philips_eyecare import PROPS, SCENES, PhilipsEyecareLamp

from .fakes import EYECARE_BRIGHTNESS

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
    assert (s.scene, s.scene_name) == (3, "Scene 3")
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


@pytest.mark.parametrize("bad", [0, 4, 9])
def test_set_scene_rejects_out_of_range(driver, bad):
    """Measured: the device accepts 1 to 3 and answers param error (-5001) otherwise."""
    with pytest.raises(ValueError, match="scene must be one of"):
        driver.set_scene(bad)


@pytest.mark.parametrize("number", sorted(SCENES))
def test_every_documented_scene_is_accepted(driver, transport, number):
    driver.set_scene(number)
    assert [number] in transport.sent("set_user_scene")


def test_sleep_timer_never_goes_negative(driver, transport):
    driver.set_sleep_timer(-5)
    assert transport.sent("delay_off") == [[0]]


# ------------------------------------------------- eyecare and brightness are coupled

def test_enabling_eyecare_does_not_immediately_cancel_it(driver, transport):
    """Regression: an earlier driver re-applied brightness and switched eyecare off.

    Enabling eyecare made the lamp's base flash the eye symbol and revert instantly to the
    brightness markers, because the corrective ``set_bright`` cancelled the mode.
    """
    driver.set_brightness(25)
    driver.set_eyecare(True)
    assert transport.props["eyecare"] == "on", "eyecare must stay on after being enabled"


def test_enabling_eyecare_sends_no_brightness_command(driver, transport):
    """The mode owns brightness; sending one would cancel it."""
    driver.set_brightness(25)
    transport.calls.clear()
    driver.set_eyecare(True)
    assert transport.sent("set_bright") == [], (
        "no brightness command may follow set_eyecare; it would cancel the mode"
    )


def test_eyecare_takes_control_of_brightness(driver, transport):
    """Measured on the hardware: the mode ramps to its own level, 25 to 53 to 70."""
    driver.set_brightness(25)
    driver.set_eyecare(True)
    assert transport.props["bright"] == EYECARE_BRIGHTNESS
    assert driver.state().brightness == EYECARE_BRIGHTNESS


def test_setting_brightness_cancels_eyecare(driver, transport):
    """Device behaviour a client must respect: the two cannot be held together."""
    driver.set_eyecare(True)
    assert transport.props["eyecare"] == "on"
    driver.set_brightness(30)
    assert transport.props["eyecare"] == "off", "set_bright cancels eyecare on this device"
    assert transport.props["bright"] == 30


def test_sleep_timer_disturbs_nothing_else(driver, transport):
    """delay_off does not touch brightness, contrary to an earlier misreading."""
    driver.set_brightness(25)
    transport.calls.clear()
    driver.set_sleep_timer(30)
    assert transport.props["dvalue"] == 30
    assert transport.props["bright"] == 25
    assert transport.sent("set_bright") == [], "no corrective write should follow delay_off"


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
    assert d["scenes"]["1"] == "Scene 1"
    assert "4" not in d["scenes"], "the device rejects scene 4 with param error"
    assert "eyecare" in d["capabilities"]
