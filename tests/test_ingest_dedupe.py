"""Phase 3 unified ingest + library-level duplicate detection."""

from __future__ import annotations

import wave
from io import BytesIO
from pathlib import Path

import pytest


def _reset_db(monkeypatch, tmp_path, *, enabled: str = "true", dedupe_mode: str = "link"):
    import localplaud.db.session as db_session
    from localplaud.config import get_settings

    monkeypatch.setenv("LOCALPLAUD_STORE__DATABASE_URL", f"sqlite:///{tmp_path / 'ingest.db'}")
    monkeypatch.setenv("LOCALPLAUD_POLLER__DOWNLOAD_DIR", str(tmp_path / "audio"))
    monkeypatch.setenv("LOCALPLAUD_INGEST__ENABLED", enabled)
    monkeypatch.setenv("LOCALPLAUD_INGEST__DEDUPE_MODE", dedupe_mode)
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_Session", None)
    return get_settings(reload=True)


def _wav_bytes(frames: int = 800, sample: bytes = b"\x00\x00") -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as fixture:
        fixture.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        fixture.writeframes(sample * frames)
    return buffer.getvalue()


def _write_wav(path: Path, *, frames: int = 800, sample: bytes = b"\x00\x00") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_wav_bytes(frames=frames, sample=sample))
    return path


def test_ingest_dedupe_migration_is_additive_and_idempotent(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from localplaud.db.migrations import migrate_ingest_dedupe_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-ingest.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name VARCHAR(80))"
            )
        )
        connection.execute(text("INSERT INTO workspaces (id, name) VALUES (1, 'localplaud')"))
        connection.execute(
            text(
                "CREATE TABLE plaud_files ("
                "id VARCHAR(64) PRIMARY KEY, "
                "origin VARCHAR(32) NOT NULL DEFAULT 'plaud', "
                "workspace_id INTEGER NOT NULL DEFAULT 1)"
            )
        )
        connection.execute(
            text("INSERT INTO plaud_files (id, origin) VALUES ('cloud-1', 'plaud')")
        )
        connection.execute(
            text("INSERT INTO plaud_files (id, origin) VALUES ('local-1', 'local')")
        )
        connection.execute(text("CREATE TABLE kv (key VARCHAR(128) PRIMARY KEY, value JSON)"))

    first = set(migrate_ingest_dedupe_schema(engine))
    assert "plaud_files.content_sha256" in first
    assert "plaud_files.source_transport" in first
    assert "recording_external_ids" in first
    assert "ingest_jobs" in first
    assert migrate_ingest_dedupe_schema(engine) == []

    columns = {c["name"] for c in inspect(engine).get_columns("plaud_files")}
    assert {
        "source_transport",
        "content_sha256",
        "audio_fingerprint",
        "duplicate_of",
        "dedupe_status",
    } <= columns
    assert "recording_external_ids" in inspect(engine).get_table_names()
    with engine.begin() as connection:
        transports = dict(
            connection.execute(
                text("SELECT id, source_transport FROM plaud_files")
            ).all()
        )
        assert transports["cloud-1"] == "cloud"
        assert transports["local-1"] == "upload"
        externals = connection.execute(
            text(
                "SELECT provider, transport, external_id FROM recording_external_ids"
            )
        ).all()
        assert ("plaud", "cloud", "cloud-1") in list(externals)


def test_same_plaud_external_id_reuses_row(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path)
    from localplaud.db.session import init_db
    from localplaud.ingest.orchestrator import IngestCandidate, ingest_candidate

    init_db()
    first = ingest_candidate(
        IngestCandidate(
            transport="cloud",
            provider="plaud",
            filename="Meeting",
            external_id="plaud-abc",
            content_sha256="a" * 64,
        ),
        settings=settings,
    )
    second = ingest_candidate(
        IngestCandidate(
            transport="cloud",
            provider="plaud",
            filename="Meeting again",
            external_id="plaud-abc",
            content_sha256="b" * 64,
        ),
        settings=settings,
    )
    assert first.outcome == "created"
    assert second.outcome == "reused"
    assert second.file_id == first.file_id == "plaud-abc"


def test_same_hash_different_id_links_duplicate(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path)
    from localplaud.db.models import PlaudFile
    from localplaud.db.session import init_db, session_scope
    from localplaud.ingest.orchestrator import ingest_filesystem_path

    init_db()
    audio_a = _write_wav(tmp_path / "a.wav", sample=b"\x11\x11")
    audio_b = tmp_path / "b.wav"
    audio_b.write_bytes(audio_a.read_bytes())

    first = ingest_filesystem_path(audio_a, filename="first.wav", settings=settings)
    second = ingest_filesystem_path(audio_b, filename="second.wav", settings=settings)
    assert first.outcome == "created"
    assert second.outcome == "linked_duplicate"
    assert second.duplicate_of == first.file_id
    assert first.file_id != second.file_id
    with session_scope() as session:
        linked = session.get(PlaudFile, second.file_id)
        original = session.get(PlaudFile, first.file_id)
        assert linked.duplicate_of == original.id
        assert linked.content_sha256 == original.content_sha256
        assert original.audio_path and Path(original.audio_path).exists()
        assert linked.audio_path and Path(linked.audio_path).exists()


def test_reject_new_mode_returns_existing(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path, dedupe_mode="reject_new")
    from localplaud.db.session import init_db
    from localplaud.ingest.orchestrator import ingest_filesystem_path

    init_db()
    audio = _write_wav(tmp_path / "once.wav")
    first = ingest_filesystem_path(audio, settings=settings)
    second = ingest_filesystem_path(audio, filename="again.wav", settings=settings)
    assert first.outcome == "created"
    assert second.outcome == "rejected_duplicate"
    assert second.file_id == first.file_id


def test_ble_vs_cloud_overlap_by_hash_and_ble_key(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path)
    from localplaud.db.models import RecordingExternalId
    from localplaud.db.session import init_db, session_scope
    from localplaud.ingest.orchestrator import IngestCandidate, ingest_ble_stub, ingest_candidate
    from localplaud.ingest.types import ble_external_id

    init_db()
    audio = _write_wav(tmp_path / "shared.wav", sample=b"\x22\x22")
    cloud = ingest_candidate(
        IngestCandidate(
            transport="cloud",
            provider="plaud",
            filename="cloud.wav",
            external_id="cloud-shared",
            audio_path=audio,
            copy_audio=True,
        ),
        settings=settings,
    )
    ble = ingest_ble_stub(
        serial="SN123",
        session_id="sess-9",
        audio_path=audio,
        settings=settings,
    )
    assert cloud.outcome == "created"
    assert ble.outcome == "linked_duplicate"
    assert ble.duplicate_of == cloud.file_id

    again = ingest_ble_stub(
        serial="SN123",
        session_id="sess-9",
        audio_path=audio,
        settings=settings,
    )
    assert again.outcome == "reused"
    assert again.file_id == ble.file_id
    with session_scope() as session:
        rows = session.query(RecordingExternalId).all()
        keys = {(r.provider, r.transport, r.external_id) for r in rows}
        assert ("plaud", "cloud", "cloud-shared") in keys
        assert ("ble", "ble", ble_external_id("SN123", "sess-9")) in keys


def test_double_import_fixture_via_upload_api(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    from localplaud.api.app import app
    from localplaud.db.models import PlaudFile
    from localplaud.db.session import init_db, session_scope

    init_db()
    client = TestClient(app)
    payload = _wav_bytes(sample=b"\x33\x33")
    first = client.post(
        "/api/imports/local/audio",
        files={"file": ("meeting.wav", payload, "audio/wav")},
    )
    second = client.post(
        "/api/imports/local/audio",
        files={"file": ("meeting-copy.wav", payload, "audio/wav")},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    body1, body2 = first.json(), second.json()
    assert body1["outcome"] == "created"
    assert body2["outcome"] == "linked_duplicate"
    assert body2["duplicate_of"] == body1["id"]
    assert body1["content_sha256"] == body2["content_sha256"]
    with session_scope() as session:
        assert session.query(PlaudFile).count() == 2
        linked = session.get(PlaudFile, body2["id"])
        assert linked.duplicate_of == body1["id"]
        assert linked.source_transport == "upload"


def test_interrupted_ingest_resume_reuses_identity(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path)
    from localplaud.db.models import IngestJob, PlaudFile
    from localplaud.db.session import init_db, session_scope
    from localplaud.ingest import recover_interrupted_ingest_jobs
    from localplaud.ingest.orchestrator import ingest_filesystem_path

    init_db()
    audio = _write_wav(tmp_path / "resume.wav", sample=b"\x44\x44")
    first = ingest_filesystem_path(
        audio, filename="resume.wav", external_id="fs-resume-1", settings=settings
    )
    assert first.outcome == "created"

    with session_scope() as session:
        session.add(
            IngestJob(
                id="zombie",
                backend="filesystem",
                transport="filesystem",
                status="running",
                content_sha256=first.content_sha256,
                external_key="filesystem:filesystem:fs-resume-1",
            )
        )
    assert recover_interrupted_ingest_jobs() == 1
    with session_scope() as session:
        assert session.get(IngestJob, "zombie").status == "failed"

    second = ingest_filesystem_path(
        audio, filename="resume-again.wav", external_id="fs-resume-1", settings=settings
    )
    assert second.outcome == "reused"
    assert second.file_id == first.file_id
    with session_scope() as session:
        assert session.query(PlaudFile).count() == 1


def test_ingest_status_and_provenance_endpoints(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient

    from localplaud.api.app import app
    from localplaud.db.session import init_db
    from localplaud.ingest.orchestrator import ingest_filesystem_path

    init_db()
    client = TestClient(app)
    status = client.get("/api/ingest/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["enabled"] is True
    assert payload["dedupe_mode"] == "link"
    names = {b["name"] for b in payload["backends"]}
    assert names == {"cloud", "filesystem", "upload", "ble"}
    ble = next(b for b in payload["backends"] if b["name"] == "ble")
    assert ble["status"] == "stub"

    audio = _write_wav(tmp_path / "prov.wav")
    result = ingest_filesystem_path(audio, external_id="fs-prov", settings=settings)
    prov = client.get(f"/api/ingest/files/{result.file_id}/provenance")
    assert prov.status_code == 200
    body = prov.json()
    assert body["source_transport"] == "filesystem"
    assert body["content_sha256"]
    assert any(e["external_id"] == "fs-prov" for e in body["external_ids"])


def test_ble_transfer_stub_raises():
    from localplaud.ingest.backends import BleBackend

    with pytest.raises(NotImplementedError):
        BleBackend().transfer()


def test_ingest_disabled_falls_back(monkeypatch, tmp_path):
    settings = _reset_db(monkeypatch, tmp_path, enabled="false")
    from localplaud.db.session import init_db
    from localplaud.ingest.orchestrator import ingest_filesystem_path

    init_db()
    audio = _write_wav(tmp_path / "off.wav")
    result = ingest_filesystem_path(audio, settings=settings)
    assert result.outcome == "disabled"
    assert result.file_id is None
