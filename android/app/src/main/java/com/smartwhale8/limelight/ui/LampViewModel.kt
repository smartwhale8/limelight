package com.smartwhale8.limelight.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.smartwhale8.limelight.data.DeviceStore
import com.smartwhale8.limelight.device.Capability
import com.smartwhale8.limelight.device.DriverRegistry
import com.smartwhale8.limelight.device.LampDriver
import com.smartwhale8.limelight.device.LampState
import com.smartwhale8.limelight.miio.DeviceUnreachableException
import com.smartwhale8.limelight.miio.DiscoveredDevice
import com.smartwhale8.limelight.miio.MiioClient
import com.smartwhale8.limelight.miio.MiioDiscovery
import com.smartwhale8.limelight.miio.isValidToken
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Static description of the connected lamp, for rendering controls. */
data class DeviceInfo(
    val label: String,
    val model: String,
    val address: String,
    val deviceId: Long,
    val capabilities: Set<Capability>,
    val scenes: Map<Int, String>,
)

/** Everything the interface needs, in one object. */
data class UiState(
    val device: DeviceInfo? = null,
    val lamp: LampState? = null,
    val reachable: Boolean = true,
    val busy: Boolean = false,
    val scanning: Boolean = false,
    val scanProgress: Float = 0f,
    val found: List<DiscoveredDevice> = emptyList(),
    val subnet: String? = null,
    val message: String? = null,
    /** Set when the user picked a device that withholds its token and must supply one. */
    val awaitingTokenFor: DiscoveredDevice? = null,
)

/**
 * Holds the connection to one lamp and drives every screen.
 *
 * The lamp exposes no push channel, so state is polled while the app is in the
 * foreground. Polling stops when the app is backgrounded, which [stopPolling] is for.
 *
 * A command is applied optimistically to the local state so the interface responds
 * immediately, then reconciled by the next poll. The device typically takes one to two
 * seconds to reflect a change.
 */
class LampViewModel(app: Application) : AndroidViewModel(app) {

    private val store = DeviceStore(app)
    private val discovery = MiioDiscovery(app)

    private var driver: LampDriver? = null
    private var pollJob: Job? = null

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state.asStateFlow()

    init {
        _state.update { it.copy(subnet = discovery.subnetPrefix()) }
        store.load()?.let { saved -> reconnect(saved) }
    }

    // ------------------------------------------------------------------ discovery

    fun scan() {
        if (_state.value.scanning) return
        viewModelScope.launch {
            _state.update {
                it.copy(scanning = true, scanProgress = 0f, found = emptyList(), message = null)
            }
            try {
                val subnet = discovery.subnetPrefix()
                if (subnet == null) {
                    _state.update {
                        it.copy(
                            scanning = false,
                            message = "No Wi-Fi connection. Join the network the lamp is on."
                        )
                    }
                    return@launch
                }
                val devices = discovery.discover { progress ->
                    _state.update { it.copy(scanProgress = progress) }
                }
                _state.update {
                    it.copy(
                        scanning = false,
                        found = devices,
                        subnet = subnet,
                        message = if (devices.isEmpty())
                            "No devices answered on ${subnet}0/24. " +
                                "Check the lamp is powered on and joined to this network."
                        else null
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(scanning = false, message = "Scan failed: ${e.message}") }
            }
        }
    }

    /**
     * Connect to a discovered device.
     *
     * Uses the token from the handshake when the firmware disclosed one, otherwise a token
     * remembered from a previous session, otherwise asks the user for one.
     */
    fun connect(device: DiscoveredDevice) {
        val token = device.token ?: store.tokenFor(device.deviceId)
        if (token == null) {
            _state.update { it.copy(awaitingTokenFor = device) }
            return
        }
        connectWith(device, token)
    }

    /** Connect using a token the user typed in. */
    fun connectWithToken(device: DiscoveredDevice, token: String) {
        val clean = token.trim().lowercase()
        if (!clean.isValidToken()) {
            _state.update { it.copy(message = "A token is 32 hexadecimal characters.") }
            return
        }
        store.rememberToken(device.deviceId, clean)
        _state.update { it.copy(awaitingTokenFor = null) }
        connectWith(device, clean)
    }

    fun cancelTokenEntry() {
        _state.update { it.copy(awaitingTokenFor = null) }
    }

    private fun connectWith(device: DiscoveredDevice, token: String) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true, message = null) }
            try {
                val client = MiioClient(device.address, token, device.deviceId)
                val built = DriverRegistry.createByAsking(client)
                if (built == null) {
                    _state.update {
                        it.copy(
                            busy = false,
                            message = "That device is not supported yet. " +
                                "Supported: ${DriverRegistry.supportedModels.values.joinToString()}"
                        )
                    }
                    return@launch
                }
                driver = built
                store.save(
                    DeviceStore.Saved(
                        address = device.address,
                        deviceId = device.deviceId,
                        token = token,
                        model = built.model,
                        label = built.displayName,
                    )
                )
                store.rememberToken(device.deviceId, token)
                publishDevice(built, built.displayName, device.deviceId)
                startPolling()
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, message = friendly(e)) }
            }
        }
    }

    private fun reconnect(saved: DeviceStore.Saved) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true) }
            val client = MiioClient(saved.address, saved.token, saved.deviceId)
            val built = DriverRegistry.create(saved.model, client)
            if (built == null) {
                _state.update { it.copy(busy = false) }
                return@launch
            }
            driver = built
            publishDevice(built, saved.label, saved.deviceId)
            startPolling()

            // The address comes from DHCP and can move. If the stored one is silent, find
            // the device again by its id, which never changes.
            try {
                built.readState()
            } catch (_: DeviceUnreachableException) {
                _state.update { it.copy(message = "Looking for the lamp on this network…") }
                val moved = discovery.findById(saved.deviceId)
                if (moved != null) {
                    client.address = moved
                    store.updateAddress(moved)
                    publishDevice(built, saved.label, saved.deviceId)
                    _state.update { it.copy(message = "Lamp moved to $moved") }
                } else {
                    _state.update {
                        it.copy(reachable = false, message = "Cannot find the lamp on this network.")
                    }
                }
            }
        }
    }

    private fun publishDevice(built: LampDriver, label: String, deviceId: Long) {
        _state.update {
            it.copy(
                busy = false,
                device = DeviceInfo(
                    label = label,
                    model = built.model,
                    address = built.address,
                    deviceId = deviceId,
                    capabilities = built.capabilities,
                    scenes = built.scenes,
                ),
            )
        }
    }

    /** Forget the lamp and return to the discovery screen. */
    fun disconnect() {
        stopPolling()
        driver = null
        store.clear()
        _state.value = UiState(subnet = discovery.subnetPrefix())
    }

    // -------------------------------------------------------------------- polling

    fun startPolling() {
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch {
            while (true) {
                refresh()
                delay(POLL_INTERVAL_MS)
            }
        }
    }

    fun stopPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    private suspend fun refresh() {
        val d = driver ?: return
        try {
            val lamp = d.readState()
            _state.update { it.copy(lamp = lamp, reachable = true) }
        } catch (_: Exception) {
            _state.update { it.copy(reachable = false) }
        }
    }

    // ------------------------------------------------------------------- commands

    private fun command(optimistic: (LampState) -> LampState = { it }, block: suspend LampDriver.() -> Unit) {
        val d = driver ?: return
        // Update locally first so the control does not lag behind the finger.
        _state.update { s -> s.copy(lamp = s.lamp?.let(optimistic)) }
        viewModelScope.launch {
            try {
                d.block()
                refresh()
            } catch (e: Exception) {
                _state.update { it.copy(message = friendly(e)) }
                refresh()
            }
        }
    }

    fun setPower(on: Boolean) = command({ it.copy(on = on) }) { setPower(on) }

    fun setBrightness(level: Int) = command({ it.copy(brightness = level) }) { setBrightness(level) }

    fun setAmbient(on: Boolean) = command({ it.copy(ambientOn = on) }) { setAmbient(on) }

    fun setAmbientBrightness(level: Int) =
        command({ it.copy(ambientBrightness = level) }) { setAmbientBrightness(level) }

    fun setEyecare(on: Boolean) = command({ it.copy(eyecare = on) }) { setEyecare(on) }

    fun setScene(number: Int) = command({ it.copy(scene = number) }) { setScene(number) }

    fun setNightLight(on: Boolean) = command({ it.copy(nightLight = on) }) { setNightLight(on) }

    fun setReminder(on: Boolean) = command({ it.copy(reminder = on) }) { setReminder(on) }

    fun setSleepTimer(minutes: Int) =
        command({ it.copy(sleepTimerMinutes = minutes) }) { setSleepTimer(minutes) }

    fun dismissMessage() {
        _state.update { it.copy(message = null) }
    }

    private fun friendly(e: Exception): String = when (e) {
        is DeviceUnreachableException -> "The lamp did not respond. It may be off, or on another network."
        is UnsupportedOperationException -> e.message ?: "That is not supported on this device."
        else -> e.message ?: e.javaClass.simpleName
    }

    private companion object {
        const val POLL_INTERVAL_MS = 3_000L
    }
}
