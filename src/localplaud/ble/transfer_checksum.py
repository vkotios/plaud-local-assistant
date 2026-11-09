"""Transfer-tail CRC evidence (algorithm unconfirmed).

Adapted from OpenPlod ``src/sync/transfer-checksum.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).

Never reject a transfer on an unconfirmed algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Crc16Variant = dict  # name/poly/init/refIn/refOut/xorOut/check

CRC16_VARIANTS: list[dict] = [
    {"name": "CRC-16/CCITT-FALSE", "poly": 0x1021, "init": 0xFFFF, "refIn": False, "refOut": False, "xorOut": 0x0000, "check": 0x29B1},
    {"name": "CRC-16/XMODEM", "poly": 0x1021, "init": 0x0000, "refIn": False, "refOut": False, "xorOut": 0x0000, "check": 0x31C3},
    {"name": "CRC-16/KERMIT", "poly": 0x1021, "init": 0x0000, "refIn": True, "refOut": True, "xorOut": 0x0000, "check": 0x2189},
    {"name": "CRC-16/X-25", "poly": 0x1021, "init": 0xFFFF, "refIn": True, "refOut": True, "xorOut": 0xFFFF, "check": 0x906E},
    {"name": "CRC-16/MCRF4XX", "poly": 0x1021, "init": 0xFFFF, "refIn": True, "refOut": True, "xorOut": 0x0000, "check": 0x6F91},
    {"name": "CRC-16/GENIBUS", "poly": 0x1021, "init": 0xFFFF, "refIn": False, "refOut": False, "xorOut": 0xFFFF, "check": 0xD64E},
    {"name": "CRC-16/SPI-FUJITSU", "poly": 0x1021, "init": 0x1D0F, "refIn": False, "refOut": False, "xorOut": 0x0000, "check": 0xE5CC},
    {"name": "CRC-16/MODBUS", "poly": 0x8005, "init": 0xFFFF, "refIn": True, "refOut": True, "xorOut": 0x0000, "check": 0x4B37},
    {"name": "CRC-16/ARC", "poly": 0x8005, "init": 0x0000, "refIn": True, "refOut": True, "xorOut": 0x0000, "check": 0xBB3D},
    {"name": "CRC-16/USB", "poly": 0x8005, "init": 0xFFFF, "refIn": True, "refOut": True, "xorOut": 0xFFFF, "check": 0xB4C8},
    {"name": "CRC-16/UMTS", "poly": 0x8005, "init": 0x0000, "refIn": False, "refOut": False, "xorOut": 0x0000, "check": 0xFEE8},
]

CONFIRMED_TAIL_ALGORITHM: str | None = None

_tables: dict[str, list[int]] = {}


def _reflect(value: int, bits: int) -> int:
    out = 0
    for i in range(bits):
        if value & (1 << i):
            out |= 1 << (bits - 1 - i)
    return out


def _table(variant: dict) -> list[int]:
    cached = _tables.get(variant["name"])
    if cached is not None:
        return cached
    poly = _reflect(variant["poly"], 16) if variant["refIn"] else variant["poly"]
    result = [0] * 256
    for n in range(256):
        crc = n if variant["refIn"] else (n << 8)
        for _ in range(8):
            if variant["refIn"]:
                crc = ((crc >> 1) ^ poly) if (crc & 1) else (crc >> 1)
            else:
                crc = (((crc << 1) ^ poly) if (crc & 0x8000) else (crc << 1)) & 0xFFFF
        result[n] = crc & 0xFFFF
    _tables[variant["name"]] = result
    return result


def crc16(variant: dict, data: bytes | bytearray) -> int:
    lookup = _table(variant)
    crc = _reflect(variant["init"], 16) if variant["refIn"] else variant["init"]
    if variant["refIn"]:
        for byte in data:
            crc = (crc >> 8) ^ lookup[(crc ^ byte) & 0xFF]
    else:
        for byte in data:
            crc = ((crc << 8) & 0xFFFF) ^ lookup[((crc >> 8) ^ byte) & 0xFF]
    if variant["refIn"] != variant["refOut"]:
        crc = _reflect(crc, 16)
    return (crc ^ variant["xorOut"]) & 0xFFFF


@dataclass(frozen=True)
class TailChecksumResult:
    status: Literal["verified", "mismatch", "unverified-algorithm"]
    algorithm: str | None
    tail_value: int
    candidate_matches: list[dict]


def _swap16(value: int) -> int:
    return ((value & 0xFF) << 8) | (value >> 8)


def evaluate_tail_checksum(
    data: bytes | bytearray,
    tail_value: int,
    confirmed: str | None = CONFIRMED_TAIL_ALGORITHM,
) -> TailChecksumResult:
    matches: list[dict] = []
    for variant in CRC16_VARIANTS:
        value = crc16(variant, data)
        if value == tail_value:
            matches.append({"algorithm": variant["name"], "byteOrder": "le"})
        elif _swap16(value) == tail_value:
            matches.append({"algorithm": variant["name"], "byteOrder": "be"})
    if not confirmed:
        return TailChecksumResult(
            status="unverified-algorithm",
            algorithm=None,
            tail_value=tail_value,
            candidate_matches=matches,
        )
    variant = next((item for item in CRC16_VARIANTS if item["name"] == confirmed), None)
    if variant is None:
        raise ValueError(f"Unknown confirmed transfer checksum algorithm {confirmed}")
    status: Literal["verified", "mismatch"] = (
        "verified" if crc16(variant, data) == tail_value else "mismatch"
    )
    return TailChecksumResult(
        status=status,
        algorithm=variant["name"],
        tail_value=tail_value,
        candidate_matches=matches,
    )
