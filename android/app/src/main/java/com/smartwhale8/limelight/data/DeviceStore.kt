package com.smartwhale8.limelight.data

import android.content.Context

/**
 * Remembers the lamp that was last connected to, so the app opens straight into control.
 *
 * Stored in app-private [android.content.SharedPreferences], which other applications
 * cannot read on a non-rooted device.
 *
 * The device token is a complete credential for the lamp: whoever holds it can control the
 * device. It is not encrypted at rest here, on the basis that the lamp itself hands the
 * same token to anything on the local network that asks, so encrypting the copy on the
 * phone would protect very little. The exposure is a lamp on a home network, and the
 * mitigation that matters is the Wi-Fi password.
 */
class DeviceStore(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences("limelight", Context.MODE_PRIVATE)

    /** A lamp the user has connected to before. */
    data class Saved(
        val address: String,
        val deviceId: Long,
        val token: String,
        val model: String,
        val label: String,
    )

    fun load(): Saved? {
        val address = prefs.getString(KEY_ADDRESS, null) ?: return null
        val token = prefs.getString(KEY_TOKEN, null) ?: return null
        val deviceId = prefs.getLong(KEY_DEVICE_ID, 0L)
        if (deviceId == 0L) return null
        return Saved(
            address = address,
            deviceId = deviceId,
            token = token,
            model = prefs.getString(KEY_MODEL, "").orEmpty(),
            label = prefs.getString(KEY_LABEL, "Lamp").orEmpty(),
        )
    }

    fun save(saved: Saved) {
        prefs.edit()
            .putString(KEY_ADDRESS, saved.address)
            .putLong(KEY_DEVICE_ID, saved.deviceId)
            .putString(KEY_TOKEN, saved.token)
            .putString(KEY_MODEL, saved.model)
            .putString(KEY_LABEL, saved.label)
            .apply()
    }

    /** Record a new address after the device moved, keeping everything else. */
    fun updateAddress(address: String) {
        prefs.edit().putString(KEY_ADDRESS, address).apply()
    }

    fun clear() {
        prefs.edit().clear().apply()
    }

    /**
     * Tokens for devices seen before, keyed by device id.
     *
     * Lets the app reconnect to a device that withholds its token in the handshake without
     * asking the user to paste it again.
     */
    fun rememberToken(deviceId: Long, token: String) {
        prefs.edit().putString("$KEY_TOKEN_PREFIX$deviceId", token).apply()
    }

    fun tokenFor(deviceId: Long): String? =
        prefs.getString("$KEY_TOKEN_PREFIX$deviceId", null)

    private companion object {
        const val KEY_ADDRESS = "address"
        const val KEY_DEVICE_ID = "device_id"
        const val KEY_TOKEN = "token"
        const val KEY_MODEL = "model"
        const val KEY_LABEL = "label"
        const val KEY_TOKEN_PREFIX = "token_for_"
    }
}
