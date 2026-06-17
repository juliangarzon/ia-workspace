"""Bucket parsed Claude turns into rolling quota windows.

Turns are grouped into a 5-hour rolling window, the current ISO week, and the
current calendar month (all UTC). Sidechain turns are excluded from quota
counts because they inflate usage without consuming the user-facing budget.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import QuotaWindow, TokenBreakdown, TokenWindows
from connectors.claude_parser import ParsedTurn


def _next_month_start(now: datetime) -> datetime:
    if now.month == 12:
        return datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    week_start = datetime(
        now.year, now.month, now.day, tzinfo=timezone.utc
    ) - timedelta(days=now.weekday())
    return week_start, week_start + timedelta(days=7)


def _turn_used(turn: ParsedTurn) -> int:
    return (
        turn.input_tokens
        + turn.output_tokens
        + turn.cache_creation_tokens
        + turn.cache_read_tokens
    )


def _window(
    name: str, turns: list[ParsedTurn], limit: int | None, resets_at: datetime | None
) -> QuotaWindow:
    used = sum(_turn_used(turn) for turn in turns)
    return QuotaWindow(
        window=name,
        used=used,
        limit=limit,
        percent=None,
        resets_at=resets_at if turns else None,
    )


def _breakdown(turns: list[ParsedTurn]) -> TokenBreakdown:
    return TokenBreakdown(
        input=sum(t.input_tokens for t in turns),
        output=sum(t.output_tokens for t in turns),
        cache_read=sum(t.cache_read_tokens for t in turns),
        cache_creation=sum(t.cache_creation_tokens for t in turns),
        cache_creation_5m=sum(t.cache_creation_5m for t in turns),
        cache_creation_1h=sum(t.cache_creation_1h for t in turns),
    )


def compute_windows(
    turns: list[ParsedTurn],
    now: datetime,
    limits: dict,
) -> TokenWindows:
    """Bucket turns into 5h / weekly / monthly windows.

    ``now`` must be timezone-aware UTC. ``limits`` maps window names
    (``five_hour``, ``weekly``, ``monthly``) to an integer ceiling or ``None``.
    Sidechain turns are dropped before any counting.
    """
    quota_turns = [turn for turn in turns if not turn.is_sidechain]

    five_hour_start = now - timedelta(hours=5)
    week_start, week_end = _week_bounds(now)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    five_hour_turns = [t for t in quota_turns if t.timestamp >= five_hour_start]
    weekly_turns = [t for t in quota_turns if week_start <= t.timestamp < week_end]
    monthly_turns = [t for t in quota_turns if t.timestamp >= month_start]

    return TokenWindows(
        five_hour=_window(
            "five_hour",
            five_hour_turns,
            limits.get("five_hour"),
            now + timedelta(hours=5),
        ),
        weekly=_window("weekly", weekly_turns, limits.get("weekly"), week_end),
        monthly=_window(
            "monthly", monthly_turns, limits.get("monthly"), _next_month_start(now)
        ),
        breakdown=_breakdown(quota_turns),
    )
