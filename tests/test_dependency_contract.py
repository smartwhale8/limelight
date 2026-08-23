"""The parts of python-miio this project relies on.

Our coupling to python-miio is deliberately small: two imports and three calls. These
tests assert exactly that surface, so upgrading the library fails here with a clear
message rather than at runtime against a device.

If one of these fails after an upgrade, the fix is confined to
``limelight/drivers/miio_transport.py``. Nothing else in the project imports miio.
"""

from __future__ import annotations

import inspect

import pytest


def test_device_is_importable_from_the_top_level():
    from miio import Device  # noqa: F401


def test_device_exception_is_importable():
    from miio.exceptions import DeviceException  # noqa: F401


def test_device_accepts_an_address_and_token():
    from miio import Device

    params = inspect.signature(Device.__init__).parameters
    assert "ip" in params, "Device no longer takes an ip argument"
    assert "token" in params, "Device no longer takes a token argument"


def test_device_exposes_send():
    from miio import Device

    assert callable(getattr(Device, "send", None)), "Device.send has moved"
    params = inspect.signature(Device.send).parameters
    assert "command" in params
    assert "parameters" in params or "params" in params


def test_device_exposes_info():
    from miio import Device

    assert callable(getattr(Device, "info", None)), "Device.info has moved"


def test_info_result_still_exposes_raw():
    """We read ``info().raw`` to get the device's untranslated self-description.

    Exercised rather than merely introspected, because ``Device.info`` is wrapped by a
    decorator and carries no usable return annotation.
    """
    from miio import DeviceInfo

    sample = {"model": "philips.light.sread1", "fw_ver": "1.2.8", "mac": "AA:BB:CC:DD:EE:FF"}
    info = DeviceInfo(sample)
    assert info.raw == sample, "DeviceInfo.raw no longer returns the untranslated reply"


def test_device_exception_is_an_exception():
    from miio.exceptions import DeviceException

    assert issubclass(DeviceException, Exception)


def test_we_do_not_use_the_broken_configure_wifi_helper():
    """python-miio's Device.configure_wifi raises TypeError against this firmware.

    It indexes the reply as ``send(...)[0]`` while the lamp answers with a bare integer,
    so the exception is raised after the device has already acted. We send
    ``miIO.config_router`` directly instead. This test guards against someone reaching for
    the helper later.
    """
    from limelight.drivers import miio_transport

    source = inspect.getsource(miio_transport)
    assert "configure_wifi(" in source, "our own configure_wifi should exist"
    assert ".configure_wifi(" not in source.replace("def configure_wifi(", ""), (
        "do not call python-miio's Device.configure_wifi; it raises TypeError on this "
        "firmware. Send miIO.config_router directly."
    )


@pytest.mark.parametrize("attribute", ["Device"])
def test_no_other_module_imports_miio(attribute):
    """Only the transport may import miio, so an upgrade has one place to fix."""
    import pathlib

    offenders = []
    for path in pathlib.Path("limelight").rglob("*.py"):
        if path.name == "miio_transport.py":
            continue
        text = path.read_text()
        if "from miio" in text or "import miio" in text:
            offenders.append(str(path))
    assert not offenders, f"these modules import miio directly: {offenders}"


def test_version_matches_pyproject():
    """``__version__`` and the packaging metadata must agree.

    They are declared in two files, so a release that bumps one and forgets the other
    would ship a wheel whose reported version is wrong.
    """
    import pathlib
    import re

    import limelight

    pyproject = pathlib.Path(__file__).parent.parent / "pyproject.toml"
    declared = re.search(r'^version = "([^"]+)"', pyproject.read_text(), re.M)
    assert declared, "no version found in pyproject.toml"
    assert limelight.__version__ == declared.group(1), (
        f"limelight.__version__ is {limelight.__version__} but pyproject.toml "
        f"says {declared.group(1)}"
    )
