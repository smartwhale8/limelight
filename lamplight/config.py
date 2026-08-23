"""Configuration and persistence.

State lives in ``~/.config/lamplight/config.json``, written with ``0600`` permissions
because it holds the device token, which is the only credential protecting the device on
the local network. The path is overridable with ``LAMPLIGHT_CONFIG`` so tests and
multiple instances do not collide.

Nothing in this file belongs in version control. The repository's ``.gitignore`` excludes
``*.local.json`` and the config directory is outside the tree in any case.

Schedule model
--------------
A schedule fires at a wall-clock time on selected weekdays. ``kind`` decides what runs:

``sunrise``   On at minimum brightness, ramping to ``target_brightness`` over
              ``duration_min``. The wake-up behaviour. No device firmware implements
              this, so it is driven by the service.
``fade_off``  Ramp from the present brightness down to minimum over ``duration_min``,
              then power off. The wind-down behaviour, also service-driven.
``on``        On, applying ``target_brightness`` and optionally ``scene`` and ``ambient``.
``off``       Off immediately.
``timer``     Set the device's own cut-off to ``duration_min`` minutes. Unlike the ramps,
              this survives the service exiting, because the device counts down itself.

Weekdays follow ``datetime.weekday()``: Monday is 0, Sunday is 6.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

KINDS = ("sunrise", "fade_off", "on", "off", "timer")
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

#: Ramp kinds that this service drives and that therefore stop if the host sleeps.
SERVICE_DRIVEN_KINDS = ("sunrise", "fade_off")


def config_dir() -> Path:
    """Return the configuration directory, overridable with ``LAMPLIGHT_CONFIG``."""
    override = os.environ.get("LAMPLIGHT_CONFIG")
    return Path(override).expanduser() if override else Path.home() / ".config" / "lamplight"


def config_file() -> Path:
    return config_dir() / "config.json"


@dataclass
class DeviceConfig:
    """How to reach one device.

    ``device_id`` is the stable identity used to find the device again after DHCP moves
    it, so it matters more than ``ip``. ``subnet`` is the /24 prefix that discovery
    sweeps, including the trailing dot.
    """

    ip: str = ""
    token: str = ""
    device_id: int | None = None
    mac: str = ""
    model: str = ""
    subnet: str = "192.168.1."
    name: str = "Lamp"


@dataclass
class ServerConfig:
    """Service settings. ``api_key`` empty means no authentication is required."""

    host: str = "0.0.0.0"
    port: int = 8765
    api_key: str = ""
    cors_origins: list[str] = field(default_factory=list)


@dataclass
class Schedule:
    """One recurring action. See the module docstring for what each ``kind`` does."""

    name: str = "Untitled"
    kind: str = "sunrise"
    time: str = "07:00"                     # local 24-hour HH:MM
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    enabled: bool = True
    duration_min: int = 20
    target_brightness: int = 100
    ambient: bool = False
    scene: int | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def validate(self) -> None:
        """Normalise and check. Raises ``ValueError`` with a usable message."""
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        hh, sep, mm = self.time.partition(":")
        if not (sep and hh.isdigit() and mm.isdigit()
                and 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError("time must be HH:MM in 24-hour form")
        self.time = f"{int(hh):02d}:{int(mm):02d}"
        if not all(isinstance(d, int) and 0 <= d <= 6 for d in self.days):
            raise ValueError("days must be integers 0..6, where Monday is 0")
        self.days = sorted(set(self.days))
        self.duration_min = max(0, min(600, int(self.duration_min)))
        self.target_brightness = max(1, min(100, int(self.target_brightness)))
        if self.scene is not None and not (1 <= int(self.scene) <= 4):
            raise ValueError("scene must be 1..4 or null")

    @property
    def service_driven(self) -> bool:
        """True when this schedule needs the service running to complete."""
        return self.kind in SERVICE_DRIVEN_KINDS

    def describe(self) -> str:
        days = "every day" if len(self.days) == 7 else ", ".join(WEEKDAY_NAMES[d] for d in self.days)
        if self.kind == "sunrise":
            what = f"ramp to {self.target_brightness}% over {self.duration_min} min"
        elif self.kind == "fade_off":
            what = f"fade out over {self.duration_min} min, then off"
        elif self.kind == "timer":
            what = f"set the device cut-off to {self.duration_min} min"
        elif self.kind == "on":
            what = f"on at {self.target_brightness}%"
        else:
            what = "off"
        return f"{self.time} {days}: {what}"

    def as_dict(self) -> dict:
        return {**asdict(self), "describe": self.describe(),
                "service_driven": self.service_driven}


@dataclass
class Config:
    """The persisted configuration: one device, the service settings, and schedules."""

    device: DeviceConfig = field(default_factory=DeviceConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    schedules: list[Schedule] = field(default_factory=list)

    # ------------------------------------------------------------------- storage

    @classmethod
    def load(cls) -> Config:
        """Read the configuration, returning defaults when the file does not exist."""
        path = config_file()
        if not path.exists():
            return cls()
        data: dict[str, Any] = json.loads(path.read_text())
        cfg = cls(
            device=DeviceConfig(**data.get("device", {})),
            server=ServerConfig(**data.get("server", {})),
            schedules=[Schedule(**s) for s in data.get("schedules", [])],
        )
        for s in cfg.schedules:
            s.validate()
        # An environment variable wins over the file, so a key can be supplied by a
        # process manager without being written to disk.
        cfg.server.api_key = os.environ.get("LAMPLIGHT_API_KEY", cfg.server.api_key)
        return cfg

    def save(self) -> None:
        """Write atomically with restrictive permissions."""
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "device": asdict(self.device),
            "server": asdict(self.server),
            "schedules": [asdict(s) for s in self.schedules],
        }
        target = config_file()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(target)
        os.chmod(target, 0o600)

    # ----------------------------------------------------------------- schedules

    def get(self, sched_id: str) -> Schedule | None:
        return next((s for s in self.schedules if s.id == sched_id), None)

    def upsert(self, sched: Schedule) -> Schedule:
        """Insert or replace by id. Validates before persisting."""
        sched.validate()
        for i, existing in enumerate(self.schedules):
            if existing.id == sched.id:
                self.schedules[i] = sched
                break
        else:
            self.schedules.append(sched)
        self.save()
        return sched

    def delete(self, sched_id: str) -> bool:
        before = len(self.schedules)
        self.schedules = [s for s in self.schedules if s.id != sched_id]
        if len(self.schedules) != before:
            self.save()
            return True
        return False


def default_schedules() -> list[Schedule]:
    """Return starting points for a fresh install, disabled so nothing fires unexpectedly."""
    return [
        Schedule(name="Wake up", kind="sunrise", time="07:00", days=[0, 1, 2, 3, 4],
                 duration_min=20, target_brightness=100, ambient=True, enabled=False),
        Schedule(name="Wind down", kind="fade_off", time="23:00", days=[0, 1, 2, 3, 4, 5, 6],
                 duration_min=30, enabled=False),
    ]
