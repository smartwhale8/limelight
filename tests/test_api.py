"""HTTP API: the contract a native client depends on.

These tests exist mainly to stop the API drifting. An Android client compiled against
``/api/v1`` cannot be recompiled remotely, so a field that quietly changes name or
meaning is a broken application in someone's hand. Every assertion about a response key
here is deliberate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from limelight.config import Config, DeviceConfig, ServerConfig
from limelight.drivers.philips_eyecare import PhilipsEyecareLamp
from limelight.server import create_app

from .fakes import FakeTransport

V1 = "/api/v1"


# ---------------------------------------------------------------------------- health

def test_health_needs_no_authentication_even_when_a_key_is_set(config, driver):
    """A client must be able to identify the service before it has been paired."""
    config.server.api_key = "secret"
    with TestClient(create_app(config, driver)) as c:
        r = c.get(f"{V1}/health")
        assert r.status_code == 200
        assert r.json()["auth_required"] is True


def test_health_reports_service_identity(client):
    body = client.get(f"{V1}/health").json()
    assert body["service"] == "limelight"
    assert body["model"] == "philips.light.sread1"
    assert body["auth_required"] is False


# -------------------------------------------------------------------- capabilities

def test_device_endpoint_publishes_capabilities(client):
    body = client.get(f"{V1}/device").json()
    assert "eyecare" in body["capabilities"]
    assert body["brightness_range"] == [1, 100]
    assert body["scenes"]["3"] == "Scene 3"
    assert "4" not in body["scenes"]


def test_device_endpoint_does_not_leak_the_token(client):
    """The token must never be reachable through the API."""
    assert "token" not in client.get(f"{V1}/device").text.lower()


def test_state_contains_everything_the_interface_needs(client):
    body = client.get(f"{V1}/state").json()
    for key in ("device", "state", "ramp", "schedules", "next_runs", "reachable", "version"):
        assert key in body, f"{key} is part of the published contract"
    assert body["reachable"] is True
    assert body["state"]["on"] is False


def test_state_reports_unreachable_rather_than_failing(config, driver, transport):
    """A dead device must produce a usable response, not a 500."""
    transport.fail_after = 0
    with TestClient(create_app(config, driver)) as c:
        body = c.get(f"{V1}/state").json()
        assert body["reachable"] is False
        assert body["state"] is None
        assert "error" in body


# --------------------------------------------------------------------------- control

def test_power_on(client, transport):
    assert client.post(f"{V1}/power", json={"on": True}).status_code == 200
    assert transport.props["power"] == "on"


def test_brightness(client, transport):
    client.post(f"{V1}/brightness", json={"level": 33})
    assert transport.props["bright"] == 33


def test_scene(client, transport):
    client.post(f"{V1}/scene", json={"number": 3})
    assert transport.props["scene_num"] == 3


def test_scene_four_is_rejected(client):
    """The device answers param error for scene 4, so the API must not forward it."""
    assert client.post(f"{V1}/scene", json={"number": 4}).status_code == 422


def test_sleep_timer(client, transport):
    client.post(f"{V1}/sleep_timer", json={"minutes": 45})
    assert transport.props["dvalue"] == 45


def test_ambient_and_its_brightness(client, transport):
    client.post(f"{V1}/ambient", json={"on": True})
    client.post(f"{V1}/ambient_brightness", json={"level": 22})
    assert transport.props["ambstatus"] == "on"
    assert transport.props["ambvalue"] == 22


def test_night_light_and_reminder(client, transport):
    client.post(f"{V1}/night_light", json={"on": False})
    client.post(f"{V1}/reminder", json={"on": True})
    assert transport.props["bls"] == "off"
    assert transport.props["notifystatus"] == "on"


# ------------------------------------------------------------------------ validation

@pytest.mark.parametrize("path,payload", [
    ("/brightness", {"level": 0}),
    ("/brightness", {"level": 101}),
    ("/ambient_brightness", {"level": -1}),
    ("/scene", {"number": 0}),
    ("/scene", {"number": 4}),
    ("/scene", {"number": 5}),
    ("/sleep_timer", {"minutes": -1}),
    ("/sleep_timer", {"minutes": 601}),
    ("/sunrise", {"duration_min": 0}),
    ("/sunrise", {"target": 0}),
    ("/fade_off", {"duration_min": -5}),
])
def test_out_of_range_values_are_rejected(client, path, payload):
    assert client.post(V1 + path, json=payload).status_code == 422


def test_missing_body_field_is_rejected(client):
    assert client.post(f"{V1}/power", json={}).status_code == 422


def test_unsupported_capability_returns_400(config, transport):
    """A driver that lacks a capability must produce a clean 400, not a protocol error."""
    class NoTimerLamp(PhilipsEyecareLamp):
        capabilities = frozenset(
            c for c in PhilipsEyecareLamp.capabilities if c.value != "sleep_timer")

    with TestClient(create_app(config, NoTimerLamp(transport))) as c:
        r = c.post(f"{V1}/sleep_timer", json={"minutes": 10})
        assert r.status_code == 400
        assert "sleep_timer" in r.json()["detail"]


def test_unreachable_device_returns_503(config, driver, transport):
    transport.fail_after = 0
    with TestClient(create_app(config, driver)) as c:
        assert c.post(f"{V1}/power", json={"on": True}).status_code == 503


# ------------------------------------------------------------------ authentication

@pytest.fixture
def secured():
    cfg = Config(
        device=DeviceConfig(ip="192.168.1.50", token="0" * 32, model="philips.light.sread1"),
        server=ServerConfig(api_key="correct-horse"),
    )
    lamp = PhilipsEyecareLamp(FakeTransport())
    with TestClient(create_app(cfg, lamp)) as c:
        yield c


def test_protected_route_rejects_a_missing_key(secured):
    r = secured.get(f"{V1}/state")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_protected_route_rejects_a_wrong_key(secured):
    assert secured.get(f"{V1}/state",
                       headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_bearer_header_is_accepted(secured):
    assert secured.get(f"{V1}/state",
                       headers={"Authorization": "Bearer correct-horse"}).status_code == 200


def test_bearer_scheme_is_case_insensitive(secured):
    assert secured.get(f"{V1}/state",
                       headers={"Authorization": "bearer correct-horse"}).status_code == 200


def test_x_api_key_header_is_accepted(secured):
    assert secured.get(f"{V1}/state",
                       headers={"X-API-Key": "correct-horse"}).status_code == 200


# --------------------------------------------------------------------------- ramps

def test_sunrise_starts_and_reports_service_driven(client):
    body = client.post(f"{V1}/sunrise", json={"duration_min": 5, "target": 60}).json()
    assert body["ok"] is True
    assert body["service_driven"] is True, "clients warn the user based on this"
    assert body["ramp"]["active"] is True
    client.post(f"{V1}/cancel_ramp")


def test_cancel_reports_whether_a_ramp_was_running(client):
    client.post(f"{V1}/sunrise", json={"duration_min": 5})
    assert client.post(f"{V1}/cancel_ramp").json()["was_running"] is True
    assert client.post(f"{V1}/cancel_ramp").json()["was_running"] is False


def test_a_manual_command_cancels_a_running_ramp(client):
    """Overriding by hand must win over an in-flight ramp."""
    client.post(f"{V1}/sunrise", json={"duration_min": 20})
    client.post(f"{V1}/brightness", json={"level": 10})
    assert client.get(f"{V1}/state").json()["ramp"]["active"] is False


# ------------------------------------------------------------------------ schedules

def test_create_then_list_a_schedule(client):
    created = client.post(f"{V1}/schedules", json={
        "name": "Morning", "kind": "sunrise", "time": "06:30",
        "days": [0, 1, 2, 3, 4], "duration_min": 25, "target_brightness": 90,
    }).json()["schedule"]
    assert created["describe"] == "06:30 Mon, Tue, Wed, Thu, Fri: ramp to 90% over 25 min"
    assert created["service_driven"] is True

    listed = client.get(f"{V1}/schedules").json()
    assert [s["id"] for s in listed] == [created["id"]]


def test_update_a_schedule_in_place(client):
    created = client.post(f"{V1}/schedules", json={"name": "A", "time": "06:00"}).json()["schedule"]
    client.post(f"{V1}/schedules", json={"id": created["id"], "name": "B", "time": "09:15"})
    listed = client.get(f"{V1}/schedules").json()
    assert len(listed) == 1, "updating must not duplicate"
    assert listed[0]["name"] == "B"
    assert listed[0]["time"] == "09:15"


def test_updating_an_unknown_id_returns_404(client):
    r = client.post(f"{V1}/schedules", json={"id": "deadbeef", "name": "X"})
    assert r.status_code == 404


def test_delete_a_schedule(client):
    created = client.post(f"{V1}/schedules", json={"name": "Bye"}).json()["schedule"]
    assert client.delete(f"{V1}/schedules/{created['id']}").status_code == 200
    assert client.get(f"{V1}/schedules").json() == []


def test_deleting_an_unknown_schedule_returns_404(client):
    assert client.delete(f"{V1}/schedules/nope").status_code == 404


def test_malformed_schedule_time_is_rejected_by_shape(client):
    """A value that is not HH:MM at all fails the request schema, giving 422."""
    assert client.post(f"{V1}/schedules", json={"time": "morning"}).status_code == 422


def test_out_of_range_schedule_time_is_rejected_by_validation(client):
    """``99:99`` has the right shape, so it is caught by domain validation, giving 400.

    The split is deliberate and consistent: malformed input is 422, well-formed but
    invalid input is 400. Clients can rely on that distinction.
    """
    r = client.post(f"{V1}/schedules", json={"time": "99:99"})
    assert r.status_code == 400
    assert "HH:MM" in r.json()["detail"]


def test_schedule_day_out_of_range_is_rejected(client):
    r = client.post(f"{V1}/schedules", json={"time": "07:00", "days": [9]})
    assert r.status_code == 400
    assert "Monday is 0" in r.json()["detail"]


# ------------------------------------------------------------------ versioning

def test_the_deprecated_unversioned_alias_still_works(client):
    """The 0.x web interface used /api; it must not break until 2.0."""
    assert client.get("/api/state").status_code == 200


def test_only_the_versioned_prefix_is_published_in_the_schema(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert any(p.startswith("/api/v1/") for p in paths)
    assert not any(p == "/api/state" for p in paths)


def test_openapi_schema_is_served_for_client_generation(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "limelight"
    assert f"{V1}/state" in schema["paths"]


def test_index_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Limelight" in r.text
    assert "/api/v1" in r.text, "the page must call the versioned API"


# ------------------------------------------------------------------------ discovery

def test_discover_never_returns_a_token(client, monkeypatch):
    monkeypatch.setattr("limelight.server.discover",
                        lambda *a, **k: [{"ip": "192.168.1.50", "device_id": 1,
                                          "token": "s" * 32}])
    body = client.post(f"{V1}/discover").json()
    assert body["found"] == [{"ip": "192.168.1.50", "device_id": 1}]
    assert "s" * 32 not in str(body)
