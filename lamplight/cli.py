"""Command line interface.

Every subcommand is a single blocking call that exits non-zero on failure, so these are
safe to use from shell scripts, cron, or other automation.

    lamplight discover                       # find miIO devices on the local subnet
    lamplight adopt --auto                   # adopt a device that discloses its token
    lamplight adopt --ip <addr> --token <hex>
    lamplight status
    lamplight on --brightness 60
    lamplight off
    lamplight brightness 35
    lamplight scene 3
    lamplight eyecare on
    lamplight ambient on --level 50
    lamplight timer 45                       # device countdown, survives this process
    lamplight sunrise --minutes 20           # runs in the foreground
    lamplight fade --minutes 30
    lamplight schedules
    lamplight capabilities
    lamplight info
    lamplight serve --port 8765

``discover`` and ``adopt --auto`` are the only subcommands that work before a device has
been configured.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .config import Config, default_schedules
from .device import build_driver
from .drivers.base import DeviceError, LightDriver, supported_models
from .drivers.miio_transport import discover, handshake
from .scheduler import Scheduler


def _driver(cfg: Config) -> LightDriver:
    if not cfg.device.token:
        sys.exit("No device configured. Run 'lamplight discover' or 'lamplight adopt --auto'.")
    return build_driver(cfg.device.ip, cfg.device.token, model=cfg.device.model,
                        device_id=cfg.device.device_id, subnet=cfg.device.subnet)


# ------------------------------------------------------------------------ adoption

def cmd_discover(args, cfg: Config) -> int:
    found = discover(subnet=args.subnet)
    if not found:
        print(f"No miIO devices answered on {args.subnet}0/24.")
        print("If the device is unprovisioned it is broadcasting its own access point;")
        print("see docs/ADOPTION.md.")
        return 1
    for f in found:
        disclosed = "token disclosed" if f.get("token") else "token withheld"
        print(f"  {f['ip']}  device_id={f['device_id']}  ({disclosed})")
    if len(found) == 1 and cfg.device.token:
        cfg.device.ip = found[0]["ip"]
        cfg.device.device_id = found[0]["device_id"]
        cfg.save()
        print(f"Updated the stored address to {found[0]['ip']}.")
    return 0


def cmd_adopt(args, cfg: Config) -> int:
    """Record and verify a device, then store what it reports about itself."""
    ip, token = args.ip, args.token

    if args.auto:
        candidates = [f for f in discover(subnet=args.subnet) if f.get("token")]
        if not candidates:
            print("No device on this subnet disclosed a token.")
            print("Either the device is bound to a vendor account, or it is unprovisioned.")
            print("See docs/ADOPTION.md for recovering a token over its setup access point.")
            return 1
        if len(candidates) > 1:
            print("More than one device disclosed a token; choose one with --ip and --token:")
            for c in candidates:
                print(f"  --ip {c['ip']} --token {c['token']}")
            return 1
        ip, token = candidates[0]["ip"], candidates[0]["token"]
        print(f"Found a device at {ip} that disclosed its token.")

    if not ip or not token:
        sys.exit("Supply --ip and --token, or use --auto.")

    try:
        driver = build_driver(ip, token, subnet=args.subnet)
        info = driver.info()
    except DeviceError as exc:
        sys.exit(f"Could not adopt the device at {ip}: {exc}")

    cfg.device.ip = ip
    cfg.device.token = token
    cfg.device.subnet = args.subnet
    cfg.device.mac = info.get("mac", "")
    cfg.device.model = info.get("model", driver.model)
    if args.name:
        cfg.device.name = args.name
    hs = handshake(ip, tries=3)
    if hs.get("device_id") is not None:
        cfg.device.device_id = hs["device_id"]
    if not cfg.schedules:
        cfg.schedules = default_schedules()
    cfg.save()

    print(json.dumps({
        "adopted": True,
        "name": cfg.device.name,
        "model": cfg.device.model,
        "driver": driver.display_name,
        "device_id": cfg.device.device_id,
        "firmware": info.get("fw_ver"),
        "capabilities": sorted(c.value for c in driver.capabilities),
    }, indent=2))
    return 0


# ---------------------------------------------------------------------------- reads

def cmd_status(args, cfg: Config) -> int:
    driver = _driver(cfg)
    try:
        state = driver.state()
    except DeviceError as exc:
        sys.exit(str(exc))
    if args.json:
        print(json.dumps(state.as_dict(include_raw=args.raw), indent=2))
        return 0
    rows = [
        ("power", "on" if state.on else "off"),
        ("brightness", f"{state.brightness}%" if state.brightness is not None else "-"),
        ("eyecare", _fmt(state.eyecare)),
        ("ambient", f"{_fmt(state.ambient_on)} at {state.ambient_brightness}%"
                    if state.ambient_on is not None else "-"),
        ("scene", f"{state.scene} ({state.scene_name})" if state.scene else "-"),
        ("night light", _fmt(state.night_light)),
        ("fatigue reminder", _fmt(state.reminder)),
        ("sleep timer", f"{state.sleep_timer_minutes} min"
                        if state.sleep_timer_minutes is not None else "-"),
        ("device", f"{driver.display_name} at {driver.address}"),
    ]
    for label, value in rows:
        print(f"  {label:<18} {value}")
    return 0


def _fmt(v: bool | None) -> str:
    return "-" if v is None else ("on" if v else "off")


def cmd_capabilities(args, cfg: Config) -> int:
    driver = _driver(cfg)
    print(json.dumps(driver.describe(), indent=2))
    return 0


def cmd_info(args, cfg: Config) -> int:
    print(json.dumps(_driver(cfg).info(), indent=2))
    return 0


def cmd_models(args, cfg: Config) -> int:
    for model, name in supported_models().items():
        print(f"  {model:<28} {name}")
    return 0


# --------------------------------------------------------------------------- writes

def cmd_on(args, cfg: Config) -> int:
    driver = _driver(cfg)
    driver.turn_on()
    if args.brightness:
        driver.set_brightness(args.brightness)
    print("on" + (f" at {args.brightness}%" if args.brightness else ""))
    return 0


def cmd_off(args, cfg: Config) -> int:
    _driver(cfg).turn_off()
    print("off")
    return 0


def cmd_brightness(args, cfg: Config) -> int:
    _driver(cfg).set_brightness(args.level)
    print(f"brightness {args.level}%")
    return 0


def cmd_scene(args, cfg: Config) -> int:
    driver = _driver(cfg)
    driver.set_scene(args.number)
    print(f"scene {args.number} ({driver.scenes.get(args.number, '')})")
    return 0


def cmd_timer(args, cfg: Config) -> int:
    _driver(cfg).set_sleep_timer(args.minutes)
    print(f"device sleep timer set to {args.minutes} min" if args.minutes
          else "sleep timer cleared")
    return 0


def cmd_eyecare(args, cfg: Config) -> int:
    _driver(cfg).set_eyecare(args.state == "on")
    print(f"eyecare {args.state}")
    return 0


def cmd_ambient(args, cfg: Config) -> int:
    driver = _driver(cfg)
    driver.set_ambient(args.state == "on")
    if args.level:
        driver.set_ambient_brightness(args.level)
    print(f"ambient {args.state}" + (f" at {args.level}%" if args.level else ""))
    return 0


# ---------------------------------------------------------------------------- ramps

def _blocking_ramp(cfg: Config, start_fn, label: str) -> int:
    """Run a ramp in the foreground so the command reflects its real duration."""
    driver = _driver(cfg)
    sched = Scheduler(driver, cfg)
    ramp = start_fn(sched)
    print(f"{label}: {ramp.label}. Press Ctrl-C to stop.")
    try:
        while sched.ramp.active:
            d = sched.ramp.as_dict()
            pct = int((d.get("progress") or 0) * 100)
            mins = (d.get("remaining_s") or 0) // 60
            print(f"\r  {pct:3d}%  {mins} min remaining ", end="", flush=True)
            time.sleep(2)
    except KeyboardInterrupt:
        sched.cancel_ramp("interrupted at the command line")
        print("\n  cancelled")
        return 130
    print("\n  complete")
    return 0


def cmd_sunrise(args, cfg: Config) -> int:
    return _blocking_ramp(cfg, lambda s: s.start_sunrise(
        args.minutes, args.target, ambient=args.ambient or None), "sunrise")


def cmd_fade(args, cfg: Config) -> int:
    return _blocking_ramp(cfg, lambda s: s.start_fade_off(args.minutes), "fade out")


# ------------------------------------------------------------------------ schedules

def cmd_schedules(args, cfg: Config) -> int:
    if not cfg.schedules:
        print("No schedules configured.")
        return 0
    for s in cfg.schedules:
        mark = "on " if s.enabled else "off"
        note = "  (needs the service running)" if s.service_driven else ""
        print(f"  [{mark}] {s.id}  {s.name}")
        print(f"          {s.describe()}{note}")
    return 0


def cmd_serve(args, cfg: Config) -> int:
    """Start the HTTP service. Imported lazily so the CLI does not need FastAPI."""
    import uvicorn

    from .server import build_default_app
    uvicorn.run(build_default_app(), host=args.host, port=args.port,
                log_level=args.log_level)
    return 0


# --------------------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="lamplight", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"lamplight {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("discover", help="find miIO devices on the local subnet")
    p.add_argument("--subnet", default=None, help="/24 prefix including the trailing dot")
    p.set_defaults(fn=cmd_discover)

    p = sub.add_parser("adopt", help="store and verify a device")
    p.add_argument("--ip")
    p.add_argument("--token", help="32 hexadecimal characters")
    p.add_argument("--auto", action="store_true",
                   help="adopt a device on this subnet that discloses its token")
    p.add_argument("--name", help="a label for the device, shown in the interface")
    p.add_argument("--subnet", default=None)
    p.set_defaults(fn=cmd_adopt)

    p = sub.add_parser("status", help="print the current state")
    p.add_argument("--json", action="store_true")
    p.add_argument("--raw", action="store_true", help="with --json, include the raw reply")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("on", help="switch on")
    p.add_argument("--brightness", type=int)
    p.set_defaults(fn=cmd_on)

    sub.add_parser("off", help="switch off").set_defaults(fn=cmd_off)

    p = sub.add_parser("brightness", help="set main brightness")
    p.add_argument("level", type=int)
    p.set_defaults(fn=cmd_brightness)

    p = sub.add_parser("scene", help="select a fixed scene")
    p.add_argument("number", type=int)
    p.set_defaults(fn=cmd_scene)

    p = sub.add_parser("timer", help="device sleep timer in minutes, 0 clears it")
    p.add_argument("minutes", type=int)
    p.set_defaults(fn=cmd_timer)

    p = sub.add_parser("eyecare", help="toggle eyecare mode")
    p.add_argument("state", choices=["on", "off"])
    p.set_defaults(fn=cmd_eyecare)

    p = sub.add_parser("ambient", help="toggle the ambient light")
    p.add_argument("state", choices=["on", "off"])
    p.add_argument("--level", type=int)
    p.set_defaults(fn=cmd_ambient)

    p = sub.add_parser("sunrise", help="gradual wake-up ramp, runs in the foreground")
    p.add_argument("--minutes", type=float, default=20)
    p.add_argument("--target", type=int, default=100)
    p.add_argument("--ambient", action="store_true")
    p.set_defaults(fn=cmd_sunrise)

    p = sub.add_parser("fade", help="gradual fade out then off, runs in the foreground")
    p.add_argument("--minutes", type=float, default=30)
    p.set_defaults(fn=cmd_fade)

    sub.add_parser("schedules", help="list configured schedules").set_defaults(fn=cmd_schedules)
    sub.add_parser("capabilities", help="print the device description").set_defaults(fn=cmd_capabilities)
    sub.add_parser("info", help="print the device's self-description").set_defaults(fn=cmd_info)
    sub.add_parser("models", help="list supported device models").set_defaults(fn=cmd_models)

    p = sub.add_parser("serve", help="run the HTTP service")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--log-level", default="info")
    p.set_defaults(fn=cmd_serve)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    cfg = Config.load()

    # Fall back to the configured values so flags stay optional.
    if getattr(args, "subnet", None) is None and hasattr(args, "subnet"):
        args.subnet = cfg.device.subnet
    if getattr(args, "host", None) is None and hasattr(args, "host"):
        args.host = cfg.server.host
    if getattr(args, "port", None) is None and hasattr(args, "port"):
        args.port = cfg.server.port

    try:
        return args.fn(args, cfg)
    except DeviceError as exc:
        sys.exit(f"Device error: {exc}")
    except ValueError as exc:
        sys.exit(f"Invalid input: {exc}")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
