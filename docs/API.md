# HTTP API

The contract for clients: the web interface, the planned Android application, and anything
else you write. Every example below is a real captured response, not an illustration.

- **Base URL** `http://<host>:8765`
- **Canonical prefix** `/api/v1`
- **Machine-readable schema** `GET /openapi.json`
- **Interactive documentation** `GET /docs`

## Compatibility promise

Within a major version:

- No field is removed.
- No field changes type or meaning.
- New fields may be added, so parse permissively and ignore what you do not recognise.
- New endpoints may be added.
- New `capabilities` values may appear, so treat the list as open and ignore unknown
  entries rather than failing.

A breaking change means `/api/v2`, served alongside v1 for at least one release.

The unversioned `/api/...` prefix also works, but it exists only for the 0.x web interface
and will be removed in 2.0. **Native clients must use `/api/v1`.**

## Authentication

Off when no key is configured. When `LIMELIGHT_API_KEY` or `server.api_key` is set, every
endpoint except `/api/v1/health` requires one of:

```http
Authorization: Bearer <key>
X-API-Key: <key>
```

The scheme name is case-insensitive. A missing or wrong key returns `401` with a
`WWW-Authenticate: Bearer` header.

Call `/api/v1/health` first to learn whether a key is needed. That endpoint is
deliberately unauthenticated so a client can find and identify a service before pairing.

## Error model

| Status | Meaning | `detail` shape |
|---|---|---|
| `400` | Well-formed but invalid, or an unsupported capability | A string |
| `401` | Missing or invalid API key | A string |
| `404` | No such schedule | A string |
| `422` | Malformed request body | FastAPI's validation array |
| `502` | The device answered with an error | A string |
| `503` | The device is unreachable after retries | A string |

The `400` and `422` split is deliberate and stable. Malformed input, such as
`{"time": "morning"}`, fails the request schema and gives `422`. Well-formed but invalid
input, such as `{"time": "99:99"}`, reaches domain validation and gives `400` with a
readable message. Show `400` detail strings to users; `422` indicates a client bug.

```json
// 400
{"detail": "time must be HH:MM in 24-hour form"}
```

```json
// 422
{"detail": [{"type": "less_than_equal", "loc": ["body", "level"],
             "msg": "Input should be less than or equal to 100",
             "input": 150, "ctx": {"le": 100}}]}
```

An unreachable device does **not** make `GET /api/v1/state` fail. It returns `200` with
`reachable: false` and `state: null`, so a client can render a degraded view rather than an
error screen. Write commands to an unreachable device return `503`.

---

## Endpoints

### `GET /api/v1/health`

Liveness and identity. No authentication.

```json
{
  "ok": true,
  "service": "limelight",
  "version": "1.0.0",
  "device_name": "Desk lamp",
  "model": "philips.light.sread1",
  "auth_required": false
}
```

Use `service == "limelight"` to confirm what you have found when scanning a network.

### `GET /api/v1/device`

Static description. Poll this once per session, not per refresh.

```json
{
  "model": "philips.light.sread1",
  "display_name": "Philips Eyecare Smart Lamp 2",
  "capabilities": ["ambient", "ambient_brightness", "brightness", "eyecare",
                   "night_light", "power", "reminder", "scenes", "sleep_timer"],
  "scenes": {"1": "Study", "2": "Office", "3": "Reading", "4": "Bedtime"},
  "brightness_range": [1, 100],
  "address": "192.168.1.42",
  "name": "Desk lamp",
  "device_id": 12345678,
  "mac": "AA:BB:CC:DD:EE:FF"
}
```

**Build your interface from `capabilities`.** Do not hard-code a feature set. A device
without `ambient` should show no ambient control, and this is the mechanism by which a
future device works with an unchanged client.

Note that `scenes` keys are **strings**, because JSON object keys always are.

The token is never present in any response.

### `GET /api/v1/state`

Everything needed for one screen refresh, in a single call. Poll every 2 to 5 seconds
while your interface is in the foreground.

```json
{
  "device": {
    "name": "Desk lamp",
    "model": "philips.light.sread1",
    "display_name": "Philips Eyecare Smart Lamp 2",
    "address": "192.168.1.42",
    "device_id": 12345678,
    "capabilities": ["ambient", "ambient_brightness", "brightness", "eyecare",
                     "night_light", "power", "reminder", "scenes", "sleep_timer"],
    "scenes": {"1": "Study", "2": "Office", "3": "Reading", "4": "Bedtime"}
  },
  "ramp": {
    "active": false, "kind": "", "label": "",
    "start_brightness": 0, "target_brightness": 0
  },
  "schedules": [ /* as in GET /schedules */ ],
  "next_runs": [
    {
      "id": "fb4c99e9", "name": "Wake up", "kind": "sunrise",
      "at": "2026-08-24 07:00", "in_minutes": 1021,
      "describe": "07:00 Mon, Tue, Wed, Thu, Fri: ramp to 100% over 20 min",
      "service_driven": true
    }
  ],
  "last_error": null,
  "version": "1.0.0",
  "state": {
    "on": true, "brightness": 70,
    "ambient_on": false, "ambient_brightness": 41,
    "eyecare": false, "scene": 1, "scene_name": "Study",
    "night_light": true, "reminder": false, "sleep_timer_minutes": 0
  },
  "reachable": true
}
```

Two details that will bite a client author:

1. **`state` omits unsupported fields entirely.** Only `on` is guaranteed. Treat an absent
   key as "this device has no such feature", and check `capabilities` rather than probing
   for keys.
2. **`state` is `null` when `reachable` is `false`.** Check `reachable` before reading it.

`ramp.progress` and `ramp.remaining_s` appear **only while `active` is true**.

`at` in `next_runs` is local time on the server, formatted `YYYY-MM-DD HH:MM`, with no
timezone. It is a display string. Use `in_minutes` for arithmetic.

### Control endpoints

All take `POST` with a JSON body and return `{"ok": true, "result": ["ok"]}`.

| Endpoint | Body | Capability required |
|---|---|---|
| `/api/v1/power` | `{"on": true}` | `power` |
| `/api/v1/brightness` | `{"level": 1..100}` | `brightness` |
| `/api/v1/ambient` | `{"on": true}` | `ambient` |
| `/api/v1/ambient_brightness` | `{"level": 1..100}` | `ambient_brightness` |
| `/api/v1/eyecare` | `{"on": true}` | `eyecare` |
| `/api/v1/scene` | `{"number": 1..4}` | `scenes` |
| `/api/v1/night_light` | `{"on": true}` | `night_light` |
| `/api/v1/reminder` | `{"on": true}` | `reminder` |
| `/api/v1/sleep_timer` | `{"minutes": 0..600}` | `sleep_timer` |

Calling one whose capability the device lacks returns `400`.

`/api/v1/power` and `/api/v1/brightness` **cancel any running ramp**, on the principle
that a person adjusting the device by hand overrides an automatic sequence. The other
endpoints do not.

`sleep_timer` sets the **device's own** countdown. It keeps running if limelight stops.
`0` cancels it.

### `POST /api/v1/sunrise`

Start a gradual brightness ramp now.

```json
{"duration_min": 20, "target": 100, "ambient": false, "scene": null}
```

```json
{
  "ok": true,
  "ramp": {"active": true, "kind": "sunrise",
           "label": "sunrise to 100% over 20 min",
           "start_brightness": 1, "target_brightness": 100,
           "progress": 0.0, "remaining_s": 1199},
  "service_driven": true
}
```

`service_driven: true` is not decoration. It means the ramp is produced by the server
stepping brightness, so it **stops if the server stops or the host sleeps**. A client
offering this as an alarm should say so.

### `POST /api/v1/fade_off`

```json
{"duration_min": 30}
```

Ramps from the present brightness down to 1%, then powers off. Also `service_driven`. Does
nothing if the device is already off.

### `POST /api/v1/cancel_ramp`

```json
{"ok": true, "was_running": true}
```

### `GET /api/v1/schedules`

```json
[
  {
    "name": "Wake up",
    "kind": "sunrise",
    "time": "07:00",
    "days": [0, 1, 2, 3, 4],
    "enabled": true,
    "duration_min": 20,
    "target_brightness": 100,
    "ambient": true,
    "scene": null,
    "id": "fb4c99e9",
    "describe": "07:00 Mon, Tue, Wed, Thu, Fri: ramp to 100% over 20 min",
    "service_driven": true
  }
]
```

`days` uses **Monday as 0** and Sunday as 6, matching Python's `datetime.weekday()`. This
differs from `java.time.DayOfWeek`, where Monday is 1, and from `java.util.Calendar`, where
Sunday is 1. Convert carefully.

`describe` is a server-rendered English summary, provided so simple clients need no
formatting logic. It is not localised; build your own string from the fields if you need
another language.

### `POST /api/v1/schedules`

Creates when `id` is absent, updates when present. An unknown `id` returns `404`.

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | string or null | — | Supply to update |
| `name` | string | `"Untitled"` | |
| `kind` | enum | `"sunrise"` | `sunrise`, `fade_off`, `on`, `off`, `timer` |
| `time` | `"HH:MM"` | `"07:00"` | Server local time, 24-hour |
| `days` | int array | `[0,1,2,3,4]` | Monday is 0 |
| `enabled` | bool | `true` | |
| `duration_min` | int | `20` | 0 to 600 |
| `target_brightness` | int | `100` | 1 to 100 |
| `ambient` | bool | `false` | |
| `scene` | int or null | `null` | 1 to 4 |

| `kind` | Behaviour | Survives the server stopping |
|---|---|---|
| `sunrise` | On at 1%, ramping to `target_brightness` over `duration_min` | No |
| `fade_off` | Ramp down to 1% over `duration_min`, then off | No |
| `on` | On, applying `target_brightness`, and `scene` and `ambient` if given | Yes, it is instant |
| `off` | Off | Yes, it is instant |
| `timer` | Set the device countdown to `duration_min` | **Yes**, the device tracks it |

To toggle a schedule, send the object back with `enabled` flipped and its `id` intact.

### `DELETE /api/v1/schedules/{id}`

`{"ok": true}`, or `404`.

### `GET /api/v1/info`

The device's raw self-description, for diagnostics. Shape varies by firmware; do not build
an interface on it. On this firmware it includes the token, so **do not log or display this
response**.

### `POST /api/v1/discover`

Re-locate the device on the subnet and store its new address. Useful after a DHCP change.
Tokens are stripped from the result.

```json
{"found": [{"ip": "192.168.1.42", "device_id": 12345678}], "address": "192.168.1.42"}
```

Takes several seconds, since it sweeps a /24.

---

## Notes for the Android client

**Generate, do not hand-write.** `GET /openapi.json` feeds
[openapi-generator](https://openapi-generator.tech/) directly:

```bash
openapi-generator generate -i http://<host>:8765/openapi.json \
  -g kotlin -o ./client --additional-properties=library=jvm-retrofit2
```

The FastAPI models carry descriptions, so the generated Kotlin arrives with documentation
on each field.

**Plain HTTP.** The service serves HTTP, not HTTPS. Android blocks cleartext by default,
so a client needs a `network_security_config.xml` permitting cleartext to your host or
subnet. Scope it narrowly rather than setting `cleartextTrafficPermitted="true"` for
everything.

**Finding the service.** There is no mDNS advertisement yet; it is on the
[roadmap](ROADMAP.md). For now, let the user enter a host, then confirm it with
`GET /api/v1/health` and check `service == "limelight"`.

**Pairing.** Read `auth_required` from `/health`. If true, collect a key, store it in
`EncryptedSharedPreferences`, and send it as a bearer token. Never write it to logs.

**Polling.** `GET /api/v1/state` in the foreground every 2 to 5 seconds. Stop when
backgrounded; the server holds no session and polling drains the battery for nothing.
There is no push channel, because the device itself has none.

**Optimistic updates.** Every write returns before the next poll reflects it. Update your
view immediately, then reconcile on the following `/state`. Expect one to two seconds of
device latency.

**Sliders.** Send one command on release, not per pixel of travel. The device is a
single-threaded ESP8266 on UDP and will drop a flood of datagrams. The web interface does
exactly this, and the same reasoning applies.

**Capability gating.** Read `capabilities` once at connection and hide unsupported
controls. A client that assumes this lamp's feature set will break on the next device.

**Ramp warnings.** When `service_driven` is true, tell the user the ramp needs the server
running. Presenting a sunrise as a reliable alarm without that caveat sets them up to
oversleep.

## Worked example

```bash
HOST=http://192.168.1.10:8765

curl -s $HOST/api/v1/health | jq .
curl -s $HOST/api/v1/device | jq '.capabilities'
curl -s $HOST/api/v1/state  | jq '.state'

curl -s -X POST $HOST/api/v1/power      -H 'Content-Type: application/json' -d '{"on":true}'
curl -s -X POST $HOST/api/v1/brightness -H 'Content-Type: application/json' -d '{"level":45}'
curl -s -X POST $HOST/api/v1/scene      -H 'Content-Type: application/json' -d '{"number":3}'

# A 20-minute wake-up, then cancel it
curl -s -X POST $HOST/api/v1/sunrise -H 'Content-Type: application/json' \
     -d '{"duration_min":20,"target":100}' | jq .
curl -s -X POST $HOST/api/v1/cancel_ramp

# Weekday alarm at 06:45
curl -s -X POST $HOST/api/v1/schedules -H 'Content-Type: application/json' -d '{
  "name":"Weekday wake","kind":"sunrise","time":"06:45",
  "days":[0,1,2,3,4],"duration_min":25,"target_brightness":100,"ambient":true}' | jq .

# With authentication enabled
curl -s -H "Authorization: Bearer $LIMELIGHT_API_KEY" $HOST/api/v1/state | jq .
```
