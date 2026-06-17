"""Claude connector: assemble token windows, sessions, and scheduled tasks.

Reads the Claude state directory (``~/.claude`` by default), parses all
transcript JSONL files for token accounting, derives interactive session
activity, and lists scheduled tasks. ``collect()`` never raises.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config import Config
from app.models import ConnectorSnapshot, TokenDataAvailability
from connectors.base import Connector
from connectors.claude_parser import parse_transcript
from connectors.claude_sessions import read_sessions
from connectors.claude_tasks import read_scheduled_tasks
from connectors.claude_windows import compute_windows


class ClaudeConnector(Connector):
    id = "claude"
    label = "Claude"

    def __init__(self, config: Config) -> None:
        self._config = config
        self.claude_state_dir = config.claude_state_dir
        self.sessions_dir = self.claude_state_dir / "sessions"
        self.projects_dir = self.claude_state_dir / "projects"
        self.scheduled_tasks_dir = self.claude_state_dir / "scheduled-tasks"

    @property
    def sources(self) -> list[Path]:
        return [
            self.claude_state_dir,
            self.sessions_dir,
            self.projects_dir,
            self.scheduled_tasks_dir,
        ]

    def available(self) -> bool:
        return self.claude_state_dir.exists()

    def collect(self) -> ConnectorSnapshot:
        try:
            return self._collect()
        except Exception:
            return ConnectorSnapshot(
                connector_id=self.id,
                label=self.label,
                available=False,
                token_data=TokenDataAvailability.unavailable,
                token_windows=None,
            )

    def _collect(self) -> ConnectorSnapshot:
        if not self.available():
            return ConnectorSnapshot(
                connector_id=self.id,
                label=self.label,
                available=False,
                token_data=TokenDataAvailability.unavailable,
                token_windows=None,
            )

        now = datetime.now(timezone.utc)

        all_turns = []
        parse_errors = 0
        if self.projects_dir.exists():
            for path in sorted(self.projects_dir.glob("**/*.jsonl")):
                turns, errors = parse_transcript(path)
                all_turns.extend(turns)
                parse_errors += errors

        token_windows = compute_windows(
            all_turns, now, self._config.quota_limits.model_dump()
        )
        sessions = read_sessions(self.sessions_dir, self.projects_dir, now)
        scheduled_tasks = read_scheduled_tasks(self.scheduled_tasks_dir)

        return ConnectorSnapshot(
            connector_id=self.id,
            label=self.label,
            available=True,
            token_data=TokenDataAvailability.full,
            token_windows=token_windows,
            sessions=sessions,
            scheduled_tasks=scheduled_tasks,
            parse_errors=parse_errors,
        )
