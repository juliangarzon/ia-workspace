"""Read Claude interactive sessions and derive their activity state.

Session metadata lives in ``<sessions_dir>/<pid>.json``. Those files carry no
last-event timestamp, so we derive activity from the session's JSONL transcripts
under ``<transcripts_dir>/**/<sessionId>/*.jsonl`` (most recent record wins,
falling back to file mtime).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.models import ActivityState, Session
from connectors.claude_parser import parse_transcript

ACTIVITY_THRESHOLDS = {
    ActivityState.thinking: 15,  # seconds
    ActivityState.active: 60,
    ActivityState.idle: 3600,  # stale beyond this
}


def _derive_state(now: datetime, last_event_at: datetime | None) -> ActivityState:
    if last_event_at is None:
        return ActivityState.stale
    elapsed = (now - last_event_at).total_seconds()
    if elapsed < ACTIVITY_THRESHOLDS[ActivityState.thinking]:
        return ActivityState.thinking
    if elapsed < ACTIVITY_THRESHOLDS[ActivityState.active]:
        return ActivityState.active
    if elapsed < ACTIVITY_THRESHOLDS[ActivityState.idle]:
        return ActivityState.idle
    return ActivityState.stale


def _started_at(started_at_ms: object) -> datetime | None:
    if not isinstance(started_at_ms, (int, float)):
        return None
    return datetime.fromtimestamp(started_at_ms / 1000, tz=timezone.utc)


def _session_jsonl_files(transcripts_dir: Path, session_id: str) -> list[Path]:
    if not session_id:
        return []
    return sorted(transcripts_dir.glob(f"**/{session_id}/*.jsonl"))


def _latest_event(files: list[Path]) -> tuple[datetime | None, str | None]:
    """Return ``(last_event_at, git_branch)`` from the most recent turn.

    Falls back to file mtime for the timestamp when no turn is parsable.
    """
    last_event_at: datetime | None = None
    git_branch: str | None = None
    for path in files:
        turns, _ = parse_transcript(path)
        if turns:
            newest = max(turns, key=lambda t: t.timestamp)
            if last_event_at is None or newest.timestamp > last_event_at:
                last_event_at = newest.timestamp
                git_branch = newest.git_branch
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if last_event_at is None or mtime > last_event_at:
            last_event_at = mtime
    return last_event_at, git_branch


def _read_session_file(
    path: Path, transcripts_dir: Path, now: datetime
) -> Session | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None

    session_id = raw.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return None

    files = _session_jsonl_files(transcripts_dir, session_id)
    last_event_at, git_branch = _latest_event(files)

    return Session(
        session_id=session_id,
        cwd=raw.get("cwd"),
        git_branch=git_branch,
        model=None,
        activity_state=_derive_state(now, last_event_at),
        last_event_at=last_event_at,
        is_sidechain=False,
        started_at=_started_at(raw.get("startedAt")),
        cost_usd=None,
    )


def read_sessions(
    sessions_dir: Path,
    transcripts_dir: Path,
    now: datetime,
) -> list[Session]:
    """Read all ``<pid>.json`` files and derive activity state per session.

    Returns sessions sorted by ``last_event_at`` descending (most recent first).
    Sessions with no transcript sort last. Unparsable session files are skipped.
    """
    if not sessions_dir.exists():
        return []

    sessions: list[Session] = []
    for path in sorted(sessions_dir.glob("*.json")):
        session = _read_session_file(path, transcripts_dir, now)
        if session is not None:
            sessions.append(session)

    return sorted(
        sessions,
        key=lambda s: s.last_event_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
