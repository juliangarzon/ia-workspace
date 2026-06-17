"""Tests for quota window bucketing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from connectors.claude_parser import ParsedTurn
from connectors.claude_windows import compute_windows

NOW = datetime(2026, 6, 17, 14, 0, 0, tzinfo=timezone.utc)  # Tue, week 25
NO_LIMITS: dict = {"five_hour": None, "weekly": None, "monthly": None}


def _turn(
    timestamp: datetime,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    is_sidechain: bool = False,
) -> ParsedTurn:
    return ParsedTurn(
        message_id="m",
        session_id="s",
        timestamp=timestamp,
        model="claude-opus-4",
        git_branch=None,
        is_sidechain=is_sidechain,
        cost_usd=None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_5m=0,
        cache_creation_1h=0,
        service_tier=None,
    )


def test_empty_turns() -> None:
    windows = compute_windows([], NOW, NO_LIMITS)
    assert windows.five_hour.used == 0
    assert windows.weekly.used == 0
    assert windows.monthly.used == 0
    assert windows.five_hour.resets_at is None


def test_five_hour_window_inclusion() -> None:
    turns = [
        _turn(NOW - timedelta(hours=4), input_tokens=10),
        _turn(NOW - timedelta(hours=6), input_tokens=10),
    ]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.five_hour.used == 10


def test_weekly_boundary() -> None:
    monday = datetime(2026, 6, 15, 9, 0, 0, tzinfo=timezone.utc)
    last_sunday = datetime(2026, 6, 14, 23, 0, 0, tzinfo=timezone.utc)
    turns = [
        _turn(monday, input_tokens=5),
        _turn(last_sunday, input_tokens=5),
    ]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.weekly.used == 5


def test_monthly_boundary() -> None:
    june_first = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    may_last = datetime(2026, 5, 31, 23, 59, 0, tzinfo=timezone.utc)
    turns = [
        _turn(june_first, input_tokens=7),
        _turn(may_last, input_tokens=7),
    ]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.monthly.used == 7


def test_sidechain_excluded() -> None:
    turns = [
        _turn(NOW - timedelta(hours=1), input_tokens=100, is_sidechain=True),
        _turn(NOW - timedelta(hours=1), input_tokens=20),
    ]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.five_hour.used == 20


def test_limit_and_percent_math() -> None:
    turns = [_turn(NOW - timedelta(hours=1), input_tokens=250)]
    windows = compute_windows(turns, NOW, {"five_hour": 1000})
    assert windows.five_hour.used == 250
    assert windows.five_hour.limit == 1000
    assert windows.five_hour.percent == 25.0


def test_no_limit_yields_none_percent() -> None:
    turns = [_turn(NOW - timedelta(hours=1), input_tokens=250)]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.five_hour.limit is None
    assert windows.five_hour.percent is None


def test_resets_at_weekly_is_next_monday() -> None:
    turns = [_turn(NOW, input_tokens=1)]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.weekly.resets_at == datetime(2026, 6, 22, 0, 0, 0, tzinfo=timezone.utc)


def test_resets_at_monthly_is_july_first() -> None:
    turns = [_turn(NOW, input_tokens=1)]
    windows = compute_windows(turns, NOW, NO_LIMITS)
    assert windows.monthly.resets_at == datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
