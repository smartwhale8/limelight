"""Configuration: validation, persistence, and file permissions.

The permission test matters more than it looks. The configuration file holds the device
token, which is the only credential protecting the device, so a regression that widened
the mode would be a real disclosure.
"""

from __future__ import annotations

import json
import stat

import pytest

from lamplight.config import (
    Config,
    DeviceConfig,
    Schedule,
    config_file,
    default_schedules,
)

# ------------------------------------------------------------------------ validation

def test_time_is_normalised_to_two_digits():
    s = Schedule(time="7:5")
    s.validate()
    assert s.time == "07:05"


@pytest.mark.parametrize("bad", ["", "7", "25:00", "07:60", "ab:cd", "0700"])
def test_invalid_times_are_rejected(bad):
    with pytest.raises(ValueError, match="HH:MM"):
        Schedule(time=bad).validate()


def test_days_are_deduplicated_and_sorted():
    s = Schedule(days=[3, 1, 1, 0])
    s.validate()
    assert s.days == [0, 1, 3]


@pytest.mark.parametrize("bad", [[7], [-1], [0, 9]])
def test_out_of_range_days_are_rejected(bad):
    with pytest.raises(ValueError, match="Monday is 0"):
        Schedule(days=bad).validate()


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="kind must be one of"):
        Schedule(kind="disco").validate()


def test_numeric_fields_are_clamped():
    s = Schedule(duration_min=99999, target_brightness=500)
    s.validate()
    assert (s.duration_min, s.target_brightness) == (600, 100)


def test_scene_must_be_valid_or_absent():
    Schedule(scene=None).validate()
    Schedule(scene=4).validate()
    with pytest.raises(ValueError, match="scene must be"):
        Schedule(scene=5).validate()


# -------------------------------------------------------------- service-driven flag

@pytest.mark.parametrize("kind,expected", [
    ("sunrise", True), ("fade_off", True),
    ("timer", False), ("on", False), ("off", False),
])
def test_service_driven_flag_identifies_ramps(kind, expected):
    """Clients rely on this to warn that a ramp stops when the host sleeps."""
    assert Schedule(kind=kind).service_driven is expected


# ------------------------------------------------------------------------ describing

@pytest.mark.parametrize("kind,fragment", [
    ("sunrise", "ramp to 80% over 15 min"),
    ("fade_off", "fade out over 15 min, then off"),
    ("timer", "set the device cut-off to 15 min"),
    ("on", "on at 80%"),
    ("off", "off"),
])
def test_describe_covers_every_kind(kind, fragment):
    s = Schedule(kind=kind, time="07:00", days=[0], duration_min=15, target_brightness=80)
    assert fragment in s.describe()


def test_describe_collapses_a_full_week():
    s = Schedule(days=list(range(7)))
    assert "every day" in s.describe()


def test_describe_names_individual_days():
    s = Schedule(days=[5, 6])
    assert "Sat, Sun" in s.describe()


# ----------------------------------------------------------------------- persistence

def test_load_returns_defaults_when_no_file_exists():
    cfg = Config.load()
    assert cfg.device.token == ""
    assert cfg.schedules == []


def test_save_then_load_round_trips(sample_schedule):
    cfg = Config(device=DeviceConfig(ip="192.168.1.9", token="a" * 32, device_id=7),
                 schedules=[sample_schedule])
    cfg.save()
    again = Config.load()
    assert again.device.ip == "192.168.1.9"
    assert again.device.device_id == 7
    assert [s.name for s in again.schedules] == ["Wake"]
    assert again.schedules[0].duration_min == 15


def test_saved_file_is_not_world_readable():
    Config(device=DeviceConfig(token="b" * 32)).save()
    mode = config_file().stat().st_mode
    assert not mode & stat.S_IRGRP, "group must not be able to read the token"
    assert not mode & stat.S_IROTH, "others must not be able to read the token"


def test_save_is_atomic_and_leaves_no_temporary_file():
    Config(device=DeviceConfig(token="c" * 32)).save()
    leftovers = list(config_file().parent.glob("*.tmp"))
    assert leftovers == []


def test_environment_key_overrides_the_stored_one(monkeypatch):
    """A process manager can supply the key without writing it to disk."""
    cfg = Config()
    cfg.server.api_key = "from-file"
    cfg.save()
    monkeypatch.setenv("LAMPLIGHT_API_KEY", "from-environment")
    assert Config.load().server.api_key == "from-environment"


def test_stored_schedules_are_validated_on_load():
    cfg = Config(schedules=[Schedule(time="7:5")])
    cfg.save()
    assert Config.load().schedules[0].time == "07:05"


# ------------------------------------------------------------------- schedule store

def test_upsert_appends_then_replaces_by_id(sample_schedule):
    cfg = Config()
    cfg.upsert(sample_schedule)
    assert len(cfg.schedules) == 1

    edited = Schedule(id=sample_schedule.id, name="Renamed", kind="off", time="08:00")
    cfg.upsert(edited)
    assert len(cfg.schedules) == 1, "an existing id must replace, not duplicate"
    assert cfg.schedules[0].name == "Renamed"


def test_upsert_rejects_an_invalid_schedule_without_persisting():
    cfg = Config()
    with pytest.raises(ValueError):
        cfg.upsert(Schedule(time="99:99"))
    assert cfg.schedules == []


def test_delete_reports_whether_anything_was_removed(sample_schedule):
    cfg = Config()
    cfg.upsert(sample_schedule)
    assert cfg.delete(sample_schedule.id) is True
    assert cfg.delete(sample_schedule.id) is False


def test_get_finds_by_id(sample_schedule):
    cfg = Config()
    cfg.upsert(sample_schedule)
    assert cfg.get(sample_schedule.id).name == "Wake"
    assert cfg.get("missing") is None


# -------------------------------------------------------------------------- defaults

def test_default_schedules_are_disabled():
    """Nothing should fire on a fresh install until the user opts in."""
    assert all(not s.enabled for s in default_schedules())


def test_default_schedules_are_valid():
    for s in default_schedules():
        s.validate()


def test_token_is_never_written_outside_the_config_directory(tmp_path):
    Config(device=DeviceConfig(token="d" * 32)).save()
    payload = json.loads(config_file().read_text())
    assert payload["device"]["token"] == "d" * 32
    assert config_file().is_relative_to(tmp_path)
