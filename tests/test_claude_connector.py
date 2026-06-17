"""Integration tests for the assembled Claude connector."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.config import Config
from app.models import TokenDataAvailability
from connectors.claude import ClaudeConnector

FIXTURES = Path(__file__).parent / "fixtures" / "claude"


def _build_state_dir(tmp_path: Path, *, include_malformed: bool) -> Path:
    state = tmp_path / ".claude"
    session_id = "sess-1"

    proj = state / "projects" / "project-slug" / session_id
    proj.mkdir(parents=True)
    shutil.copy(FIXTURES / "valid_transcript.jsonl", proj / "valid.jsonl")
    if include_malformed:
        shutil.copy(FIXTURES / "malformed.jsonl", proj / "malformed.jsonl")

    sessions = state / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "111.json").write_text(
        json.dumps(
            {"pid": 111, "sessionId": session_id, "cwd": "/p", "startedAt": 1781726286747}
        )
    )

    tasks = state / "scheduled-tasks" / "skills-scan"
    tasks.mkdir(parents=True)
    (tasks / "SKILL.md").write_text("---\nname: skills-scan\n---\nbody\n")

    return state


def _config(state_dir: Path) -> Config:
    return Config(claude_state_path=str(state_dir))


def test_collect_returns_valid_snapshot(tmp_path: Path) -> None:
    state = _build_state_dir(tmp_path, include_malformed=False)
    connector = ClaudeConnector(_config(state))

    assert connector.available() is True
    snapshot = connector.collect()

    assert snapshot.available is True
    assert snapshot.connector_id == "claude"
    assert snapshot.token_data is TokenDataAvailability.full
    assert snapshot.token_windows is not None
    assert len(snapshot.sessions) == 1
    assert snapshot.sessions[0].session_id == "sess-1"
    assert [t.name for t in snapshot.scheduled_tasks] == ["skills-scan"]


def test_missing_state_dir_unavailable(tmp_path: Path) -> None:
    connector = ClaudeConnector(_config(tmp_path / "does-not-exist"))

    assert connector.available() is False
    snapshot = connector.collect()

    assert snapshot.available is False
    assert snapshot.token_data is TokenDataAvailability.unavailable
    assert snapshot.sessions == []
    assert snapshot.scheduled_tasks == []


def test_truncated_jsonl_counts_parse_errors(tmp_path: Path) -> None:
    state = _build_state_dir(tmp_path, include_malformed=True)
    snapshot = ClaudeConnector(_config(state)).collect()

    assert snapshot.parse_errors > 0
    assert snapshot.available is True


def test_sources_lists_expected_paths(tmp_path: Path) -> None:
    state = _build_state_dir(tmp_path, include_malformed=False)
    connector = ClaudeConnector(_config(state))

    assert connector.sources == [
        state,
        state / "sessions",
        state / "projects",
        state / "scheduled-tasks",
    ]
