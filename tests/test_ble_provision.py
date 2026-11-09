"""Phase 4 provision + identity storage (mocked network; no live secrets)."""

from __future__ import annotations

import base64
import json
import os

import pytest

from localplaud.ble.identity import (
    clear_stored_identity,
    read_stored_identity,
    write_stored_identity,
)
from localplaud.ble.provision import (
    PlaudIdentityProvisioner,
    device_type_for_serial,
    normalize_access_token,
    parse_access_token,
    provision_device,
)

SERIAL = "8810B50327175322"
MAC = "C4:96:9D:11:27:21"
BINDING_TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"


def _token(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{body}.signature"


def test_normalize_access_token_shapes():
    assert normalize_access_token("  abc.def.ghi  ") == "abc.def.ghi"
    assert normalize_access_token('"abc.def.ghi"') == "abc.def.ghi"
    assert normalize_access_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert normalize_access_token(json.dumps({"tokenstr": "abc.def.ghi"})) == "abc.def.ghi"
    assert normalize_access_token(json.dumps({"access_token": "abc.def.ghi"})) == "abc.def.ghi"


def test_parse_access_token_claims():
    claims = parse_access_token(
        _token(
            {
                "sub": BINDING_TOKEN,
                "user_id": "user-7",
                "client_id": "plaud-web",
                "exp": 1_700_000_000,
            }
        )
    )
    assert claims.sub == BINDING_TOKEN
    assert claims.user_id == "user-7"
    assert claims.client_id == "plaud-web"
    assert claims.expires_at == 1_700_000_000_000
    assert parse_access_token(_token({"sub": BINDING_TOKEN})).user_id == BINDING_TOKEN


def test_parse_access_token_rejects_bad_input():
    with pytest.raises(ValueError, match="does not look like"):
        parse_access_token("not-a-jwt")
    with pytest.raises(ValueError, match="binding token"):
        parse_access_token(_token({"user_id": "user-7"}))
    with pytest.raises(ValueError, match="binding token"):
        parse_access_token(_token({"sub": "has spaces here"}))


def test_device_type_for_serial():
    assert device_type_for_serial("8800000000000000") == "notepin"
    assert device_type_for_serial("8810B50327175322") == "notepro"
    assert device_type_for_serial("8820000000000000") == "notepins"
    assert device_type_for_serial("8830000000000000") == "notepro"
    assert device_type_for_serial("8890000000000000") == "note"
    with pytest.raises(ValueError, match="serial number"):
        device_type_for_serial("8810b50327175322")


def test_provisioner_mints_identity_with_mocked_http():
    requests: list[dict] = []

    def fetcher(url: str, init: dict):
        requests.append({"url": url, "init": init})
        if "gen-key" in url:
            return {"public_key": "PUBLIC", "private_key": "PRIVATE"}
        if "sn-sign" in url:
            return {"signature": "SIGNATURE"}
        raise AssertionError(url)

    provisioner = PlaudIdentityProvisioner(fetcher)
    access = _token({"sub": BINDING_TOKEN, "user_id": "u1"})
    identity = provisioner.provision(token=access, serial=SERIAL, identifier=MAC)
    assert identity["bindingToken"] == BINDING_TOKEN
    assert identity["publicKey"] == "PUBLIC"
    assert identity["privateKey"] == "PRIVATE"
    assert identity["signature"] == "SIGNATURE"
    assert identity["deviceType"] == "notepro"
    paths = [item["url"].split("plaud.ai", 1)[1] for item in requests]
    assert paths == [
        "/developer/api/open/partner/sdk/gen-key",
        "/developer/api/open/partner/sdk/sn-sign",
    ]
    assert all(
        item["init"]["headers"]["Authorization"] == f"Bearer {access}" for item in requests
    )
    assert json.loads(requests[1]["init"]["body"]) == {"type": "notepro", "sn": SERIAL}


def test_provisioner_maps_token_rejection():
    def fetcher(url: str, init: dict):
        raise ValueError(
            "Plaud rejected the sign-in token. Sign in again and paste a fresh token."
        )

    # Simulate _post error path via generate_key_pair raising from fetcher returning error
    provisioner = PlaudIdentityProvisioner(
        lambda url, init: (_ for _ in ()).throw(
            ValueError(
                "Plaud rejected the sign-in token. Sign in again and paste a fresh token."
            )
        )
    )
    with pytest.raises(ValueError, match="rejected the sign-in token"):
        provisioner.provision(
            token=_token({"sub": BINDING_TOKEN}), serial=SERIAL, identifier=MAC
        )


def test_provisioner_rejects_non_bluetooth_identifier():
    provisioner = PlaudIdentityProvisioner(lambda url, init: {})
    with pytest.raises(ValueError, match="Bluetooth address"):
        provisioner.provision(
            token=_token({"sub": BINDING_TOKEN}),
            serial=SERIAL,
            identifier="not-an-address",
        )


def test_identity_roundtrip_owner_mode(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "plaud-device.json"
    monkeypatch.setenv("OPENPLOD_DEVICE_IDENTITY", str(path))
    identity = {
        "identifier": MAC,
        "serial": SERIAL,
        "bindingToken": BINDING_TOKEN,
        "signature": "SIGNATURE",
        "publicKey": "PUBLIC",
        "privateKey": "PRIVATE",
    }
    written = write_stored_identity(identity)
    assert written == path.resolve()
    assert read_stored_identity() == identity
    assert json.loads(path.read_text(encoding="utf-8")) == identity
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0
    assert clear_stored_identity() is True
    assert read_stored_identity() is None
    assert clear_stored_identity() is False


def test_provision_device_writes_file(tmp_path, monkeypatch):
    path = tmp_path / "plaud-device.json"
    monkeypatch.setenv("LOCALPLAUD_BLE__IDENTITY_PATH", str(path))

    def fetcher(url: str, init: dict):
        if "gen-key" in url:
            return {"public_key": "PUBLIC", "private_key": "PRIVATE"}
        return {"signature": "SIGNATURE"}

    identity = provision_device(
        token=_token({"sub": BINDING_TOKEN}),
        serial=SERIAL,
        identifier=MAC,
        provisioner=PlaudIdentityProvisioner(fetcher),
        identity_path=str(path),
    )
    assert path.is_file()
    assert "PRIVATE" not in path.name
    loaded = read_stored_identity(path)
    assert loaded is not None
    assert loaded["serial"] == SERIAL
    # Ensure secrets are on disk but tests never print them.
    assert loaded["privateKey"] == identity["privateKey"] == "PRIVATE"
