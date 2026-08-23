"""Shared fixtures.

Every fixture keeps the suite off the network and out of the real configuration
directory. ``LAMPLIGHT_CONFIG`` is redirected to a temporary path for each test, so a run
can never read or overwrite a real device token.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lamplight.config import Config, DeviceConfig, Schedule, ServerConfig
from lamplight.drivers.philips_eyecare import PhilipsEyecareLamp
from lamplight.scheduler import Scheduler
from lamplight.server import create_app

from .fakes import FakeTransport


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point configuration at a temporary directory for the duration of each test."""
    monkeypatch.setenv("LAMPLIGHT_CONFIG", str(tmp_path / "config"))
    monkeypatch.delenv("LAMPLIGHT_API_KEY", raising=False)
    return tmp_path / "config"


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def driver(transport):
    return PhilipsEyecareLamp(transport)


@pytest.fixture
def config():
    return Config(
        device=DeviceConfig(ip="192.168.1.50", token="0" * 32, device_id=1234,
                            model="philips.light.sread1", name="Test Lamp",
                            subnet="192.168.1."),
        server=ServerConfig(),
        schedules=[],
    )


@pytest.fixture
def scheduler(driver, config):
    """Return a scheduler whose loop is never started, so tests stay deterministic."""
    return Scheduler(driver, config)


@pytest.fixture
def client(config, driver, scheduler):
    """Return a test client over the real routes, backed by the fake transport."""
    app = create_app(config, driver, scheduler)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_schedule():
    return Schedule(name="Wake", kind="sunrise", time="07:00", days=[0, 1, 2],
                    duration_min=15, target_brightness=80)
