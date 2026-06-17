"""Tests for the workspace snapshot data model."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import (
    ActivityState,
    ConnectorSnapshot,
    DockerContainer,
    PortMapping,
    Project,
    QuotaWindow,
    ScheduledTask,
    Session,
    Snapshot,
    TokenBreakdown,
    TokenDataAvailability,
    TokenWindows,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _token_windows() -> TokenWindows:
    return TokenWindows(
        five_hour=QuotaWindow(
            window="five_hour",
            used=1000,
            limit=5000,
            percent=None,
            resets_at=_utc(2026, 6, 17, 18, 0, 0),
        ),
        weekly=QuotaWindow(
            window="weekly",
            used=20000,
            limit=100000,
            percent=None,
            resets_at=_utc(2026, 6, 22, 0, 0, 0),
        ),
        monthly=QuotaWindow(
            window="monthly",
            used=50000,
            limit=None,
            percent=None,
            resets_at=None,
        ),
        breakdown=TokenBreakdown(
            input=10,
            output=20,
            cache_read=30,
            cache_creation=40,
            cache_creation_5m=5,
            cache_creation_1h=1,
        ),
    )


def _full_snapshot() -> Snapshot:
    return Snapshot(
        captured_at=_utc(2026, 6, 17, 16, 0, 0),
        connectors=[
            ConnectorSnapshot(
                connector_id="claude-code",
                label="Claude Code",
                available=True,
                token_data=TokenDataAvailability.full,
                token_windows=_token_windows(),
                sessions=[
                    Session(
                        session_id="abc123",
                        cwd="/Users/dev/project",
                        git_branch="main",
                        model="opus-4.8",
                        activity_state=ActivityState.active,
                        last_event_at=_utc(2026, 6, 17, 15, 59, 0),
                        is_sidechain=False,
                        started_at=_utc(2026, 6, 17, 15, 0, 0),
                        cost_usd=1.23,
                    )
                ],
                scheduled_tasks=[
                    ScheduledTask(
                        name="nightly-report",
                        schedule="0 0 * * *",
                        next_run=_utc(2026, 6, 18, 0, 0, 0),
                    )
                ],
                parse_errors=2,
            )
        ],
        docker_containers=[
            DockerContainer(
                id="deadbeef",
                name="api",
                image="api:latest",
                status="running",
                uptime_seconds=3600,
                cpu_percent=12.5,
                memory_used_mb=256.0,
                memory_limit_mb=1024.0,
                ports=[PortMapping(host=8080, container=80, protocol="tcp")],
            )
        ],
        projects=[
            Project(
                name="ai_manager",
                path="/Users/dev/ai_manager",
                branch="main",
                dirty=True,
                ahead=2,
                behind=0,
                last_commit_message="add models",
                last_commit_at=_utc(2026, 6, 17, 14, 0, 0),
                last_activity_at=_utc(2026, 6, 17, 15, 30, 0),
            )
        ],
        totals=_token_windows(),
    )


def test_snapshot_json_round_trip() -> None:
    snapshot = _full_snapshot()
    payload = snapshot.model_dump_json()
    restored = Snapshot.model_validate_json(payload)
    assert restored == snapshot


def test_quota_window_percent_none_when_no_limit() -> None:
    window = QuotaWindow(
        window="monthly", used=5000, limit=None, percent=None, resets_at=None
    )
    assert window.percent is None


def test_quota_window_percent_computed_when_limit_set() -> None:
    window = QuotaWindow(
        window="five_hour", used=2500, limit=5000, percent=None, resets_at=None
    )
    assert window.percent == 50.0


def test_quota_window_percent_forced_none_when_limit_missing() -> None:
    window = QuotaWindow(
        window="weekly", used=100, limit=None, percent=42.0, resets_at=None
    )
    assert window.percent is None


@pytest.mark.parametrize("state", list(ActivityState))
def test_activity_state_round_trip(state: ActivityState) -> None:
    session = Session(
        session_id="s1",
        cwd=None,
        git_branch=None,
        model=None,
        activity_state=state,
        last_event_at=None,
        started_at=None,
        cost_usd=None,
    )
    payload = session.model_dump_json()
    restored = Session.model_validate_json(payload)
    assert restored.activity_state == state
    assert f'"activity_state":"{state.value}"' in payload


def test_docker_container_missing_optionals() -> None:
    container = DockerContainer(
        id="abc",
        name="db",
        image="postgres:16",
        status="unknown",
        uptime_seconds=None,
        cpu_percent=None,
        memory_used_mb=None,
        memory_limit_mb=None,
    )
    assert container.ports == []
    assert container.uptime_seconds is None
