package com.smartwhale8.lamplight.miio

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.util.concurrent.atomic.AtomicInteger

/** Raised when a device does not answer after retries. */
class DeviceUnreachableException(message: String, cause: Throwable? = null) :
    Exception(message, cause)

/** Raised when a device answers with an error object. */
class DeviceErrorException(val code: Int, message: String) : Exception(message)

/**
 * A connection to one miIO device.
 *
 * UDP is connectionless, so a lost datagram is indistinguishable from a dead device.
 * Every command is therefore retried with increasing backoff before being reported as a
 * failure.
 *
 * Two pieces of state have to be kept in step with the device:
 *
 * *Request id* must increase. A reused id is silently ignored by the firmware.
 *
 * *Uptime stamp* must be close to the device's own. It is learned from a handshake and
 * then advanced by locally elapsed time. A stale stamp is also silently ignored, which is
 * why [handshake] is repeated once the last one is older than [HANDSHAKE_MAX_AGE_MS].
 *
 * All calls are suspending and run on [Dispatchers.IO]. Instances are not safe for
 * concurrent use from several coroutines; the view model serialises access.
 */
class MiioClient(
    address: String,
    val token: String,
    val deviceId: Long,
) {
    /** Updated in place when the device is found at a new address after a DHCP change. */
    @Volatile
    var address: String = address

    companion object {
        private const val TIMEOUT_MS = 2_000
        private const val RETRIES = 3
        private const val HANDSHAKE_MAX_AGE_MS = 60_000L
    }

    private val requestId = AtomicInteger(1)

    /** Device uptime reported by the last handshake, with the local time it was taken. */
    private var deviceStamp: Long = 0
    private var handshakeAtMs: Long = 0

    /** Milliseconds since the last successful exchange, for a staleness indicator. */
    @Volatile
    var lastSuccessMs: Long = 0
        private set

    // ---------------------------------------------------------------- handshake

    /** Refresh the uptime stamp. Cheap, unencrypted, and needs no credential. */
    suspend fun handshake(): MiioCodec.Handshake = withContext(Dispatchers.IO) {
        DatagramSocket().use { socket ->
            socket.soTimeout = TIMEOUT_MS
            val target = InetAddress.getByName(address)
            var lastError: Exception? = null

            repeat(RETRIES) { attempt ->
                try {
                    socket.send(DatagramPacket(MiioCodec.HELLO, MiioCodec.HELLO.size, target, MiioCodec.PORT))
                    val buffer = ByteArray(1024)
                    val reply = DatagramPacket(buffer, buffer.size)
                    socket.receive(reply)
                    val decoded = MiioCodec.parseHandshake(reply.data, reply.length)
                    if (decoded != null) {
                        deviceStamp = decoded.stamp
                        handshakeAtMs = System.currentTimeMillis()
                        lastSuccessMs = handshakeAtMs
                        return@withContext decoded
                    }
                } catch (e: SocketTimeoutException) {
                    lastError = e
                } catch (e: Exception) {
                    lastError = e
                }
                Thread.sleep(200L * (attempt + 1))
            }
            throw DeviceUnreachableException("no handshake reply from $address", lastError)
        }
    }

    private suspend fun ensureFreshStamp() {
        if (System.currentTimeMillis() - handshakeAtMs > HANDSHAKE_MAX_AGE_MS) handshake()
    }

    private fun currentStamp(): Long =
        deviceStamp + (System.currentTimeMillis() - handshakeAtMs) / 1000

    // ------------------------------------------------------------------ commands

    /**
     * Send one command and return its `result` value.
     *
     * @param method the miIO method, for example `set_bright`
     * @param params the argument array, for example `[45]`
     */
    suspend fun send(method: String, params: JSONArray): Any? =
        withContext(Dispatchers.IO) {
            ensureFreshStamp()

            val id = requestId.getAndIncrement()
            val body = JSONObject().apply {
                put("id", id)
                put("method", method)
                put("params", params)
            }.toString()

            var lastError: Exception? = null

            repeat(RETRIES) { attempt ->
                try {
                    DatagramSocket().use { socket ->
                        socket.soTimeout = TIMEOUT_MS
                        val packet = MiioCodec.buildCommand(body, token, deviceId, currentStamp())
                        socket.send(
                            DatagramPacket(
                                packet, packet.size,
                                InetAddress.getByName(address), MiioCodec.PORT
                            )
                        )

                        val buffer = ByteArray(4096)
                        val reply = DatagramPacket(buffer, buffer.size)
                        socket.receive(reply)

                        val json = MiioCodec.decodeReply(reply.data, reply.length, token)
                        if (json != null) {
                            lastSuccessMs = System.currentTimeMillis()
                            return@withContext parseResult(json)
                        }
                        // A payload-free reply means the device wants a fresh handshake.
                        handshake()
                    }
                } catch (e: DeviceErrorException) {
                    throw e                      // a real device error, not a lost datagram
                } catch (e: SocketTimeoutException) {
                    lastError = e
                } catch (e: Exception) {
                    lastError = e
                }

                // Before the final attempt, re-handshake in case the stamp drifted.
                if (attempt == RETRIES - 2) {
                    runCatching { handshake() }
                }
                Thread.sleep(300L * (attempt + 1))
            }
            throw DeviceUnreachableException("$method failed after $RETRIES attempts", lastError)
        }

    /** Convenience for the common case of a single-value argument list. */
    suspend fun send(method: String, vararg args: Any): Any? =
        send(method, JSONArray().apply { args.forEach { put(it) } })

    private fun parseResult(json: String): Any? {
        val obj = JSONObject(json)
        if (obj.has("error")) {
            val err = obj.getJSONObject("error")
            throw DeviceErrorException(
                err.optInt("code", 0),
                err.optString("message", "device reported an error")
            )
        }
        return if (obj.has("result")) obj.get("result") else null
    }

    // -------------------------------------------------------------------- reads

    /**
     * Read several properties in one call.
     *
     * One request for all of them is not an optimisation nicety: the device is a
     * single-threaded microcontroller on a connectionless transport, and one request per
     * property will drop datagrams.
     *
     * Some firmware returns fewer values than requested, so the result is zipped
     * defensively and a missing property becomes null.
     */
    suspend fun getProps(names: List<String>): Map<String, Any?> {
        val result = send("get_prop", JSONArray().apply { names.forEach { put(it) } })
        val values = result as? JSONArray ?: return emptyMap()
        return names.mapIndexed { i, name ->
            name to if (i < values.length() && !values.isNull(i)) values.get(i) else null
        }.toMap()
    }

    /** The device's self-description. Includes the token on some firmware; never log it. */
    suspend fun info(): JSONObject {
        val result = send("miIO.info", JSONArray())
        return result as? JSONObject ?: JSONObject()
    }
}
