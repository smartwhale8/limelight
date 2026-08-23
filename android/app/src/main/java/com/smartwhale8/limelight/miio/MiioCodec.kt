package com.smartwhale8.limelight.miio

import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * miIO packet framing and cryptography.
 *
 * A miIO datagram is a 32-byte header followed by an optionally encrypted JSON payload:
 *
 * ```
 *  offset  size  field
 *  ------  ----  ----------------------------------------------------------
 *       0     2  magic, always 0x2131
 *       2     2  total packet length, header included, big-endian
 *       4     4  unknown, zero in practice
 *       8     4  device id, big-endian
 *      12     4  uptime stamp, seconds since the device booted
 *      16    16  MD5 checksum, or the token during a handshake
 *      32     n  encrypted payload, absent on a handshake
 * ```
 *
 * The token is never transmitted. It seeds the encryption:
 *
 * ```
 * key = md5(token)
 * iv  = md5(key + token)
 * payload = AES-128-CBC(key, iv, json)   // PKCS#5/7 padding
 * checksum = md5(header[0..16] + token + payload)
 * ```
 *
 * Everything here uses `javax.crypto` and `java.nio` from the standard library, so the
 * app carries no third-party dependency. It is a direct port of the behaviour verified
 * against the hardware by the Python implementation in this repository; see
 * `docs/PROTOCOL.md`.
 */
object MiioCodec {

    const val PORT = 54321
    const val HEADER_SIZE = 32
    private const val MAGIC = 0x2131

    /** Marker occupying the checksum field of a handshake, and of a withheld token. */
    private val FILLER_FF = ByteArray(16) { 0xFF.toByte() }
    private val FILLER_00 = ByteArray(16)

    /**
     * The handshake packet: a header with no payload and a checksum field of 0xFF bytes.
     *
     * No credential is involved, which is what makes discovery possible and is also how a
     * token is recovered from firmware that discloses one.
     */
    val HELLO: ByteArray = ByteBuffer.allocate(HEADER_SIZE).order(ByteOrder.BIG_ENDIAN).apply {
        putShort(MAGIC.toShort())
        putShort(HEADER_SIZE.toShort())
        put(FILLER_FF, 0, 4)   // unknown field, 0xFF in a hello
        put(FILLER_FF, 0, 4)   // device id, unknown at this point
        put(FILLER_FF, 0, 4)   // stamp, unknown at this point
        put(FILLER_FF)         // checksum slot
    }.array()

    /** A decoded handshake reply. [token] is null when the firmware withholds it. */
    data class Handshake(
        val deviceId: Long,
        val stamp: Long,
        val token: String?,
    ) {
        val tokenDisclosed: Boolean get() = token != null
    }

    /** A decoded command reply. */
    data class Packet(
        val deviceId: Long,
        val stamp: Long,
        val payload: ByteArray,
    ) {
        // ByteArray needs explicit equality; the generated one compares references.
        override fun equals(other: Any?): Boolean =
            this === other || (other is Packet && deviceId == other.deviceId &&
                stamp == other.stamp && payload.contentEquals(other.payload))

        override fun hashCode(): Int =
            (deviceId.hashCode() * 31 + stamp.hashCode()) * 31 + payload.contentHashCode()
    }

    // ------------------------------------------------------------------ parsing

    /** True when [data] looks like a miIO datagram rather than some other traffic. */
    fun isMiioPacket(data: ByteArray, length: Int): Boolean =
        length >= HEADER_SIZE &&
            (data[0].toInt() and 0xFF) == 0x21 &&
            (data[1].toInt() and 0xFF) == 0x31

    /**
     * Decode a handshake reply. Returns null if the datagram is not a miIO packet.
     *
     * Bytes 16 to 32 hold the token when the firmware discloses it, and a filler of all
     * 0xFF or all 0x00 when it does not.
     */
    fun parseHandshake(data: ByteArray, length: Int): Handshake? {
        if (!isMiioPacket(data, length)) return null
        val buf = ByteBuffer.wrap(data, 0, length).order(ByteOrder.BIG_ENDIAN)
        buf.position(8)
        val deviceId = buf.int.toLong() and 0xFFFFFFFFL
        val stamp = buf.int.toLong() and 0xFFFFFFFFL
        val tokenBytes = ByteArray(16)
        buf.get(tokenBytes)
        val disclosed = !tokenBytes.contentEquals(FILLER_FF) && !tokenBytes.contentEquals(FILLER_00)
        return Handshake(deviceId, stamp, if (disclosed) tokenBytes.toHex() else null)
    }

    // ------------------------------------------------------------------ building

    /**
     * Build an encrypted command datagram.
     *
     * @param json the JSON-RPC request body
     * @param token the 32-character hexadecimal device token
     * @param deviceId from the handshake
     * @param stamp the device's uptime, which must be close to its own clock; callers
     *   derive it from the handshake plus elapsed local time
     */
    fun buildCommand(json: String, token: String, deviceId: Long, stamp: Long): ByteArray {
        val tokenBytes = token.hexToBytes()
        require(tokenBytes.size == 16) { "a miIO token is 32 hexadecimal characters" }

        // The reference implementation null-terminates the JSON before encrypting, and
        // the firmware is written against that. Verified by decrypting a python-miio
        // packet: its plaintext is the JSON followed by a single 0x00.
        val payload = encrypt(json.toByteArray(Charsets.UTF_8) + 0.toByte(), tokenBytes)
        val total = HEADER_SIZE + payload.size

        // Build the header with the token occupying the checksum slot, hash the whole
        // thing, then overwrite that slot with the digest.
        val packet = ByteBuffer.allocate(total).order(ByteOrder.BIG_ENDIAN).apply {
            putShort(MAGIC.toShort())
            putShort(total.toShort())
            putInt(0)                       // unknown
            putInt(deviceId.toInt())
            putInt(stamp.toInt())
            put(tokenBytes)                 // replaced by the checksum below
            put(payload)
        }.array()

        val checksum = md5(packet)
        System.arraycopy(checksum, 0, packet, 16, 16)
        return packet
    }

    /**
     * Decode and decrypt a command reply, returning the JSON body.
     *
     * A reply with no payload means the device answered a handshake instead, which
     * happens when it has decided to re-handshake; callers treat that as a retry.
     */
    fun decodeReply(data: ByteArray, length: Int, token: String): String? {
        if (!isMiioPacket(data, length) || length <= HEADER_SIZE) return null
        val payload = data.copyOfRange(HEADER_SIZE, length)
        val plain = decrypt(payload, token.hexToBytes())
        // Replies carry the same trailing null terminator; strip it before parsing.
        return String(plain, Charsets.UTF_8).trimEnd('\u0000')
    }

    /** Read the device id and stamp from any miIO datagram. */
    fun parseHeader(data: ByteArray, length: Int): Packet? {
        if (!isMiioPacket(data, length)) return null
        val buf = ByteBuffer.wrap(data, 0, length).order(ByteOrder.BIG_ENDIAN)
        buf.position(8)
        val deviceId = buf.int.toLong() and 0xFFFFFFFFL
        val stamp = buf.int.toLong() and 0xFFFFFFFFL
        val payload =
            if (length > HEADER_SIZE) data.copyOfRange(HEADER_SIZE, length) else ByteArray(0)
        return Packet(deviceId, stamp, payload)
    }

    // ---------------------------------------------------------------- crypto

    private fun cipher(mode: Int, token: ByteArray): Cipher {
        val key = md5(token)
        val iv = md5(key + token)
        return Cipher.getInstance("AES/CBC/PKCS5Padding").apply {
            init(mode, SecretKeySpec(key, "AES"), IvParameterSpec(iv))
        }
    }

    private fun encrypt(plain: ByteArray, token: ByteArray): ByteArray =
        cipher(Cipher.ENCRYPT_MODE, token).doFinal(plain)

    private fun decrypt(encrypted: ByteArray, token: ByteArray): ByteArray =
        cipher(Cipher.DECRYPT_MODE, token).doFinal(encrypted)

    private fun md5(vararg parts: ByteArray): ByteArray =
        MessageDigest.getInstance("MD5").apply { parts.forEach { update(it) } }.digest()
}

// -------------------------------------------------------------------- hex helpers

/** Lowercase hexadecimal, as tokens are always written. */
fun ByteArray.toHex(): String =
    joinToString("") { "%02x".format(it) }

/** Parse hexadecimal, tolerating spaces, colons and case. */
fun String.hexToBytes(): ByteArray {
    val clean = filter { !it.isWhitespace() && it != ':' && it != '-' }
    require(clean.length % 2 == 0) { "hexadecimal input must have an even number of digits" }
    return ByteArray(clean.length / 2) { i ->
        clean.substring(i * 2, i * 2 + 2).toInt(16).toByte()
    }
}

/** True when the string is exactly 32 hexadecimal characters, the shape of a token. */
fun String.isValidToken(): Boolean =
    length == 32 && all { it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' }
