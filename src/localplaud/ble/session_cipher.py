"""ChaCha20-Poly1305 session cipher for Note Pro encrypted links.

Adapted from OpenPlod ``src/sync/plaud-session-cipher.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).

Requires the optional ``cryptography`` package (``pip install 'localplaud[ble]'``).
"""

from __future__ import annotations


class PlaudSessionCipher:
    def __init__(self, material: bytes | bytearray) -> None:
        raw = bytes(material)
        if len(raw) != 80:
            raise ValueError(f"Invalid Plaud session material length ({len(raw)})")
        self._key = bytearray(raw[0:32])
        self._nonce = bytearray(raw[32:44])
        self._associated_data = bytearray(raw[44:56])
        self._send_counter = 1
        self._receive_counter = -1
        self._closed = False
        try:
            if self._open(raw[56:]) != b"PLAUD.AI":
                raise ValueError("Invalid device key verification marker")
        except Exception as exc:
            self.destroy()
            raise ValueError("Plaud key-exchange verification failed") from exc

    def _aead(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
        except ImportError as exc:  # pragma: no cover - exercised when extra missing
            raise RuntimeError(
                "BLE session crypto requires cryptography; install localplaud[ble]"
            ) from exc
        return ChaCha20Poly1305(bytes(self._key))

    def _open(self, ciphertext: bytes | bytearray) -> bytes:
        if self._closed or len(ciphertext) < 16:
            raise ValueError("Invalid encrypted Plaud packet")
        return self._aead().decrypt(
            bytes(self._nonce), bytes(ciphertext), bytes(self._associated_data)
        )

    def encrypt(self, packet: bytes | bytearray) -> bytes:
        if self._closed or len(packet) < 3 or self._send_counter >= 0xFFFFFFFF:
            raise ValueError("Plaud session unavailable")
        self._send_counter += 1
        counter = self._send_counter.to_bytes(4, "little")
        plaintext = counter + bytes(packet)
        return self._aead().encrypt(
            bytes(self._nonce), plaintext, bytes(self._associated_data)
        )

    def decrypt(self, packet: bytes | bytearray) -> bytes:
        plaintext = self._open(packet)
        if len(plaintext) < 7:
            raise ValueError("Truncated encrypted Plaud response")
        counter = int.from_bytes(plaintext[0:4], "little")
        if counter <= self._receive_counter:
            raise ValueError("Replayed or out-of-order Plaud response")
        self._receive_counter = counter
        return plaintext[4:]

    def destroy(self) -> None:
        self._closed = True
        for buf in (self._key, self._nonce, self._associated_data):
            for i in range(len(buf)):
                buf[i] = 0
