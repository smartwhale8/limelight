package com.smartwhale8.lamplight.device

import com.smartwhale8.lamplight.miio.MiioClient

/**
 * A feature a lamp may support.
 *
 * The interface renders controls from a driver's capability set rather than assuming what
 * a device can do, so a second model needs no change to the screens. The string values
 * match those published by the lamplight HTTP service, so the two stay comparable.
 */
enum class Capability(val id: String) {
    POWER("power"),
    BRIGHTNESS("brightness"),
    AMBIENT("ambient"),
    AMBIENT_BRIGHTNESS("ambient_brightness"),
    EYECARE("eyecare"),
    SCENES("scenes"),
    NIGHT_LIGHT("night_light"),
    REMINDER("reminder"),
    SLEEP_TIMER("sleep_timer"),
}

/**
 * A normalised snapshot of a lamp.
 *
 * Fields the device does not support stay null, which is how the interface distinguishes
 * "off" from "not present".
 */
data class LampState(
    val on: Boolean = false,
    val brightness: Int? = null,
    val ambientOn: Boolean? = null,
    val ambientBrightness: Int? = null,
    val eyecare: Boolean? = null,
    val scene: Int? = null,
    val nightLight: Boolean? = null,
    val reminder: Boolean? = null,
    val sleepTimerMinutes: Int? = null,
)

/**
 * The operations lamplight expects of a lamp.
 *
 * A driver declares its model, a display name and a capability set, then implements only
 * what that set claims. Anything else throws [UnsupportedOperationException], which the
 * view model turns into a message rather than a crash.
 */
abstract class LampDriver(protected val client: MiioClient) {

    abstract val model: String
    abstract val displayName: String
    abstract val capabilities: Set<Capability>

    /** Scene number to name. Empty when the device has no scenes. */
    open val scenes: Map<Int, String> = emptyMap()

    /** Inclusive brightness bounds as the device defines them. */
    open val brightnessRange: IntRange = 1..100

    val address: String get() = client.address

    fun supports(capability: Capability): Boolean = capability in capabilities

    protected fun clampBrightness(level: Int): Int =
        level.coerceIn(brightnessRange.first, brightnessRange.last)

    private fun unsupported(what: String): Nothing =
        throw UnsupportedOperationException("$displayName does not support $what")

    // ------------------------------------------------------------------- reads

    abstract suspend fun readState(): LampState

    // ------------------------------------------------------------------ writes

    abstract suspend fun setPower(on: Boolean)

    open suspend fun setBrightness(level: Int): Unit = unsupported("brightness")
    open suspend fun setAmbient(on: Boolean): Unit = unsupported("the ambient light")
    open suspend fun setAmbientBrightness(level: Int): Unit = unsupported("ambient brightness")
    open suspend fun setEyecare(on: Boolean): Unit = unsupported("eyecare mode")
    open suspend fun setScene(number: Int): Unit = unsupported("scenes")
    open suspend fun setNightLight(on: Boolean): Unit = unsupported("the night light")
    open suspend fun setReminder(on: Boolean): Unit = unsupported("the fatigue reminder")
    open suspend fun setSleepTimer(minutes: Int): Unit = unsupported("a sleep timer")
}

/**
 * Maps a miIO model identifier to a driver.
 *
 * Identifiers take the form `vendor.category.model`, for example `philips.light.sread1`.
 * The identifier, not the brand on the device, is what selects a driver.
 */
object DriverRegistry {

    private val builders: Map<String, (MiioClient) -> LampDriver> = mapOf(
        PhilipsEyecareLamp.MODEL to { client -> PhilipsEyecareLamp(client) },
    )

    /** Every supported model, as identifier to display name. */
    val supportedModels: Map<String, String> = mapOf(
        PhilipsEyecareLamp.MODEL to PhilipsEyecareLamp.DISPLAY_NAME,
    )

    fun isSupported(model: String): Boolean = model in builders

    /** Build a driver for [model], or null when the model is unknown. */
    fun create(model: String, client: MiioClient): LampDriver? = builders[model]?.invoke(client)

    /**
     * Build a driver by asking the device what it is.
     *
     * Costs one round trip and removes any need to record the model by hand.
     */
    suspend fun createByAsking(client: MiioClient): LampDriver? {
        val model = client.info().optString("model", "")
        return if (model.isEmpty()) null else create(model, client)
    }
}
