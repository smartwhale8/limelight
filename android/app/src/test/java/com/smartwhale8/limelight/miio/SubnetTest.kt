package com.smartwhale8.limelight.miio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SubnetTest {

    @Test
    fun `scanOrder puts Wi-Fi first and VPN last`() {
        val vpn = ScanTarget(NetworkKind.VPN, "10.14.0.")
        val wifi = ScanTarget(NetworkKind.WIFI, "192.168.1.")
        val ethernet = ScanTarget(NetworkKind.ETHERNET, "192.168.2.")
        assertEquals(listOf(wifi, ethernet, vpn), Subnet.scanOrder(listOf(vpn, ethernet, wifi)))
    }

    @Test
    fun `scanOrder keeps Wi-Fi when a VPN reports the same subnet`() {
        val vpn = ScanTarget(NetworkKind.VPN, "192.168.1.")
        val wifi = ScanTarget(NetworkKind.WIFI, "192.168.1.")
        assertEquals(listOf(wifi), Subnet.scanOrder(listOf(vpn, wifi)))
    }

    @Test
    fun `cidr names the whole subnet`() {
        assertEquals("10.14.0.0/24", ScanTarget(NetworkKind.VPN, "10.14.0.").cidr)
    }

    @Test
    fun `prefixOf keeps the first three octets and the trailing dot`() {
        assertEquals("192.168.1.", Subnet.prefixOf("192.168.1.155"))
    }

    @Test
    fun `prefixOf rejects text that is not an IPv4 address`() {
        assertNull(Subnet.prefixOf("fe80::1"))
        assertNull(Subnet.prefixOf("192.168.1"))
        assertNull(Subnet.prefixOf("192.168.1.256"))
    }

    @Test
    fun `parse accepts every written form of the same subnet`() {
        listOf("192.168.1", "192.168.1.", "192.168.1.0", "192.168.1.0/24", " 192.168.1.0 ")
            .forEach { assertEquals(it, "192.168.1.", Subnet.parse(it)) }
    }

    @Test
    fun `parse rejects a host address`() {
        assertNull(Subnet.parse("192.168.1.42"))
    }

    @Test
    fun `parse rejects masks other than 24`() {
        assertNull(Subnet.parse("192.168.1.0/16"))
    }

    @Test
    fun `parse rejects out of range and malformed input`() {
        assertNull(Subnet.parse(""))
        assertNull(Subnet.parse("192.168"))
        assertNull(Subnet.parse("192.168.300"))
        assertNull(Subnet.parse("lamp"))
    }
}
