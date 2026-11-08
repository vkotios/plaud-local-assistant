"""Phase 4 BLE → Phase 3 ingest dedupe (fixtures; no live radio/secrets)."""

from __future__ import annotations

import wave
from io import BytesIO
from pathlib import Path

from localplaud.ble.doctor import ble_doctor_status
from localplaud.ble.redact import identity_public_view, redact_serial
from localplaud.ble.service import BleIngestRequest, ingest_decoded_session
from localplaud.ingest.types import ble_external_id


def _reset_db(monkeypatch, tmp_path, *, enabled: str = "true", dedupe_mode: str = "link"):
    import localplaud.db.session as db_session
    from localplaud.config import get_settings

    monkeypatch.setenv("LOCALPLAUD_STORE__DATABASE_URL", f"sqlite:///{tmp_path / 'ble-ingest.db'}")
    monkeypatch.setenv("LOCALPLAUD_POLLER__DOWNLOAD_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("LOCALPLAUD_INGEST__ENABLED", enabled)
    monkeypatch.setenv("LOCALPLAUD_INGEST__DEDUPE_MODE", dedupe_mode)
    monkeypatch.setenv("LOCALPLAUD_BLE__ENABLED", "true")
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_Session", None)
    return get_settings(reload=True)


def _write_wav(path: Path, *, frames: int = 800, sample: bytes = b"\x00\x00") -> Path:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as fixture:
        fixture.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        fixture.writeframes(sample * frames)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())
    return path


def test_ble_external_id_shape():
    assert ble_external_id("8810B50327175322", "42") == "8810B50327175322:42"


def test_redaction_never_echoes_full_serial():
    assert redact_serial("8810B50327175322") == "881…22"
    view = identity_public_view(
        {
            "serial": "8810B50327175322",
            "identifier": "C4:96:9D:11:27:21",
            "bindingToken": "SECRET",
            "privateKey": "PRIVATE",
            "publicKey": "PUBLIC",
            "signature": "SIG",
            "deviceType": "notepro",
        }
    )
    assert view is not None
    assert "8810B50327175322" not in view["serial"]
    assert "PRIVATE" not in str(view)
    assert "SECRET" not in str(view)
    assert view["hasPrivateKey"] is True


def test_doctor_status_is_redacted_and_experimental(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALPLAUD_BLE__ENABLED", "false")
    monkeypatch.setenv("LOCALPLAUD_BLE__IDENTITY_PATH", str(tmp_path / "missing.json"))
    report = ble_doctor_status(enabled=False)
    assert report["experimental"] is True
    assert report["enabled"] is False
    assert report["identityPresent"] is False
    assert "notes" in report
    dumped = str(report)
    assert "privateKey" not in dumped
    assert "bindingToken" not in dumped


def test_ingest_decoded_ble_session_dedupes_by_serial_session(tmp_path, monkeypatch):
    from localplaud.db.session import init_db
    from localplaud.ingest.orchestrator import provenance_for_file

    _reset_db(monkeypatch, tmp_path)
    init_db()
    audio = _write_wav(tmp_path / "decoded.wav")
    first = ingest_decoded_session(
        BleIngestRequest(serial="8810AAAABBBBCCCC", session_id="7", audio_path=audio)
    )
    second = ingest_decoded_session(
        BleIngestRequest(serial="8810AAAABBBBCCCC", session_id="7", audio_path=audio)
    )
    assert first.outcome == "created"
    assert first.source_transport == "ble"
    assert second.outcome == "reused"
    assert second.file_id == first.file_id
    provenance = provenance_for_file(first.file_id)
    assert provenance is not None
    assert provenance["source_transport"] == "ble"
    external = provenance["external_ids"]
    assert any(row["external_id"] == "8810AAAABBBBCCCC:7" for row in external)


def test_ble_backend_describe_feature_flag(monkeypatch, tmp_path):
    from localplaud.ingest.backends import BleBackend

    _reset_db(monkeypatch, tmp_path)
    monkeypatch.setenv("LOCALPLAUD_BLE__ENABLED", "false")
    from localplaud.config import get_settings

    get_settings(reload=True)
    desc = BleBackend().describe()
    assert desc["transport"] == "ble"
    assert desc["external_id_shape"] == "serial:sessionId"
    assert desc["status"] in {"disabled", "experimental"}
