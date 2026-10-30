package com.smartwhale8.limelight.miio

/** A kind of local network, in the order the scan screen offers them. */
enum class NetworkKind(val label: String) {
    WIFI("Wi-Fi"),
    ETHERNET("Ethernet"),
    VPN("VPN"),
}

/** A network the phone is on, which the scan screen offers as a choice. */
data class ScanTarget(val kind: NetworkKind, val subnet: String) {
    val cidr: String get() = "${subnet}0/24"
}

/**
 * Parsing for the /24 subnets that discovery sweeps.
 *
 * A subnet is passed around as its prefix including the trailing dot, for example
 * `192.168.1.`, which is what the sweep appends a host number to.
 */
object Subnet {

    private val SUFFIX = Regex("""\.0(/24)?$""")

    /** Wi-Fi first, VPN last, and one choice for each subnet. */
    fun scanOrder(targets: Collection<ScanTarget>): List<ScanTarget> =
        targets.sortedBy { it.kind }.distinctBy { it.subnet }

    /** The prefix of an IPv4 address, or null when [ipv4] is not one. */
    fun prefixOf(ipv4: String): String? {
        val octets = ipv4.split('.')
        if (octets.size != 4 || !octets.all(::isOctet)) return null
        return octets.take(3).joinToString(separator = ".", postfix = ".")
    }

    /**
     * The prefix a person meant, or null when the input is not a /24.
     *
     * Accepts `192.168.1`, `192.168.1.`, `192.168.1.0` and `192.168.1.0/24`.
     */
    fun parse(input: String): String? {
        val trimmed = input.trim().removeSuffix(".")
        val network = if (trimmed.count { it == '.' } == 3) {
            if (!SUFFIX.containsMatchIn(trimmed)) return null
            trimmed.replace(SUFFIX, "")
        } else {
            trimmed
        }
        val octets = network.split('.')
        if (octets.size != 3 || !octets.all(::isOctet)) return null
        return octets.joinToString(separator = ".", postfix = ".")
    }

    private fun isOctet(text: String): Boolean =
        text.isNotEmpty() && text.length <= 3 && text.all(Char::isDigit) && text.toInt() <= 255
}
