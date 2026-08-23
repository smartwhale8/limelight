"""HTTP service and web interface.

Run with ``limelight serve``, ``python -m limelight.server``, or ``./run.sh``.

API versioning
--------------
The canonical prefix is ``/api/v1``. The same routes are also mounted at ``/api`` for the
0.x web interface; that alias is deprecated and will be removed in 2.0. Native clients
must use ``/api/v1``. Within a major version, fields are only added: none is removed or
given a new meaning. ``docs/API.md`` is the written contract and ``/openapi.json`` is the
machine-readable one.

Capability negotiation
----------------------
``GET /api/v1/device`` publishes the device's capability list. Clients render controls
from that list rather than hard-coding a feature set, which is what lets a second device
type appear without a client update. Calling an unsupported operation returns 400.

Authentication
--------------
Disabled when no key is configured, which keeps a private home setup frictionless. Set
``LIMELIGHT_API_KEY`` or ``server.api_key`` to require ``Authorization: Bearer <key>``
(``X-API-Key`` is also accepted) on everything except ``/api/v1/health``. This is a
shared secret over plain HTTP: it identifies a client on a trusted network and is not a
substitute for a VPN when reaching the service from outside that network.

Construction
------------
:func:`create_app` builds a service around an injected configuration, driver and
scheduler, so tests can exercise every route against a fake transport with no hardware
and no network. The module-level ``app`` is created on first access, which is what
``uvicorn limelight.server:app`` resolves.
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import __version__
from .config import Config, Schedule, default_schedules
from .device import build_driver
from .drivers.base import (
    Capability,
    DeviceCommandError,
    DeviceError,
    DeviceUnreachable,
    LightDriver,
    OperationNotSupported,
)
from .drivers.miio_transport import discover
from .scheduler import Scheduler
from .web import PAGE

log = logging.getLogger("limelight")


# --------------------------------------------------------------------- request bodies

class OnOff(BaseModel):
    """A boolean toggle."""

    on: bool


class Level(BaseModel):
    """A brightness level as a percentage."""

    level: int = Field(ge=1, le=100, description="Brightness percentage")


class SceneBody(BaseModel):
    """A fixed scene selection."""

    number: int = Field(ge=1, le=3, description="Fixed scene number; the device accepts 1 to 3")


class Minutes(BaseModel):
    """A duration in whole minutes, where zero cancels."""

    minutes: int = Field(ge=0, le=600, description="Minutes; 0 cancels")


class SunriseBody(BaseModel):
    """Parameters for a gradual wake-up ramp."""

    duration_min: float = Field(default=20, gt=0, le=600, description="Ramp length in minutes")
    target: int = Field(default=100, ge=1, le=100, description="Final brightness")
    ambient: bool = Field(default=False, description="Also switch the ambient light on")
    scene: int | None = Field(default=None, ge=1, le=3)


class FadeBody(BaseModel):
    """Parameters for a gradual fade to off."""

    duration_min: float = Field(default=30, gt=0, le=600)


class ScheduleBody(BaseModel):
    """A recurring schedule. Supply ``id`` to update an existing one."""

    id: str | None = Field(default=None, description="Omit to create, supply to update")
    name: str = "Untitled"
    kind: Literal["sunrise", "fade_off", "on", "off", "timer"] = "sunrise"
    time: str = Field(default="07:00", pattern=r"^\d{1,2}:\d{2}$")
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4],
                            description="Monday is 0, Sunday is 6")
    enabled: bool = True
    duration_min: int = Field(default=20, ge=0, le=600)
    target_brightness: int = Field(default=100, ge=1, le=100)
    ambient: bool = False
    scene: int | None = Field(default=None, ge=1, le=3)


# ------------------------------------------------------------------------- factory

def create_app(config: Config, driver: LightDriver,
               scheduler: Scheduler | None = None) -> FastAPI:
    """Build the service around an injected device.

    Separating construction from module import is what makes the routes testable: pass a
    driver backed by a fake transport and every endpoint can be exercised offline.
    """
    sched = scheduler or Scheduler(driver, config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        sched.start()
        log.info("limelight %s ready: %s at %s", __version__,
                 driver.display_name, driver.address)
        if not config.server.api_key:
            log.info("authentication is disabled; any host on this network can "
                     "control the device")
        yield
        sched.stop()

    app = FastAPI(
        title="limelight",
        version=__version__,
        summary="Local control of Xiaomi-ecosystem lights over the miIO protocol",
        lifespan=lifespan,
    )
    app.state.config = config
    app.state.driver = driver
    app.state.scheduler = sched

    if config.server.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=config.server.cors_origins,
                           allow_methods=["*"], allow_headers=["*"])

    # ---------------------------------------------------------------------- auth

    def require_api_key(request: Request) -> None:
        """Enforce the shared secret when one is configured.

        Compared with :func:`secrets.compare_digest` so the check cannot be narrowed by
        measuring response time.
        """
        expected = config.server.api_key
        if not expected:
            return
        header = request.headers.get("authorization", "")
        supplied = (header[7:] if header[:7].lower() == "bearer "
                    else request.headers.get("x-api-key", ""))
        if not supplied or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="missing or invalid API key",
                                headers={"WWW-Authenticate": "Bearer"})

    # ------------------------------------------------------------------- helpers

    def guard(fn, capability: Capability | None = None):
        """Run a device call, mapping device failures onto HTTP status codes."""
        try:
            if capability is not None:
                driver.require(capability)
            return {"ok": True, "result": fn()}
        except OperationNotSupported as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DeviceCommandError as exc:
            # The device was reached and refused the request, so this is a client error.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DeviceUnreachable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DeviceError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def manual(reason: str) -> None:
        """Cancel any ramp in progress, because a hand-issued command overrides it."""
        sched.cancel_ramp(reason)

    # -------------------------------------------------------------------- routes

    public = APIRouter(tags=["limelight"])
    api = APIRouter(tags=["limelight"], dependencies=[Depends(require_api_key)])

    @public.get("/health", summary="Liveness and identity; no authentication required")
    def health() -> dict:
        """Left unauthenticated so a client can find and identify the service."""
        return {
            "ok": True,
            "service": "limelight",
            "version": __version__,
            "device_name": config.device.name,
            "model": driver.model,
            "auth_required": bool(config.server.api_key),
        }

    @api.get("/device", summary="Static device description and capability list")
    def device_description() -> dict:
        return {
            **driver.describe(),
            "name": config.device.name,
            "device_id": config.device.device_id,
            "mac": config.device.mac,
        }

    @api.get("/state", summary="Everything needed to render the interface, in one call")
    def get_state() -> dict:
        payload: dict = {
            "device": {
                "name": config.device.name,
                "model": driver.model,
                "display_name": driver.display_name,
                "address": driver.address,
                "device_id": config.device.device_id,
                "capabilities": sorted(c.value for c in driver.capabilities),
                "scenes": {str(k): v for k, v in driver.scenes.items()},
            },
            "ramp": sched.ramp.as_dict(),
            "schedules": [s.as_dict() for s in config.schedules],
            "next_runs": sched.next_runs(),
            "last_error": sched.last_error,
            "version": __version__,
        }
        try:
            payload["state"] = driver.state().as_dict()
            payload["reachable"] = True
        except DeviceError as exc:
            payload["state"] = None
            payload["reachable"] = False
            payload["error"] = str(exc)
        return payload

    @api.get("/info", summary="Raw device self-description, for diagnostics")
    def get_info() -> dict:
        return guard(driver.info)

    @api.post("/discover", summary="Re-locate the device and store its address")
    def rediscover() -> dict:
        found = discover(config.device.device_id, config.device.subnet)
        if found:
            config.device.ip = found[0]["ip"]
            config.save()
        # The token is deliberately stripped: it must never leave via the API.
        return {"found": [{k: v for k, v in f.items() if k != "token"} for f in found],
                "address": driver.address}

    @api.post("/power")
    def set_power(body: OnOff) -> dict:
        manual("power set by hand")
        return guard(lambda: driver.set_power(body.on), Capability.POWER)

    @api.post("/brightness")
    def set_brightness(body: Level) -> dict:
        manual("brightness set by hand")
        return guard(lambda: driver.set_brightness(body.level), Capability.BRIGHTNESS)

    @api.post("/ambient")
    def set_ambient(body: OnOff) -> dict:
        return guard(lambda: driver.set_ambient(body.on), Capability.AMBIENT)

    @api.post("/ambient_brightness")
    def set_ambient_brightness(body: Level) -> dict:
        return guard(lambda: driver.set_ambient_brightness(body.level),
                     Capability.AMBIENT_BRIGHTNESS)

    @api.post("/eyecare")
    def set_eyecare(body: OnOff) -> dict:
        return guard(lambda: driver.set_eyecare(body.on), Capability.EYECARE)

    @api.post("/scene")
    def set_scene(body: SceneBody) -> dict:
        return guard(lambda: driver.set_scene(body.number), Capability.SCENES)

    @api.post("/night_light")
    def set_night_light(body: OnOff) -> dict:
        return guard(lambda: driver.set_night_light(body.on), Capability.NIGHT_LIGHT)

    @api.post("/reminder")
    def set_reminder(body: OnOff) -> dict:
        return guard(lambda: driver.set_reminder(body.on), Capability.REMINDER)

    @api.post("/sleep_timer",
              summary="The device's own countdown; survives this service exiting")
    def set_sleep_timer(body: Minutes) -> dict:
        return guard(lambda: driver.set_sleep_timer(body.minutes), Capability.SLEEP_TIMER)

    @api.post("/sunrise", summary="Start a gradual wake-up ramp now")
    def start_sunrise(body: SunriseBody) -> dict:
        """Service-driven: this stops progressing if the host sleeps."""
        ramp = sched.start_sunrise(body.duration_min, body.target,
                                   ambient=body.ambient or None, scene=body.scene)
        return {"ok": True, "ramp": ramp.as_dict(), "service_driven": True}

    @api.post("/fade_off", summary="Start a gradual fade to off now")
    def start_fade_off(body: FadeBody) -> dict:
        ramp = sched.start_fade_off(body.duration_min)
        return {"ok": True, "ramp": ramp.as_dict(), "service_driven": True}

    @api.post("/cancel_ramp")
    def cancel_ramp() -> dict:
        return {"ok": True, "was_running": sched.cancel_ramp("cancelled by a client")}

    @api.get("/schedules")
    def list_schedules() -> list[dict]:
        return [s.as_dict() for s in config.schedules]

    @api.post("/schedules", summary="Create a schedule, or update one by supplying its id")
    def upsert_schedule(body: ScheduleBody) -> dict:
        fields = body.model_dump()
        sched_id = fields.pop("id", None)
        schedule = Schedule(**fields)
        if sched_id:
            if config.get(sched_id) is None:
                raise HTTPException(status_code=404,
                                    detail=f"no schedule with id {sched_id}")
            schedule.id = sched_id
        try:
            config.upsert(schedule)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "schedule": schedule.as_dict()}

    @api.delete("/schedules/{sched_id}")
    def delete_schedule(sched_id: str) -> dict:
        if not config.delete(sched_id):
            raise HTTPException(status_code=404, detail="no such schedule")
        return {"ok": True}

    # Canonical prefix first, then the deprecated 0.x alias on the same handlers.
    app.include_router(public, prefix="/api/v1")
    app.include_router(api, prefix="/api/v1")
    app.include_router(public, prefix="/api", include_in_schema=False)
    app.include_router(api, prefix="/api", include_in_schema=False)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return PAGE

    return app


# ------------------------------------------------------- module-level app, built lazily

_app: FastAPI | None = None


def build_default_app() -> FastAPI:
    """Construct the service from the stored configuration, contacting the device."""
    config = Config.load()
    if not config.schedules:
        config.schedules = default_schedules()
        config.save()
    if not config.device.token:
        raise SystemExit(
            "No device configured. Adopt one first:\n"
            "  limelight discover\n"
            "  limelight adopt --auto\n"
            "  limelight adopt --ip <address> --token <32 hex characters>\n"
            "See docs/ADOPTION.md for recovering a token from the device."
        )
    driver = build_driver(config.device.ip, config.device.token,
                          model=config.device.model, device_id=config.device.device_id,
                          subnet=config.device.subnet)
    return create_app(config, driver)


def __getattr__(name: str):
    """Build ``app`` on first access, so importing this module stays side-effect free.

    ``uvicorn limelight.server:app`` resolves through here. Tests import
    :func:`create_app` instead and never trigger device contact.
    """
    if name == "app":
        global _app
        if _app is None:
            _app = build_default_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    import argparse

    import uvicorn

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config.load()
    ap = argparse.ArgumentParser(description="Run the limelight service")
    ap.add_argument("--host", default=config.server.host)
    ap.add_argument("--port", type=int, default=config.server.port)
    ap.add_argument("--log-level", default="info")
    args = ap.parse_args()
    uvicorn.run(build_default_app(), host=args.host, port=args.port,
                log_level=args.log_level)


if __name__ == "__main__":
    main()
