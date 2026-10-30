package com.smartwhale8.limelight.miio

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
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

    private val connectivity: ConnectivityManager?
        get() = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager

    /**
     * Every local network with an IPv4 address, by transport.
     *
     * [ConnectivityManager.getActiveNetwork] returns the VPN for an app that a VPN covers,
     * so reading it alone hides Wi-Fi, which is where lamps live.
     */
    @Suppress("DEPRECATION") // The replacement is a callback, and this is a one-shot read.
    private fun localNetworks(): Map<ScanTarget, Network> {
        val cm = connectivity ?: return emptyMap()
        return cm.allNetworks.mapNotNull { network ->
            val caps = cm.getNetworkCapabilities(network) ?: return@mapNotNull null
            val kind = when {
                // A VPN also reports the transports beneath it, so this check comes first.
                caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) -> NetworkKind.VPN
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkKind.WIFI
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> NetworkKind.ETHERNET
                else -> return@mapNotNull null
            }
            val subnet = ipv4Of(network)?.let(Subnet::prefixOf) ?: return@mapNotNull null
            ScanTarget(kind, subnet) to network
        }.toMap()
    }

    private fun ipv4Of(network: Network): String? {
        val props: LinkProperties = connectivity?.getLinkProperties(network) ?: return null
        return props.linkAddresses
            .map { it.address }
            .filterIsInstance<Inet4Address>()
            .firstOrNull { !it.isLoopbackAddress }
            ?.hostAddress
    }

    /** The networks the scan screen offers, Wi-Fi first. */
    fun scanTargets(): List<ScanTarget> = Subnet.scanOrder(localNetworks().keys)

    /** The default /24 prefix to sweep, including the trailing dot, for example `192.168.1.` */
    fun subnetPrefix(): String? = scanTargets().firstOrNull()?.subnet

    /**
     * Send this socket's traffic over the network that contains [address].
     *
     * An address on no local network goes over the first network that is not a VPN, so a
     * typed subnet behind the home router leaves through Wi-Fi.
     *
     * A VPN that forbids bypass refuses the bind. The socket then stays on the default
     * route, which still reaches the LAN when the VPN excludes local traffic.
     */
    fun bindFor(socket: DatagramSocket, address: String) {
        val networks = localNetworks()
        val targets = Subnet.scanOrder(networks.keys)
        val prefix = Subnet.prefixOf(address)
        val target = targets.firstOrNull { it.subnet == prefix }
            ?: targets.firstOrNull { it.kind != NetworkKind.VPN }
            ?: return
        runCatching { networks.getValue(target).bindSocket(socket) }
    }

    /**
     * Sweep a /24 and return every device that answers.
     *
     * @param subnet the prefix to sweep, or null for the first network in [scanTargets]
     * @param onProgress reports fractional progress while datagrams are being sent, so
     *   the interface can show a determinate indicator
     */
    suspend fun discover(
        subnet: String? = null,
        onProgress: (Float) -> Unit = {},
    ): List<DiscoveredDevice> =
        withContext(Dispatchers.IO) {
            val prefix = subnet ?: subnetPrefix()
                ?: return@withContext emptyList()

            // Replies arrive as unicast to our source port, so a multicast lock is not
            // strictly required. Some devices are aggressive about background radio use,
            // and holding one during a short scan is harmless.
            val wifi = context.applicationContext
                .getSystemService(Context.WIFI_SERVICE) as? WifiManager
            val lock = wifi?.createMulticastLock("limelight-discovery")?.apply {
                setReferenceCounted(true)
                runCatching { acquire() }
            }

            val found = LinkedHashMap<String, DiscoveredDevice>()
            try {
                DatagramSocket().use { socket ->
                    bindFor(socket, "${prefix}1")
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
