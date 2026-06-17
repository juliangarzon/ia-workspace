"""Tests for Claude session detection and activity-state derivation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import ActivityState
from connectors.claude_sessions import read_sessions


def _write_session(sessions_dir: Path, pid: int, session_id: str) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / f"{pid}.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "sessionId": session_id,
                "cwd": "/path/to/project",
                "startedAt": 1781726286747,
                "kind": "interactive",
            }
        )
    )


def _write_transcript(
    transcripts_dir: Path, session_id: str, ts: datetime, branch: str = "main"
) -> None:
    session_dir = transcripts_dir / "project-slug" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "gitBranch": branch,
        "isSidechain": False,
        "message": {
            "id": "msg_a",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "service_tier": "standard",
            },
        },
    }
    (session_dir / "transcript.jsonl").write_text(json.dumps(record) + "\n")


def test_active_session(tmp_path: Path) -> None:
    now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    transcripts_dir = tmp_path / "projects"
    _write_session(sessions_dir, 100, "sess-active")
    _write_transcript(transcripts_dir, "sess-active", now - timedelta(seconds=30))

    sessions = read_sessions(sessions_dir, transcripts_dir, now)

    assert len(sessions) == 1
    assert sessions[0].activity_state is ActivityState.active
    assert sessions[0].git_branch == "main"
    assert sessions[0].last_event_at is not None


def test_stale_session(tmp_path: Path) -> None:
    now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    transcripts_dir = tmp_path / "projects"
    _write_session(sessions_dir, 101, "sess-stale")
    _write_transcript(transcripts_dir, "sess-stale", now - timedelta(hours=2))

    sessions = read_sessions(sessions_dir, transcripts_dir, now)

    assert sessions[0].activity_state is ActivityState.stale


def test_no_transcript_is_stale(tmp_path: Path) -> None:
    now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    transcripts_dir = tmp_path / "projects"
    _write_session(sessions_dir, 102, "sess-orphan")

    sessions = read_sessions(sessions_dir, transcripts_dir, now)

    assert sessions[0].activity_state is ActivityState.stale
    assert sessions[0].last_event_at is None


def test_thinking_and_idle_thresholds(tmp_path: Path) -> None:
    now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    transcripts_dir = tmp_path / "projects"
    _write_session(sessions_dir, 200, "sess-thinking")
    _write_transcript(transcripts_dir, "sess-thinking", now - timedelta(seconds=5))
    _write_session(sessions_dir, 201, "sess-idle")
    _write_transcript(transcripts_dir, "sess-idle", now - timedelta(minutes=30))

    by_id = {s.session_id: s for s in read_sessions(sessions_dir, transcripts_dir, now)}

    assert by_id["sess-thinking"].activity_state is ActivityState.thinking
    assert by_id["sess-idle"].activity_state is ActivityState.idle


def test_sorted_by_last_event_desc(tmp_path: Path) -> None:
    now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    transcripts_dir = tmp_path / "projects"
    _write_session(sessions_dir, 300, "sess-old")
    _write_transcript(transcripts_dir, "sess-old", now - timedelta(hours=3))
    _write_session(sessions_dir, 301, "sess-new")
    _write_transcript(transcripts_dir, "sess-new", now - timedelta(seconds=10))

    sessions = read_sessions(sessions_dir, transcripts_dir, now)

    assert [s.session_id for s in sessions] == ["sess-new", "sess-old"]


def test_skips_unparsable_session_file(tmp_path: Path) -> None:
    now = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
    sessions_dir = tmp_path / "sessions"
    transcripts_dir = tmp_path / "projects"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "bad.json").write_text("{not json")
    _write_session(sessions_dir, 400, "sess-ok")
    _write_transcript(transcripts_dir, "sess-ok", now - timedelta(seconds=10))

    sessions = read_sessions(sessions_dir, transcripts_dir, now)

    assert [s.session_id for s in sessions] == ["sess-ok"]
