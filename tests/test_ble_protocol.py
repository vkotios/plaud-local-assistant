"""Phase 4 protocol / checksum / session-cipher fixtures (no live radio)."""

from __future__ import annotations

import os

import pytest

from localplaud.ble.protocol import (
    PLAUD_COMMAND,
    PlaudKeyChunks,
    build_download_request,
    build_handshake,
    build_pre_handshake_chunks,
    build_session_request,
    parse_note_pro_advertisement,
    parse_session_page,
)
from localplaud.ble.transfer_checksum import CRC16_VARIANTS, crc16, evaluate_tail_checksum


def test_parse_note_pro_advertisement_fixture():
    data = bytes.fromhex("5d000271030456000701088810000000000001441400040101")
    parsed = parse_note_pro_advertisement(data)
    assert parsed.project == 881
    assert parsed.serial == "8810000000000001"
    assert parsed.protocol_version == 20
    assert parsed.encrypted is True
    with pytest.raises(ValueError):
        parse_note_pro_advertisement(data[:21])
    bad = bytearray(data)
    bad[3] = 0
    with pytest.raises(ValueError):
        parse_note_pro_advertisement(bad)


def test_handshake_and_builders():
    packet = build_handshake("test-token", 20)
    assert packet[:6].hex() == "010100020000"
    assert packet[6:].decode("ascii") == "test-token".ljust(32, "0")
    assert len(build_handshake("x", 2)) == 21
    assert len(build_handshake("x", 3)) == 22
    assert build_session_request(request_id=7, cursor=100).hex() == (
        "011a00070000006400000000"
    )
    assert build_download_request(session_id=10, offset=20, end=30).hex() == (
        "011c000a000000140000001e000000"
    )
    with pytest.raises(ValueError):
        build_download_request(session_id=10, offset=30, end=20)
    with pytest.raises(ValueError):
        build_handshake("", 20)


def test_pre_handshake_chunks_and_reassembly():
    payload = os.urandom(256)
    chunks = build_pre_handshake_chunks(PLAUD_COMMAND["publicKey"], payload)
    assert [len(c) for c in chunks] == [104, 104, 60]
    assert chunks[0][:4].hex() == "12fe0300"
    collector = PlaudKeyChunks()
    assert collector.add(chunks[2]) is None
    assert collector.add(chunks[0]) is None
    assert collector.add(chunks[0]) is None
    assert collector.add(chunks[1]) == payload


def test_parse_session_page():
    packet = bytes.fromhex("011a0007000000030001000a000000640000002c02")
    page = parse_session_page(packet, 20)
    assert page.request_id == 7
    assert page.total == 3
    assert page.offset == 1
    assert page.entries[0].session_id == 10
    assert page.entries[0].size == 100
    assert page.entries[0].timezone == 44
    assert page.entries[0].scene == 2


def test_crc16_catalogue_check_values():
    sample = b"123456789"
    for variant in CRC16_VARIANTS:
        assert crc16(variant, sample) == variant["check"]


def test_tail_checksum_unconfirmed_never_rejects():
    data = b"fixture-bytes"
    result = evaluate_tail_checksum(data, tail_value=0x1234, confirmed=None)
    assert result.status == "unverified-algorithm"
    assert result.algorithm is None


def test_session_cipher_cryptokit_fixture():
    pytest.importorskip("cryptography")
    from localplaud.ble.session_cipher import PlaudSessionCipher

    material = (
        bytes([7] * 32)
        + bytes([3] * 12)
        + bytes([5] * 12)
        + bytes.fromhex("bbea0c32d2ba19b0fc2584562a17f81b2978a3b15c8bf8e4")
    )
    session = PlaudSessionCipher(material)
    plain = session.decrypt(bytes.fromhex("eaa64d67978e5840f3cd7315f9c4762025d028e0833515"))
    assert plain.hex() == "011a00"
    with pytest.raises(ValueError, match="verification|length"):
        PlaudSessionCipher(b"\x00" * 56)
