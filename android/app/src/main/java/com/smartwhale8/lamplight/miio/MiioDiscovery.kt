package com.smartwhale8.lamplight.miio

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.wifi.WifiManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.Inet4Address
import java.net.InetAddress

/**
 * One device found on the network.
 *
 * [token] is present only when the firmware discloses it, which is the case for any
 * device that has never been bound to a vendor cloud account. When it is null the user
 * has to supply a token by hand before the device can be controlled.
 */
data class DiscoveredDevice(
    val address: String,
    val deviceId: Long,
    val token: String?,
) {
    val tokenDisclosed: Boolean get() = token != null
}

/**
 * Finds miIO devices on the local network.
 *
 * Discovery is the unencrypted handshake: a 32-byte hello sent to UDP 54321. No
 * credential is involved, so any device on the subnet answers with its device id, and
 * firmware that discloses its token includes that too.
 *
 * Both a broadcast and a unicast sweep of the whole /24 are sent, because some access
 * points drop directed broadcast between clients while still forwarding unicast.
 */
class MiioDiscovery(private val context: Context) {

    companion object {
        private const val COLLECT_MS = 3_000L
        private const val SEND_PAUSE_MS = 2L
    }

    /**
     * The device's own IPv4 address on the active network, or null when not on IPv4.
     *
     * Read from [ConnectivityManager] rather than by enumerating interfaces, so it
     * reflects the network actually in use rather than any interface that happens to be up.
     */
    fun localIpv4(): String? {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return null
        val network = cm.activeNetwork ?: return null
        val props: LinkProperties = cm.getLinkProperties(network) ?: return null
        return props.linkAddresses
            .map { it.address }
            .filterIsInstance<Inet4Address>()
            .firstOrNull { !it.isLoopbackAddress }
            ?.hostAddress
    }

    /** The /24 prefix to sweep, including the trailing dot, for example `192.168.0.` */
    fun subnetPrefix(): String? =
        localIpv4()?.substringBeforeLast('.')?.plus('.')

    /**
     * Sweep the local /24 and return every device that answers.
     *
     * @param onProgress reports fractional progress while datagrams are being sent, so
     *   the interface can show a determinate indicator
     */
    suspend fun discover(onProgress: (Float) -> Unit = {}): List<DiscoveredDevice> =
        withContext(Dispatchers.IO) {
            val prefix = subnetPrefix()
                ?: return@withContext emptyList()

            // Replies arrive as unicast to our source port, so a multicast lock is not
            // strictly required. Some devices are aggressive about background radio use,
            // and holding one during a short scan is harmless.
            val wifi = context.applicationContext
                .getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val lock = wifi?.createMulticastLock("lamplight-discovery")?.apply {
                setReferenceCounted(true)
                runCatching { acquire() }
            }

            val found = LinkedHashMap<String, DiscoveredDevice>()
            try {
                DatagramSocket().use { socket ->
                    socket.broadcast = true
                    socket.soTimeout = 400

                    runCatching {
                        socket.send(
                            DatagramPacket(
                                MiioCodec.HELLO, MiioCodec.HELLO.size,
                                InetAddress.getByName("255.255.255.255"), MiioCodec.PORT
                            )
                        )
                    }

                    for (host in 1..254) {
                        runCatching {
                            socket.send(
                                DatagramPacket(
                                    MiioCodec.HELLO, MiioCodec.HELLO.size,
                                    InetAddress.getByName("$prefix$host"), MiioCodec.PORT
                                )
                            )
                        }
                        // Pacing keeps the radio and the ARP table from being swamped.
                        if (host % 16 == 0) {
                            Thread.sleep(SEND_PAUSE_MS)
                            onProgress(host / 254f * 0.6f)
                        }
                    }
                    onProgress(0.6f)

                    val deadline = System.currentTimeMillis() + COLLECT_MS
                    val buffer = ByteArray(1024)
                    while (System.currentTimeMillis() < deadline) {
                        try {
                            val reply = DatagramPacket(buffer, buffer.size)
                            socket.receive(reply)
                            val decoded = MiioCodec.parseHandshake(reply.data, reply.length)
                            if (decoded != null) {
                                val ip = reply.address.hostAddress ?: continue
                                found[ip] = DiscoveredDevice(ip, decoded.deviceId, decoded.token)
                            }
                        } catch (_: Exception) {
                            // A timeout here simply means nothing arrived in this slice.
                        }
                        val elapsed = COLLECT_MS - (deadline - System.currentTimeMillis())
                        onProgress(0.6f + (elapsed.toFloat() / COLLECT_MS) * 0.4f)
                    }
                }
            } finally {
                runCatching { lock?.release() }
            }

            onProgress(1f)
            found.values.toList()
        }

    /**
     * Look for one known device by id, for use after a DHCP address change.
     *
     * Returns its current address, or null when it cannot be found.
     */
    suspend fun findById(deviceId: Long): String? =
        discover().firstOrNull { it.deviceId == deviceId }?.address
}
