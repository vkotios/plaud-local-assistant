"""Contract tests for the local knowledge MCP (fixture library; no cloud creds)."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

pytest.importorskip("mcp.server.fastmcp")

from plaud_local.mcp_knowledge.auth import (
    KnowledgeMcpAuth,
    KnowledgeMcpAuthError,
    constant_time_equals,
    verify_http_bearer,
)
from plaud_local.mcp_knowledge.server import SERVER_NAME, create_mcp
from plaud_local.mcp_knowledge.tools import (
    _MAX_CHARS_CAP,
    _MIN_CHARS,
    READ_ONLY_TOOL_NAMES,
    KnowledgeToolError,
    knowledge_ask,
    knowledge_get_notes,
    knowledge_get_provenance,
    knowledge_get_recording,
    knowledge_get_transcript,
    knowledge_list_folders,
    knowledge_list_recordings,
    knowledge_list_tags,
    knowledge_search,
)

_PATH_LEAK_KEYS = frozenset(
    {
        "audio_path",
        "wav_path",
        "path",
        "filepath",
        "file_path",
        "absolute_path",
        "local_path",
    }
)


def _assert_no_path_leakage(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in _PATH_LEAK_KEYS, f"leaked path key: {key}"
            _assert_no_path_leakage(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_path_leakage(item)


def _fresh_db(monkeypatch, tmp_path, name="knowledge-mcp.db"):
    import localplaud.db.session as db_session
    from localplaud.config import get_settings
    from localplaud.db.session import init_db

    monkeypatch.setenv("LOCALPLAUD_STORE__DATABASE_URL", f"sqlite:///{tmp_path / name}")
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_Session", None)
    get_settings(reload=True)
    init_db()


def _seed_library():
    from localplaud.db.models import (
        Folder,
        PlaudFile,
        Speaker,
        Summary,
        Tag,
        Transcript,
        TranscriptRevision,
        UserNote,
    )
    from localplaud.db.session import session_scope

    with session_scope() as session:
        folder = Folder(name="Research")
        tag = Tag(name="Decision")
        local = PlaudFile(
            id="local-recording",
            filename="Original title",
            local_title="Launch meeting",
            origin="local",
            source_transport="filesystem",
            content_sha256="abc123",
            audio_path="/secret/data/local-recording.wav",
            wav_path="/secret/data/local-recording.wav",
            start_time_ms=1_783_582_737_000,
            folder=folder,
            tags=[tag],
        )
        cloud = PlaudFile(
            id="cloud-recording",
            filename="Plaud interview",
            origin="plaud",
            source_transport="cloud",
            audio_path="/secret/data/cloud-recording.wav",
            start_time_ms=1_780_990_737_000,
        )
        trashed = PlaudFile(
            id="trashed-recording",
            filename="Gone meeting",
            local_title="Trashed launch",
            origin="local",
            is_trash=True,
            audio_path="/secret/data/trashed.wav",
            start_time_ms=1_783_000_000_000,
        )
        session.add_all([local, cloud, trashed])
        session.flush()
        session.add(
            Summary(
                file_id=trashed.id,
                template="meeting",
                source="local",
                content_md="Should not appear in MCP list/search/get.",
            )
        )
        raw = Transcript(
            file_id=local.id,
            provider="test",
            source="local",
            text="the launch was delayed",
            segments=[
                {
                    "text": "the launch was delayed",
                    "start": 12.5,
                    "end": 16.0,
                    "speaker": "SPEAKER_00",
                }
            ],
        )
        session.add(raw)
        session.flush()
        session.add(
            TranscriptRevision(
                file_id=local.id,
                base_transcript_id=raw.id,
                revision=1,
                source="local",
                text="the launch was approved",
                segments=[
                    {
                        "text": "the launch was approved",
                        "start": 12.5,
                        "end": 16.0,
                        "speaker": "SPEAKER_00",
                    }
                ],
            )
        )
        session.add(
            Transcript(
                file_id=cloud.id,
                provider="plaud",
                source="cloud",
                text="exclusive cloud phrase",
                segments=[{"text": "exclusive cloud phrase", "start": 4.0, "end": 6.0}],
            )
        )
        session.add_all(
            [
                Summary(
                    file_id=local.id,
                    template="meeting",
                    source="local",
                    content_md="Decision owner is Morgan.",
                ),
                Speaker(file_id=local.id, key="SPEAKER_00", display_name="Sky"),
                UserNote(
                    file_id=local.id,
                    title="Follow-up",
                    content_md="Call Riley tomorrow.",
                ),
            ]
        )


class _FakeEmbedder:
    name = "fake"
    dim = 2

    def available(self):
        return True

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


class _FakeLlm:
    name = "fake"

    def available(self):
        return True

    def complete(self, prompt, system=None, temperature=0.3, max_tokens=2048):
        return "Grounded answer about the launch."


def _seed_chunks():
    from localplaud.db.models import Chunk
    from localplaud.db.session import session_scope
    from localplaud.providers.service import resolve_recording_profile

    hit = np.array([1.0, 0.0], dtype=np.float32)
    with session_scope() as session:
        snapshot = resolve_recording_profile(session, "local-recording").to_dict()
        session.add(
            Chunk(
                file_id="local-recording",
                idx=0,
                text="the launch was approved",
                start=12.5,
                end=16.0,
                speaker="SPEAKER_00",
                embedding=hit.tobytes(),
                dim=2,
                resolved_profile_snapshot=snapshot,
            )
        )


def test_stdio_server_lists_only_read_only_tools():
    mcp = create_mcp()
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    assert set(tools) == READ_ONLY_TOOL_NAMES
    assert SERVER_NAME == "localplaud-knowledge"
    assert "knowledge_delete" not in tools
    assert "delete_recording" not in tools
    # Cloud ingest tool names must not appear on this server.
    assert "list_files" not in tools
    assert "get_file" not in tools


def test_search_ask_get_against_fixture_library(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    _seed_library()
    _seed_chunks()
    monkeypatch.setattr("localplaud.worker.qa.build_embedder", lambda cfg: _FakeEmbedder())
    monkeypatch.setattr("localplaud.worker.qa.build_llm", lambda cfg: _FakeLlm())

    search = knowledge_search("approved")
    assert search["cloud_credentials_required"] is False
    assert search["count"] >= 1
    assert search["hits"][0]["file_id"] == "local-recording"

    listed = knowledge_list_recordings(query="Launch")
    assert listed["returned"] == 1
    assert listed["files"][0]["id"] == "local-recording"

    folders = knowledge_list_folders()
    assert any(folder["name"] == "Research" for folder in folders["folders"])
    tags = knowledge_list_tags()
    assert any(tag["name"] == "Decision" for tag in tags["tags"])

    recording = knowledge_get_recording("local-recording")
    assert recording["has_transcript"] is True
    assert recording["has_notes"] is True
    assert recording["recording"]["source_transport"] == "filesystem"

    transcript = knowledge_get_transcript("local-recording", max_chars=2000)
    assert "approved" in transcript["content"]
    assert transcript["end_of_document"] is True

    notes = knowledge_get_notes("local-recording", max_chars=2000)
    assert "Morgan" in notes["content"] or "Riley" in notes["content"]

    provenance = knowledge_get_provenance("local-recording")
    assert provenance["ingest"]["source_transport"] == "filesystem"
    assert provenance["transcript"].get("transcript_source") == "local"

    asked = knowledge_ask("What happened to the launch?", file_id="local-recording")
    assert "Grounded answer" in asked["answer"]
    assert asked["cloud_credentials_required"] is False
    assert asked["sources"]
    assert asked["side_effects"] == ["provider_cost_reservations"]


def test_rejects_invalid_and_path_like_file_ids(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    _seed_library()
    for bad_id in (
        "../etc/passwd",
        "/tmp/audio.wav",
        "foo/bar",
        "id with spaces",
        "a" * 129,
        "",
        ".",
        "..",
    ):
        with pytest.raises(KnowledgeToolError, match="valid recording ID"):
            knowledge_get_recording(bad_id)
        with pytest.raises(KnowledgeToolError, match="valid recording ID"):
            knowledge_get_transcript(bad_id)
        with pytest.raises(KnowledgeToolError, match="valid recording ID"):
            knowledge_ask("q", file_id=bad_id)


def test_pagination_and_max_chars_clamping(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    _seed_library()
    from localplaud.db.models import UserNote
    from localplaud.db.session import session_scope

    long_body = "α" * 5_000
    with session_scope() as session:
        session.add(
            UserNote(
                file_id="local-recording",
                title="Long note",
                content_md=long_body,
            )
        )

    under = knowledge_get_notes("local-recording", max_chars=100, offset=0)
    assert under["max_chars"] == _MIN_CHARS
    assert len(under["content"]) == _MIN_CHARS
    assert under["end_of_document"] is False
    assert under["next_offset"] == _MIN_CHARS

    page2 = knowledge_get_notes(
        "local-recording", max_chars=_MIN_CHARS, offset=under["next_offset"]
    )
    assert page2["offset"] == _MIN_CHARS
    full = knowledge_get_notes("local-recording", max_chars=_MAX_CHARS_CAP, offset=0)
    assert full["content"].startswith(under["content"])
    assert full["content"][under["next_offset"] :].startswith(page2["content"])

    over = knowledge_get_notes("local-recording", max_chars=100_000, offset=0)
    assert over["max_chars"] == _MAX_CHARS_CAP

    with pytest.raises(KnowledgeToolError, match="offset"):
        knowledge_get_notes("local-recording", offset=-1)
    with pytest.raises(KnowledgeToolError, match="offset"):
        knowledge_get_notes("local-recording", offset=over["total_chars"] + 1)


def test_trash_excluded_and_payloads_omit_filesystem_paths(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    _seed_library()

    listed = knowledge_list_recordings(max_results=50)
    ids = {row["id"] for row in listed["files"]}
    assert "trashed-recording" not in ids
    assert "local-recording" in ids

    search = knowledge_search("Trashed")
    assert all(hit["file_id"] != "trashed-recording" for hit in search["hits"])

    with pytest.raises(KnowledgeToolError, match="recording not found"):
        knowledge_get_recording("trashed-recording")
    with pytest.raises(KnowledgeToolError, match="recording not found"):
        knowledge_get_notes("trashed-recording")
    with pytest.raises(KnowledgeToolError, match="recording not found"):
        knowledge_get_provenance("trashed-recording")

    recording = knowledge_get_recording("local-recording")
    listed_again = knowledge_list_recordings()
    folders = knowledge_list_folders()
    tags = knowledge_list_tags()
    provenance = knowledge_get_provenance("local-recording")
    for payload in (recording, listed_again, folders, tags, provenance, search):
        _assert_no_path_leakage(payload)
        blob = json.dumps(payload)
        assert "/secret/data/" not in blob
        assert "audio_path" not in blob


def test_mcp_tool_wrappers_return_json(monkeypatch, tmp_path):
    _fresh_db(monkeypatch, tmp_path)
    _seed_library()
    mcp = create_mcp()

    async def _call():
        return await mcp.call_tool("knowledge_search", {"query": "approved"})

    result = asyncio.run(_call())
    if isinstance(result, dict) and "hits" in result:
        payload = result
    elif isinstance(result, str):
        payload = json.loads(result)
    elif isinstance(result, tuple) and result and isinstance(result[-1], dict) and "result" in result[-1]:
        payload = json.loads(result[-1]["result"])
    else:
        blocks = result[0] if isinstance(result, tuple) else result
        block = blocks[0]
        payload = json.loads(block.text)
    assert payload["hits"][0]["file_id"] == "local-recording"


def test_http_bearer_fail_closed_and_constant_time():
    assert constant_time_equals("same-token", "same-token")
    assert not constant_time_equals("a", "b")

    with pytest.raises(KnowledgeMcpAuthError):
        verify_http_bearer(None, auth=KnowledgeMcpAuth(bearer_token=None, require_auth=True))

    with pytest.raises(KnowledgeMcpAuthError):
        verify_http_bearer(
            "Bearer wrong",
            auth=KnowledgeMcpAuth(bearer_token="correct-token", require_auth=True),
        )

    verify_http_bearer(
        "Bearer correct-token",
        auth=KnowledgeMcpAuth(bearer_token="correct-token", require_auth=True),
    )
    verify_http_bearer(
        None,
        auth=KnowledgeMcpAuth(bearer_token=None, require_auth=False),
    )


def test_mutations_flag_does_not_register_destructive_tools(capsys):
    mcp = create_mcp(allow_mutations=True)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert names == READ_ONLY_TOOL_NAMES
    err = capsys.readouterr().err
    assert "read-only" in err
