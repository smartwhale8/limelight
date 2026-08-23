package com.smartwhale8.lamplight.device

import com.smartwhale8.lamplight.miio.MiioClient
import kotlinx.coroutines.delay

/**
 * Driver for the Philips Eyecare Smart Lamp 2, model `philips.light.sread1`.
 *
 * Hardware is an ESP8266. Verified against firmware 1.2.8, MCU 0026, Wi-Fi 1.4.0.
 *
 * Command surface:
 *
 * | Function            | miIO method       | Argument            |
 * |---------------------|-------------------|---------------------|
 * | Power               | `set_power`       | `"on"` / `"off"`    |
 * | Main brightness     | `set_bright`      | 1..100              |
 * | Eyecare mode        | `set_eyecare`     | `"on"` / `"off"`    |
 * | Ambient light       | `enable_amb`      | `"on"` / `"off"`    |
 * | Ambient brightness  | `set_amb_bright`  | 1..100              |
 * | Fixed scene         | `set_user_scene`  | 1..4                |
 * | Sleep timer         | `delay_off`       | minutes, 0 cancels  |
 * | Smart night light   | `enable_bl`       | `"on"` / `"off"`    |
 * | Fatigue reminder    | `set_notifyuser`  | `"on"` / `"off"`    |
 *
 * ## Firmware quirks
 *
 * Two commands reset brightness as an undocumented side effect, measured on the hardware:
 *
 * 1. `set_eyecare` reset brightness from 25 to 53.
 * 2. `delay_off` reset brightness from 53 to 70.
 *
 * A user enabling eyecare or setting a sleep timer has not asked for a brightness change,
 * so [preserveBrightness] reads brightness first and restores it if the firmware moved it.
 * This mirrors the Python driver in the same repository.
 */
class PhilipsEyecareLamp(client: MiioClient) : LampDriver(client) {

    companion object {
        const val MODEL = "philips.light.sread1"
        const val DISPLAY_NAME = "Philips Eyecare Smart Lamp 2"

        /** Properties readable in one call, in the order the firmware returns them. */
        val PROPS = listOf(
            "power",         // "on" | "off"
            "bright",        // 1..100, main light
            "notifystatus",  // "on" | "off", eye-fatigue reminder
            "ambstatus",     // "on" | "off", ambient light
            "ambvalue",      // 1..100, ambient brightness
            "eyecare",       // "on" | "off"
            "scene_num",     // 1..4
            "bls",           // "on" | "off", smart night light
            "dvalue",        // sleep timer, minutes remaining, 0 when unset
        )

        val SCENE_NAMES = mapOf(1 to "Study", 2 to "Office", 3 to "Reading", 4 to "Bedtime")

        /** Time to let the firmware settle before re-reading brightness after a quirk. */
        private const val QUIRK_SETTLE_MS = 400L
    }

    override val model = MODEL
    override val displayName = DISPLAY_NAME
    override val scenes = SCENE_NAMES
    override val brightnessRange = 1..100

    override val capabilities = setOf(
        Capability.POWER,
        Capability.BRIGHTNESS,
        Capability.AMBIENT,
        Capability.AMBIENT_BRIGHTNESS,
        Capability.EYECARE,
        Capability.SCENES,
        Capability.NIGHT_LIGHT,
        Capability.REMINDER,
        Capability.SLEEP_TIMER,
    )

    // -------------------------------------------------------------------- reads

    override suspend fun readState(): LampState {
        val v = client.getProps(PROPS)
        return LampState(
            on = v["power"] == "on",
            brightness = v.int("bright"),
            ambientOn = v["ambstatus"]?.let { it == "on" },
            ambientBrightness = v.int("ambvalue"),
            eyecare = v["eyecare"]?.let { it == "on" },
            scene = v.int("scene_num"),
            nightLight = v["bls"]?.let { it == "on" },
            reminder = v["notifystatus"]?.let { it == "on" },
            sleepTimerMinutes = v.int("dvalue"),
        )
    }

    private fun Map<String, Any?>.int(key: String): Int? = when (val raw = this[key]) {
        is Int -> raw
        is Number -> raw.toInt()
        is String -> raw.toIntOrNull()
        else -> null
    }

    // ------------------------------------------------------------ quirk handling

    /** Run [block], then undo any brightness change the firmware made on its own. */
    private suspend fun preserveBrightness(block: suspend () -> Unit) {
        val wanted = readState().brightness
        block()
        if (wanted == null || wanted <= 0) return
        delay(QUIRK_SETTLE_MS)
        val now = readState().brightness
        if (now != null && now != wanted) {
            client.send("set_bright", wanted)
        }
    }

    // ------------------------------------------------------------------- writes

    override suspend fun setPower(on: Boolean) {
        client.send("set_power", if (on) "on" else "off")
    }

    override suspend fun setBrightness(level: Int) {
        client.send("set_bright", clampBrightness(level))
    }

    override suspend fun setAmbient(on: Boolean) {
        client.send("enable_amb", if (on) "on" else "off")
    }

    override suspend fun setAmbientBrightness(level: Int) {
        client.send("set_amb_bright", clampBrightness(level))
    }

    /** Quirk 1: this command resets main brightness, so it is restored. */
    override suspend fun setEyecare(on: Boolean) {
        preserveBrightness { client.send("set_eyecare", if (on) "on" else "off") }
    }

    override suspend fun setScene(number: Int) {
        require(number in SCENE_NAMES.keys) { "scene must be 1 to 4" }
        client.send("set_user_scene", number)
    }

    override suspend fun setNightLight(on: Boolean) {
        client.send("enable_bl", if (on) "on" else "off")
    }

    override suspend fun setReminder(on: Boolean) {
        client.send("set_notifyuser", if (on) "on" else "off")
    }

    /**
     * The device's own countdown, in minutes. Zero cancels it.
     *
     * This runs on the lamp, so it keeps working when the phone is away or switched off.
     * Quirk 2 applies, so brightness is restored afterwards.
     */
    override suspend fun setSleepTimer(minutes: Int) {
        val safe = minutes.coerceAtLeast(0)
        preserveBrightness { client.send("delay_off", safe) }
    }
}
