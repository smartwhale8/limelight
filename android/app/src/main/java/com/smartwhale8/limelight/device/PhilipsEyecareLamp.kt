package com.smartwhale8.limelight.device

import com.smartwhale8.limelight.miio.MiioClient

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
 * | Fixed scene         | `set_user_scene`  | 1..3                |
 * | Sleep timer         | `delay_off`       | minutes, 0 cancels  |
 * | Smart night light   | `enable_bl`       | `"on"` / `"off"`    |
 * | Fatigue reminder    | `set_notifyuser`  | `"on"` / `"off"`    |
 *
 * ## Eyecare mode and brightness are coupled
 *
 * Two behaviours, measured on the hardware, that a client has to respect:
 *
 * 1. **Enabling eyecare hands brightness to the mode.** It ramps to its own level over
 *    about three seconds: 25 became 53 after one second and 70 after three. That is the
 *    feature working, not a defect.
 * 2. **`set_bright` cancels eyecare.** There is no way to hold both.
 *
 * So brightness must not be re-applied after enabling eyecare. An earlier version did
 * exactly that, believing it was correcting a firmware defect, and the result was that
 * eyecare switched on and immediately off again: the lamp's base flashed the eye symbol
 * and reverted to the brightness markers.
 *
 * `delay_off` disturbs nothing else.
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
            "scene_num",     // 1..3
            "bls",           // "on" | "off", smart night light
            "dvalue",        // sleep timer, minutes remaining, 0 when unset
        )

        /**
         * The device accepts 1, 2 and 3. Scene 4 is rejected with `param error` (-5001).
         *
         * The names are neutral on purpose: setting a scene changes `scene_num` and
         * nothing else that can be read back, so naming them would be invention.
         */
        val SCENE_NAMES = mapOf(1 to "Scene 1", 2 to "Scene 2", 3 to "Scene 3")
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

    // ------------------------------------------------------------------- writes

    override suspend fun setPower(on: Boolean) {
        client.send("set_power", if (on) "on" else "off")
    }

    /**
     * Set the main light.
     *
     * This **cancels eyecare mode** if it is on. The hardware offers no way to hold both,
     * so a client that sets brightness is implicitly leaving eyecare.
     */
    override suspend fun setBrightness(level: Int) {
        client.send("set_bright", clampBrightness(level))
    }

    override suspend fun setAmbient(on: Boolean) {
        client.send("enable_amb", if (on) "on" else "off")
    }

    override suspend fun setAmbientBrightness(level: Int) {
        client.send("set_amb_bright", clampBrightness(level))
    }

    /**
     * Switch eyecare mode.
     *
     * Enabling it hands brightness to the mode, which ramps to its own level over about
     * three seconds. Do not re-apply brightness afterwards: that cancels the mode.
     */
    override suspend fun setEyecare(on: Boolean) {
        client.send("set_eyecare", if (on) "on" else "off")
    }

    override suspend fun setScene(number: Int) {
        require(number in SCENE_NAMES.keys) { "scene must be 1 to 3" }
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
     * It disturbs nothing else.
     */
    override suspend fun setSleepTimer(minutes: Int) {
        client.send("delay_off", minutes.coerceAtLeast(0))
    }
}
