"""Scheduler: ramp stepping, cancellation, due-time evaluation, and next-run projection.

Ramps are driven by wall-clock waits, so the step interval is shortened to keep the suite
fast. That is a legitimate substitution: the arithmetic under test is the interpolation
and the cancellation, not the sleeping.
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

from lamplight.config import Schedule
from lamplight.scheduler import MIN_BRIGHTNESS, Scheduler


@pytest.fixture(autouse=True)
def fast_ramps(monkeypatch):
    """Shorten the step interval so a whole ramp completes in milliseconds."""
    monkeypatch.setattr("lamplight.scheduler.STEP_SECONDS", 0.01)


def wait_for_ramp(sched: Scheduler, timeout: float = 5.0) -> None:
    end = time.time() + timeout
    while sched.ramp.active and time.time() < end:
        time.sleep(0.01)
    assert not sched.ramp.active, "ramp did not finish within the timeout"


# ----------------------------------------------------------------------- sunrise

def test_sunrise_switches_on_and_reaches_the_target(scheduler, transport):
    scheduler.start_sunrise(duration_min=0.01, target=80)
    wait_for_ramp(scheduler)
    assert transport.props["power"] == "on"
    assert transport.props["bright"] == 80


def test_sunrise_starts_from_minimum_brightness(scheduler, transport):
    scheduler.start_sunrise(duration_min=0.01, target=90)
    wait_for_ramp(scheduler)
    first = transport.sent("set_bright")[0]
    assert first == [MIN_BRIGHTNESS]


def test_sunrise_brightness_increases_monotonically(scheduler, transport):
    scheduler.start_sunrise(duration_min=0.02, target=100)
    wait_for_ramp(scheduler)
    levels = [p[0] for p in transport.sent("set_bright")]
    assert levels == sorted(levels), "a sunrise must never dim part-way through"
    assert levels[-1] == 100


def test_sunrise_can_enable_ambient_and_select_a_scene(scheduler, transport):
    scheduler.start_sunrise(duration_min=0.01, target=50, ambient=True, scene=2)
    wait_for_ramp(scheduler)
    assert transport.props["ambstatus"] == "on"
    assert transport.props["scene_num"] == 2


def test_sunrise_target_is_clamped(scheduler, transport):
    scheduler.start_sunrise(duration_min=0.01, target=999)
    wait_for_ramp(scheduler)
    assert transport.props["bright"] == 100


# ---------------------------------------------------------------------- fade off

def test_fade_off_dims_then_powers_off(scheduler, transport):
    transport.props.update({"power": "on", "bright": 90})
    scheduler.start_fade_off(duration_min=0.01)
    wait_for_ramp(scheduler)
    levels = [p[0] for p in transport.sent("set_bright")]
    assert levels == sorted(levels, reverse=True), "a fade must never brighten"
    assert transport.props["power"] == "off"


def test_fade_off_does_nothing_when_already_off(scheduler, transport):
    transport.props["power"] = "off"
    transport.calls.clear()
    scheduler.start_fade_off(duration_min=0.01)
    wait_for_ramp(scheduler)
    assert transport.sent("set_bright") == []
    assert transport.sent("set_power") == []


# -------------------------------------------------------------------- cancellation

def test_cancel_stops_a_ramp_before_it_completes(scheduler, transport):
    scheduler.start_sunrise(duration_min=10, target=100)
    time.sleep(0.05)
    assert scheduler.cancel_ramp("test") is True
    assert not scheduler.ramp.active
    assert transport.props["bright"] < 100


def test_cancel_reports_false_when_nothing_is_running(scheduler):
    assert scheduler.cancel_ramp("test") is False


def test_a_new_ramp_supersedes_the_running_one(scheduler, transport):
    scheduler.start_sunrise(duration_min=10, target=100)
    time.sleep(0.03)
    scheduler.start_sunrise(duration_min=0.01, target=40)
    wait_for_ramp(scheduler)
    assert transport.props["bright"] == 40


def test_cancelled_fade_does_not_power_off(scheduler, transport):
    transport.props.update({"power": "on", "bright": 100})
    scheduler.start_fade_off(duration_min=10)
    time.sleep(0.05)
    scheduler.cancel_ramp("test")
    assert transport.props["power"] == "on", "cancelling must not complete the fade"


# ------------------------------------------------------------------ error tolerance

def test_a_dropped_command_does_not_abort_the_ramp(driver, config, transport):
    """One lost datagram must not end a twenty-minute sunrise."""
    sched = Scheduler(driver, config)
    transport.fail_after = 4
    sched.start_sunrise(duration_min=0.01, target=100)
    wait_for_ramp(sched)
    assert sched.last_error is not None
    assert not sched.ramp.active, "the ramp thread must exit cleanly, not hang"


# ------------------------------------------------------------------ due evaluation

def test_schedule_is_due_at_its_time_on_a_selected_day(scheduler):
    monday_seven = datetime(2026, 8, 24, 7, 0)      # a Monday
    sched = Schedule(time="07:00", days=[0], enabled=True)
    assert scheduler._due(sched, monday_seven) is True


def test_schedule_fires_only_once_per_minute(scheduler):
    monday_seven = datetime(2026, 8, 24, 7, 0)
    sched = Schedule(time="07:00", days=[0], enabled=True)
    assert scheduler._due(sched, monday_seven) is True
    assert scheduler._due(sched, monday_seven) is False, "must not fire twice in a minute"


def test_disabled_schedule_never_fires(scheduler):
    sched = Schedule(time="07:00", days=[0], enabled=False)
    assert scheduler._due(sched, datetime(2026, 8, 24, 7, 0)) is False


def test_schedule_does_not_fire_on_an_unselected_day(scheduler):
    sched = Schedule(time="07:00", days=[5, 6], enabled=True)
    assert scheduler._due(sched, datetime(2026, 8, 24, 7, 0)) is False   # Monday


def test_schedule_does_not_fire_at_the_wrong_minute(scheduler):
    sched = Schedule(time="07:00", days=[0], enabled=True)
    assert scheduler._due(sched, datetime(2026, 8, 24, 7, 1)) is False


# --------------------------------------------------------------------- projection

def test_next_runs_lists_enabled_schedules_soonest_first(scheduler, config):
    config.schedules = [
        Schedule(name="Later", time="23:00", days=list(range(7)), enabled=True),
        Schedule(name="Sooner", time="00:01", days=list(range(7)), enabled=True),
    ]
    runs = scheduler.next_runs()
    assert len(runs) == 2
    assert runs[0]["at"] <= runs[1]["at"]


def test_next_runs_omits_disabled_schedules(scheduler, config):
    config.schedules = [Schedule(name="Off", days=list(range(7)), enabled=False)]
    assert scheduler.next_runs() == []


def test_next_runs_marks_service_driven_schedules(scheduler, config):
    config.schedules = [Schedule(name="Wake", kind="sunrise", days=list(range(7)),
                                 enabled=True)]
    assert scheduler.next_runs()[0]["service_driven"] is True


def test_next_runs_respects_the_limit(scheduler, config):
    config.schedules = [
        Schedule(name=f"S{i}", time=f"{i:02d}:00", days=list(range(7)), enabled=True)
        for i in range(6)
    ]
    assert len(scheduler.next_runs(limit=3)) == 3


# ------------------------------------------------------------------ firing schedules

def test_firing_a_timer_schedule_uses_the_device_countdown(scheduler, transport):
    scheduler._fire(Schedule(kind="timer", duration_min=25))
    assert transport.sent("delay_off") == [[25]]


def test_firing_an_on_schedule_applies_brightness(scheduler, transport):
    scheduler._fire(Schedule(kind="on", target_brightness=65))
    assert transport.props["power"] == "on"
    assert transport.props["bright"] == 65


def test_firing_an_off_schedule_powers_down(scheduler, transport):
    transport.props["power"] = "on"
    scheduler._fire(Schedule(kind="off"))
    assert transport.props["power"] == "off"


def test_a_failing_schedule_is_recorded_and_does_not_raise(scheduler, transport):
    transport.fail_after = 0
    scheduler._fire(Schedule(kind="off"))
    assert scheduler.last_error is not None
