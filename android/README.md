# Lamplight for Android

A standalone Android client that talks to the lamp **directly over miIO**, with no server
in between.

The phone sends UDP datagrams to the lamp on your Wi-Fi. Nothing else has to be running:
no laptop, no cloud service, no account.

## What it does

1. **Finds lamps.** Broadcasts the miIO handshake across your subnet and lists everything
   that answers.
2. **Connects.** A device that discloses its token connects in one tap. One that withholds
   it prompts for a token, and remembers it afterwards.
3. **Controls.** Power, brightness, eyecare mode, ambient light and its brightness, four
   scenes, smart night light, fatigue reminder, and the lamp's own sleep timer.

Controls are rendered from the device's capability set, so a different model shows a
different set of controls with no code change.

## Install it

Download the APK from [Releases](https://github.com/smartwhale8/lamplight/releases) and
sideload it. Your browser or file manager will ask for permission to install once.

It is a debug build, signed with the standard debug key. That is fine for sideloading and
means it cannot go to Play without resigning.

Every push also produces an APK as a workflow artifact under the Actions tab, which is
useful between releases but expires after 90 days and needs a GitHub login.

## Build it

Requires **Android Studio** with a JDK 17 toolchain.

1. Open the `android/` directory in Android Studio, not the repository root.
2. Let it sync. It will fetch the Gradle distribution named in
   `gradle/wrapper/gradle-wrapper.properties` and generate the wrapper JAR if it is
   missing.
3. Run on a device or emulator on the same Wi-Fi network as the lamp.

From the command line, once the wrapper exists:

```bash
cd android
./gradlew assembleDebug
# app/build/outputs/apk/debug/app-debug.apk
```

An emulator will not find the lamp, because it sits behind its own NAT rather than on your
Wi-Fi. Use a real phone.

## How it works

The protocol is documented in full in [../docs/PROTOCOL.md](../docs/PROTOCOL.md), and the
concepts are introduced in [../README.md](../README.md#how-it-works). In brief:

| | |
|---|---|
| Transport | UDP port 54321 |
| Encryption | AES-128-CBC, key `md5(token)`, IV `md5(key + token)` |
| Credential | A 16-byte device token, which is the only access control |
| Discovery | A 32-byte unencrypted hello; devices answer with their id and, on most firmware, their token |

### Verification

The Kotlin codec in `miio/MiioCodec.kt` cannot be exercised against the hardware from CI,
so it was verified by translating it line by line into Python and comparing its output
with `python-miio`, which has been run against the real lamp. With the same request, the
same token, the same device id and the same uptime stamp, **the Kotlin produces a
byte-identical packet**, and `python-miio` decrypts a Kotlin-built packet back to the
original request.

That comparison found a real defect: the reference implementation appends a **null
terminator** to the JSON before encrypting, and the first version of this code did not.
The packets looked plausible and would have failed against the firmware.

## Layout

```
app/src/main/java/com/smartwhale8/lamplight/
  MainActivity.kt              single activity, picks discovery or control
  miio/
    MiioCodec.kt               packet framing and cryptography
    MiioClient.kt              one connection: retries, request ids, uptime stamp
    MiioDiscovery.kt           subnet sweep and broadcast
  device/
    Device.kt                  Capability, LampState, LampDriver, DriverRegistry
    PhilipsEyecareLamp.kt      the concrete driver, including firmware quirks
  data/DeviceStore.kt          remembers the last lamp
  ui/
    LampViewModel.kt           state, polling, commands
    DiscoveryScreen.kt         scan, list, connect, token entry
    ControlScreen.kt           the controls
    theme/Theme.kt             Material 3, light and dark
```

No third-party runtime dependency. The protocol uses `javax.crypto` and `java.net`, and
JSON uses `org.json`, all from the platform.

## Design notes

**Sliders commit on release.** The lamp is a single-threaded ESP8266 on a connectionless
transport. A datagram per pixel of travel is dropped, not queued.

**State is polled every three seconds while the app is in the foreground**, and polling
stops in `onStop`. The lamp offers no push channel, so there is nothing to subscribe to,
and a background poll would drain the battery to tell nobody anything.

**Commands apply optimistically**, then reconcile on the next poll. The device takes one to
two seconds to reflect a change.

**A lost datagram is indistinguishable from a dead device**, so every command is retried
with increasing backoff before failing.

**The address is not the identity.** DHCP moves devices. The app stores the device id,
which never changes, and re-runs discovery to find the lamp again if the stored address
goes quiet.

**Two firmware defects are compensated for**, in `PhilipsEyecareLamp`: `set_eyecare` and
`delay_off` each reset brightness as an undocumented side effect, so brightness is read
first and restored afterwards.

## Permissions

| Permission | Why |
|---|---|
| `INTERNET` | Required for any socket, including a purely local one |
| `ACCESS_NETWORK_STATE` | Reads the active network's IPv4 address, to derive the subnet to sweep |
| `CHANGE_WIFI_MULTICAST_STATE` | Holds a multicast lock during a scan |

No cleartext HTTP configuration is needed, because the app speaks raw UDP rather than HTTP.

## Security

There is no authentication, by design and by necessity: the lamp itself has none beyond
its token, and on this firmware it hands that token to anything on the network that asks.

The token is stored in app-private preferences and excluded from cloud backup and device
transfer. Encrypting it further would protect little, since the lamp discloses the same
value to any host on the Wi-Fi. The control that actually matters is your Wi-Fi password.
See [../SECURITY.md](../SECURITY.md).

## Not included

Sunrise ramps and recurring schedules are not in this app. They require something to be
running at the scheduled moment, and Android's background execution limits make a phone a
poor host for that. They live in the Python service, which can run on any always-on
machine. A foreground-service implementation is noted in
[../docs/ROADMAP.md](../docs/ROADMAP.md).

The lamp's own sleep timer **is** included, because the countdown runs on the device and
survives the phone being away.
