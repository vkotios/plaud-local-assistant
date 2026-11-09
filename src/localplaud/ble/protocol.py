"""Note Pro BLE framing (protocol 20).

Adapted from OpenPlod ``src/sync/plaud-protocol.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).
Interoperability framing verified against APK builders/parsers upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

PLAUD_COMMAND = {
    "handshake": 1,
    "sessions": 26,
    "download": 28,
    "tail": 29,
    "signature": 0xFE10,
    "signatureAccepted": 0xFE11,
    "publicKey": 0xFE12,
}


def _u16_le(value: int) -> bytes:
    return int(value).to_bytes(2, "little", signed=False)


def _u32_le(value: int) -> bytes:
    if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
        raise ValueError("Invalid unsigned integer")
    return value.to_bytes(4, "little", signed=False)


def _command(command_id: int, payload: bytes) -> bytes:
    return bytes([1]) + _u16_le(command_id) + payload


@dataclass(frozen=True)
class NoteProAdvertisement:
    project: int
    serial: str
    protocol_version: int
    encrypted: bool


def parse_note_pro_advertisement(data: bytes | bytearray) -> NoteProAdvertisement:
    raw = bytes(data)
    if len(raw) < 22 or raw[2] != 2 or raw[5] != 4 or raw[10] != 8:
        raise ValueError("Unsupported or truncated Note Pro advertisement")
    project = int.from_bytes(raw[3:5], "little")
    if project not in (881, 883):
        raise ValueError("Not a supported Note Pro project")
    serial = raw[11:19].hex().upper()
    protocol_version = int.from_bytes(raw[20:22], "little")
    return NoteProAdvertisement(
        project=project,
        serial=serial,
        protocol_version=protocol_version,
        encrypted=protocol_version >= 20,
    )


def build_handshake(binding_token: str, protocol_version: int) -> bytes:
    if not binding_token or not all(0x21 <= ord(ch) <= 0x7E for ch in binding_token):
        raise ValueError("A nonempty ASCII device binding token is required")
    if not isinstance(protocol_version, int) or protocol_version < 1:
        raise ValueError("Invalid protocol version")
    token_length = 32 if protocol_version >= 9 else 16
    token = (binding_token[:token_length].ljust(token_length, "0")).encode("ascii")
    options = bytes([2, 0, 0]) if protocol_version >= 3 else bytes([2, 0])
    return _command(PLAUD_COMMAND["handshake"], options + token)


def build_session_request(*, request_id: int, cursor: int, ascending: bool = False) -> bytes:
    return _command(
        PLAUD_COMMAND["sessions"],
        _u32_le(request_id) + _u32_le(cursor) + bytes([1 if ascending else 0]),
    )


def build_download_request(*, session_id: int, offset: int, end: int) -> bytes:
    if offset >= end:
        raise ValueError("Download range must be nonempty")
    return _command(
        PLAUD_COMMAND["download"],
        _u32_le(session_id) + _u32_le(offset) + _u32_le(end),
    )


def build_pre_handshake_chunks(opcode: int, payload: bytes | bytearray) -> list[bytes]:
    supported = {PLAUD_COMMAND["signature"], PLAUD_COMMAND["publicKey"]}
    if opcode not in supported:
        raise ValueError("Unsupported pre-handshake command")
    data = bytes(payload)
    total = (len(data) + 99) // 100
    if total < 1 or total > 255:
        raise ValueError("Invalid pre-handshake payload size")
    chunks: list[bytes] = []
    for index in range(total):
        header = _u16_le(opcode) + bytes([total, index])
        chunks.append(header + data[index * 100 : (index + 1) * 100])
    return chunks


class PlaudKeyChunks:
    def __init__(self) -> None:
        self._total: int | None = None
        self._chunks: dict[int, bytes] = {}

    def add(self, packet: bytes | bytearray) -> bytes | None:
        raw = bytes(packet)
        if (
            len(raw) < 5
            or len(raw) > 104
            or int.from_bytes(raw[0:2], "little") != PLAUD_COMMAND["publicKey"]
        ):
            raise ValueError("Invalid key-exchange packet")
        total, index = raw[2], raw[3]
        if total == 0 or total > 3 or index >= total or (
            self._total is not None and total != self._total
        ):
            raise ValueError("Inconsistent RSA-2048 key-exchange chunks")
        payload = raw[4:]
        prior = self._chunks.get(index)
        if prior is not None and prior != payload:
            raise ValueError("Conflicting key chunk")
        self._total = total
        self._chunks[index] = payload
        if len(self._chunks) != total:
            return None
        result = b"".join(self._chunks[i] for i in range(total))
        if len(result) != 256:
            raise ValueError("Invalid RSA-2048 ciphertext size")
        return result


@dataclass(frozen=True)
class PlaudSessionEntry:
    session_id: int
    size: int
    scene: int
    timezone: int


@dataclass(frozen=True)
class SessionPage:
    request_id: int
    total: int
    offset: int
    entries: list[PlaudSessionEntry]


def parse_session_page(packet: bytes | bytearray, protocol_version: int) -> SessionPage:
    raw = bytes(packet)
    if (
        len(raw) < 11
        or raw[0] != 1
        or int.from_bytes(raw[1:3], "little") != PLAUD_COMMAND["sessions"]
    ):
        raise ValueError("Invalid recording-list response")
    if not isinstance(protocol_version, int) or protocol_version < 1:
        raise ValueError("Invalid protocol version")
    stride = 8 if protocol_version == 1 else 9 if protocol_version < 7 else 10
    total = int.from_bytes(raw[7:9], "little")
    offset = int.from_bytes(raw[9:11], "little")
    body = raw[11:]
    if len(body) % stride != 0 or offset + (len(body) // stride) > total:
        raise ValueError("Truncated or inconsistent recording-list page")
    entries: list[PlaudSessionEntry] = []
    for start in range(0, len(body), stride):
        chunk = body[start : start + stride]
        entries.append(
            PlaudSessionEntry(
                session_id=int.from_bytes(chunk[0:4], "little"),
                size=int.from_bytes(chunk[4:8], "little"),
                scene=0 if stride == 8 else chunk[stride - 1],
                timezone=chunk[8] if stride == 10 else 0,
            )
        )
    return SessionPage(
        request_id=int.from_bytes(raw[3:7], "little"),
        total=total,
        offset=offset,
        entries=entries,
    )
