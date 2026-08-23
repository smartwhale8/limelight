"""Time-driven behaviour: sunrise ramps, fade-outs, and the daily schedule loop.

The device firmware this project targets offers exactly one timed feature, a hard cut-off
after N minutes. Gradual wake-up and gradual wind-down do not exist on the hardware, so
they are produced here by stepping brightness over time.

The consequence is important enough to state plainly, and it is repeated in the README
and surfaced in the API response for every schedule: a ``sunrise`` or ``fade_off`` ramp
progresses **only while this process runs**. If the host sleeps, the ramp stops where it
stood. A ``timer`` schedule uses the device's own countdown and therefore survives the
service exiting. :attr:`limelight.config.Schedule.service_driven` reports which is which.

Threading model
---------------
One daemon thread evaluates schedules every 20 seconds. Each ramp runs in its own daemon
thread and holds no lock between steps, so the interface stays responsive during a
twenty-minute sunrise. All device access is serialised inside the transport.

Any manual command arriving through the API cancels a running ramp, on the assumption
that a person overriding the device by hand means it.

One device interaction is worth knowing: a ramp works by stepping ``set_bright``, and on
the Philips Eyecare lamp that command cancels eyecare mode. A sunrise or fade therefore
switches eyecare off. That is inherent to the hardware, which offers no way to hold both.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Config, Schedule
from .drivers.base import Capability, DeviceError, LightDriver

log = logging.getLogger(__name__)

#: How often a ramp adjusts brightness. Five seconds keeps a 20-minute ramp smooth at
#: 240 steps while staying well clear of flooding the device with datagrams.
STEP_SECONDS = 5.0
MIN_BRIGHTNESS = 1
#: How often the schedule loop wakes. Must be under 60 so a one-minute slot is not missed.
LOOP_SECONDS = 20


@dataclass
class RampStatus:
    """What a ramp is doing, for display and for the API."""

    kind: str = ""
    started_at: float = 0.0
    duration_s: float = 0.0
    start_brightness: int = 0
    target_brightness: int = 0
    active: bool = False
    label: str = ""

    def as_dict(self) -> dict:
        d = {
            "active": self.active,
            "kind": self.kind,
            "label": self.label,
            "start_brightness": self.start_brightness,
            "target_brightness": self.target_brightness,
        }
        if self.active and self.duration_s:
            elapsed = time.time() - self.started_at
            d["progress"] = round(min(1.0, elapsed / self.duration_s), 3)
            d["remaining_s"] = max(0, int(self.duration_s - elapsed))
        return d


class Scheduler:
    """Owns the schedule loop and whichever ramp is in flight."""

    def __init__(self, driver: LightDriver, config: Config):
        self.driver = driver
        self.config = config
        self.ramp = RampStatus()
        self.last_error: str | None = None
        self._cancel = threading.Event()
        self._ramp_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._fired: set[tuple[str, str]] = set()   # (schedule id, "YYYY-MM-DD HH:MM")

    # ---------------------------------------------------------------- ramp control

    def cancel_ramp(self, reason: str = "cancelled") -> bool:
        """Stop any ramp in progress. Returns True when one was running."""
        if self._ramp_thread and self._ramp_thread.is_alive():
            log.info("cancelling ramp: %s", reason)
            self._cancel.set()
            self._ramp_thread.join(timeout=STEP_SECONDS + 2)
            self.ramp.active = False
            return True
        self.ramp.active = False
        return False

    def _run_ramp(self, kind: str, start: int, target: int, duration_s: float, label: str,
                  power_off_at_end: bool, ambient: bool | None, scene: int | None) -> None:
        """Step brightness from ``start`` to ``target``, then optionally power off."""
        try:
            if scene is not None and self.driver.supports(Capability.SCENES):
                self.driver.set_scene(scene)
            if ambient is not None and self.driver.supports(Capability.AMBIENT):
                self.driver.set_ambient(ambient)

            if kind == "sunrise":
                self.driver.set_brightness(start)
                self.driver.turn_on()
            elif not self.driver.state().on:
                log.info("%s: device already off, nothing to fade", label)
                return

            steps = max(1, int(duration_s / STEP_SECONDS))
            for i in range(1, steps + 1):
                if self._cancel.is_set():
                    log.info("%s: cancelled at step %d of %d", label, i, steps)
                    return
                level = max(MIN_BRIGHTNESS, min(100, round(start + (target - start) * (i / steps))))
                try:
                    self.driver.set_brightness(level)
                except DeviceError as exc:
                    # A dropped datagram must not abort a twenty-minute ramp.
                    self.last_error = str(exc)
                    log.warning("%s: step %d failed: %s", label, i, exc)
                if self._cancel.wait(STEP_SECONDS):
                    log.info("%s: cancelled while waiting", label)
                    return

            if power_off_at_end and not self._cancel.is_set():
                self.driver.turn_off()
            log.info("%s: complete", label)
        except Exception as exc:
            self.last_error = repr(exc)
            log.exception("%s failed", label)
        finally:
            self.ramp.active = False

    def _start_ramp(self, kind: str, start: int, target: int, duration_min: float, label: str,
                    power_off_at_end: bool = False, ambient: bool | None = None,
                    scene: int | None = None) -> RampStatus:
        self.cancel_ramp("superseded by a new ramp")
        self._cancel = threading.Event()
        duration_s = max(STEP_SECONDS, duration_min * 60.0)
        self.ramp = RampStatus(kind=kind, started_at=time.time(), duration_s=duration_s,
                               start_brightness=start, target_brightness=target,
                               active=True, label=label)
        self._ramp_thread = threading.Thread(
            target=self._run_ramp,
            args=(kind, start, target, duration_s, label, power_off_at_end, ambient, scene),
            name=f"ramp-{kind}", daemon=True)
        self._ramp_thread.start()
        return self.ramp

    # ------------------------------------------------------------- public actions

    def start_sunrise(self, duration_min: float, target: int = 100,
                      ambient: bool | None = None, scene: int | None = None) -> RampStatus:
        """Wake-up: on at minimum brightness, rising to ``target``."""
        target = max(1, min(100, int(target)))
        return self._start_ramp("sunrise", MIN_BRIGHTNESS, target, duration_min,
                                f"sunrise to {target}% over {duration_min:g} min",
                                ambient=ambient, scene=scene)

    def start_fade_off(self, duration_min: float) -> RampStatus:
        """Wind-down: fade from the present brightness to minimum, then power off."""
        try:
            current = self.driver.state().brightness or 100
        except DeviceError:
            current = 100
        return self._start_ramp("fade_off", current, MIN_BRIGHTNESS, duration_min,
                                f"fade out over {duration_min:g} min", power_off_at_end=True)

    # -------------------------------------------------------------- schedule loop

    def _due(self, sched: Schedule, now: datetime) -> bool:
        """Report whether ``sched`` is due now and has not already fired this minute."""
        if not sched.enabled or now.weekday() not in sched.days:
            return False
        if now.strftime("%H:%M") != sched.time:
            return False
        key = (sched.id, now.strftime("%Y-%m-%d %H:%M"))
        if key in self._fired:
            return False
        self._fired.add(key)
        return True

    def _fire(self, sched: Schedule) -> None:
        log.info("schedule %r firing: %s", sched.name, sched.describe())
        try:
            if sched.kind == "sunrise":
                self.start_sunrise(sched.duration_min, sched.target_brightness,
                                   ambient=sched.ambient or None, scene=sched.scene)
            elif sched.kind == "fade_off":
                self.start_fade_off(sched.duration_min)
            elif sched.kind == "on":
                self.cancel_ramp("a schedule switched the device on")
                if sched.scene is not None and self.driver.supports(Capability.SCENES):
                    self.driver.set_scene(sched.scene)
                self.driver.turn_on()
                if self.driver.supports(Capability.BRIGHTNESS):
                    self.driver.set_brightness(sched.target_brightness)
                if sched.ambient and self.driver.supports(Capability.AMBIENT):
                    self.driver.set_ambient(True)
            elif sched.kind == "off":
                self.cancel_ramp("a schedule switched the device off")
                self.driver.turn_off()
            elif sched.kind == "timer":
                self.driver.set_sleep_timer(sched.duration_min)
        except Exception as exc:
            self.last_error = f"schedule {sched.name!r}: {exc!r}"
            log.exception("schedule %r failed", sched.name)

    def _loop(self) -> None:
        log.info("scheduler running with %d schedule(s)", len(self.config.schedules))
        while not self._stop.is_set():
            now = datetime.now()
            for sched in list(self.config.schedules):
                if self._due(sched, now):
                    self._fire(sched)
            # Discard fire markers older than a day so the set cannot grow without bound.
            cutoff = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
            self._fired = {k for k in self._fired if k[1] >= cutoff}
            self._stop.wait(LOOP_SECONDS)

    def start(self) -> None:
        if self._loop_thread and self._loop_thread.is_alive():
            return
        self._stop.clear()
        self._loop_thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._loop_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.cancel_ramp("service shutting down")

    def next_runs(self, limit: int = 5) -> list[dict]:
        """Upcoming firings across all enabled schedules, soonest first."""
        now = datetime.now().replace(second=0, microsecond=0)
        out: list[dict] = []
        for sched in self.config.schedules:
            if not sched.enabled or not sched.days:
                continue
            hh, mm = (int(x) for x in sched.time.split(":"))
            for ahead in range(0, 8):
                cand = (now + timedelta(days=ahead)).replace(hour=hh, minute=mm)
                if cand > now and cand.weekday() in sched.days:
                    out.append({"id": sched.id, "name": sched.name, "kind": sched.kind,
                                "at": cand.strftime("%Y-%m-%d %H:%M"),
                                "in_minutes": int((cand - now).total_seconds() // 60),
                                "describe": sched.describe(),
                                "service_driven": sched.service_driven})
                    break
        return sorted(out, key=lambda r: r["at"])[:limit]
