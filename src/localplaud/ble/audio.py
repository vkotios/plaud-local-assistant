"""Encrypted Plaud audio header parse + Ogg integrity + ChaCha20 decode.

Adapted from OpenPlod ``src/sync/plaud-audio.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

RsaUnwrap = Callable[[bytes], bytes]


@dataclass(frozen=True)
class PlaudAudioHeader:
    channels: int
    counter: int
    nonce: bytes
    encrypted_key: bytes
    payload: bytes


def parse_plaud_audio_header(data: bytes | bytearray) -> PlaudAudioHeader:
    raw = bytes(data)
    if (
        len(raw) <= 512
        or raw[0:8] != b"PLAUD.AI"
        or int.from_bytes(raw[8:10], "little") != 1
        or int.from_bytes(raw[10:12], "little") != 512
        or int.from_bytes(raw[48:50], "little") != 1
        or int.from_bytes(raw[52:54], "little") != 1
    ):
        raise ValueError("Unsupported Plaud audio header")
    channels = int.from_bytes(raw[50:52], "little")
    if channels < 1 or channels > 2:
        raise ValueError("Unsupported Plaud audio channels")
    return PlaudAudioHeader(
        channels=channels,
        counter=int.from_bytes(raw[128:132], "little"),
        nonce=raw[132:144],
        encrypted_key=raw[256:512],
        payload=raw[512:],
    )


def ogg_crc(data: bytes | bytearray) -> int:
    crc = 0
    for byte in data:
        crc = (crc ^ (byte << 24)) & 0xFFFFFFFF
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


@dataclass(frozen=True)
class OggIntegrity:
    pages: int
    streams: int
    channels: int


def validate_ogg_audio(data: bytes | bytearray, expected_channels: int) -> OggIntegrity:
    raw = bytes(data)
    streams: dict[int, dict] = {}
    offset = 0
    pages = 0
    opus = False
    while offset < len(raw):
        if (
            offset + 27 > len(raw)
            or raw[offset : offset + 4] != b"OggS"
            or raw[offset + 4] != 0
        ):
            raise ValueError("Truncated or invalid Ogg page")
        segments = raw[offset + 26]
        header_end = offset + 27 + segments
        if header_end > len(raw):
            raise ValueError("Truncated Ogg segment table")
        length = sum(raw[offset + 27 : header_end])
        end = header_end + length
        if end > len(raw):
            raise ValueError("Incomplete Ogg payload")
        page = bytearray(raw[offset:end])
        checksum = int.from_bytes(page[22:26], "little")
        page[22:26] = b"\x00\x00\x00\x00"
        if ogg_crc(page) != checksum:
            raise ValueError("Ogg checksum mismatch")
        serial = int.from_bytes(page[14:18], "little")
        sequence = int.from_bytes(page[18:22], "little")
        flags = page[5]
        previous = streams.get(serial)
        if (not previous and (sequence != 0 or not (flags & 2))) or (
            previous
            and (previous["ended"] or sequence != previous["sequence"] + 1 or (flags & 2))
        ):
            raise ValueError("Discontinuous Ogg stream")
        streams[serial] = {"sequence": sequence, "ended": bool(flags & 4)}
        if not previous and raw[header_end : header_end + 8] == b"OpusHead":
            if length < 19 or raw[header_end + 9] != expected_channels:
                raise ValueError("Opus channel mismatch")
            opus = True
        pages += 1
        offset = end
    if not opus or not streams or any(not stream["ended"] for stream in streams.values()):
        raise ValueError("Incomplete Opus recording")
    return OggIntegrity(pages=pages, streams=len(streams), channels=expected_channels)


def _chacha20_xor(key: bytes, nonce: bytes, counter: int, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "BLE audio decode requires cryptography; install localplaud[ble]"
        ) from exc
    # cryptography ChaCha20 uses a 16-byte nonce = counter(4 LE) || nonce(12)
    full_nonce = counter.to_bytes(4, "little") + nonce
    encryptor = Cipher(algorithms.ChaCha20(key, full_nonce), mode=None).encryptor()
    return encryptor.update(data) + encryptor.finalize()


@dataclass(frozen=True)
class DecodedPlaudAudio:
    audio: bytes
    integrity: OggIntegrity


def decode_plaud_audio(data: bytes | bytearray, unwrap: RsaUnwrap) -> DecodedPlaudAudio:
    header = parse_plaud_audio_header(data)
    key = bytearray(unwrap(header.encrypted_key))
    try:
        if len(key) != 32:
            raise ValueError("Plaud audio key does not match the authorized identity")
        if header.counter != 0:
            raise ValueError("Unsupported Plaud audio counter")
        audio = _chacha20_xor(bytes(key), header.nonce, 0, header.payload)
        integrity = validate_ogg_audio(audio, header.channels)
        return DecodedPlaudAudio(audio=audio, integrity=integrity)
    finally:
        for i in range(len(key)):
            key[i] = 0
