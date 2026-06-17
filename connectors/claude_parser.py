"""Streaming parser for Claude transcript JSONL files.

Claude writes one JSON object per line. Assistant turns can be emitted as
multiple streaming chunks sharing one ``message.id``; only the last chunk holds
the final token usage, so we deduplicate by keeping the last record per id.

The parser never raises. Malformed lines are counted and skipped so a single
corrupt line cannot sink a whole transcript.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PRICE_PER_MILLION: dict[str, tuple[float, float, float, float]] = {
    # model prefix: (input, output, cache_read, cache_creation) USD per 1M tokens
    "claude-fable-5": (10.0, 50.0, 1.0, 12.50),
    "claude-opus-4": (5.0, 25.0, 0.5, 6.25),
    "claude-sonnet-4": (3.0, 15.0, 0.3, 3.75),
    "claude-haiku-4": (1.0, 5.0, 0.1, 1.25),
}


@dataclass
class ParsedTurn:
    """One deduplicated turn from a Claude transcript."""

    message_id: str
    session_id: str
    timestamp: datetime  # UTC
    model: str | None
    git_branch: str | None
    is_sidechain: bool
    cost_usd: float | None  # None when not present or null in JSONL
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int  # flat field
    cache_read_tokens: int
    cache_creation_5m: int  # from cache_creation.ephemeral_5m_input_tokens
    cache_creation_1h: int  # from cache_creation.ephemeral_1h_input_tokens
    service_tier: str | None  # "standard" | "fast"


def _parse_timestamp(raw: str | None) -> datetime:
    if not raw:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_int(value: object) -> int:
    return value if isinstance(value, int) else 0


def _build_turn(record: dict) -> ParsedTurn | None:
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    message_id = message.get("id")
    if not message_id:
        return None

    usage = message.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    cache_creation = usage.get("cache_creation")
    cache_creation = cache_creation if isinstance(cache_creation, dict) else {}

    cost = record.get("costUSD")
    cost_usd = float(cost) if isinstance(cost, (int, float)) else None

    return ParsedTurn(
        message_id=message_id,
        session_id=record.get("sessionId") or "",
        timestamp=_parse_timestamp(record.get("timestamp")),
        model=message.get("model"),
        git_branch=record.get("gitBranch"),
        is_sidechain=bool(record.get("isSidechain", False)),
        cost_usd=cost_usd,
        input_tokens=_to_int(usage.get("input_tokens")),
        output_tokens=_to_int(usage.get("output_tokens")),
        cache_creation_tokens=_to_int(usage.get("cache_creation_input_tokens")),
        cache_read_tokens=_to_int(usage.get("cache_read_input_tokens")),
        cache_creation_5m=_to_int(cache_creation.get("ephemeral_5m_input_tokens")),
        cache_creation_1h=_to_int(cache_creation.get("ephemeral_1h_input_tokens")),
        service_tier=usage.get("service_tier"),
    )


def parse_transcript(path: Path) -> tuple[list[ParsedTurn], int]:
    """Parse a single JSONL transcript file.

    Returns ``(turns, parse_error_count)``. Deduplicates by ``message.id``
    (last chunk wins), drops turns with zero total tokens, and never raises.
    """
    latest: dict[str, ParsedTurn] = {}
    order: dict[str, int] = {}
    error_count = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if not line.strip():
                continue
            if '"usage":' not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                error_count += 1
                continue
            if not isinstance(record, dict) or record.get("type") != "assistant":
                continue
            turn = _build_turn(record)
            if turn is None:
                continue
            if turn.message_id not in order:
                order[turn.message_id] = index
            latest[turn.message_id] = turn

    turns = [
        turn
        for turn in sorted(latest.values(), key=lambda t: order[t.message_id])
        if (
            turn.input_tokens
            + turn.output_tokens
            + turn.cache_creation_tokens
            + turn.cache_read_tokens
        )
        > 0
    ]
    return turns, error_count


def parse_session_transcripts(session_dir: Path) -> tuple[list[ParsedTurn], int]:
    """Parse all JSONL files under a session directory.

    Returns merged ``(turns, total_parse_errors)``. Deduplication is applied
    per file; ids are assumed unique across a session's transcript files.
    """
    all_turns: list[ParsedTurn] = []
    total_errors = 0
    for path in sorted(session_dir.glob("*.jsonl")):
        turns, errors = parse_transcript(path)
        all_turns.extend(turns)
        total_errors += errors
    return all_turns, total_errors


def _lookup_prices(model: str | None) -> tuple[float, float, float, float] | None:
    if not model:
        return None
    exact = PRICE_PER_MILLION.get(model)
    if exact is not None:
        return exact
    for prefix, prices in PRICE_PER_MILLION.items():
        if model.startswith(prefix):
            return prices
    return None


def estimate_cost(turn: ParsedTurn) -> float:
    """Estimate cost from token counts. Returns 0.0 if model unknown."""
    prices = _lookup_prices(turn.model)
    if prices is None:
        return 0.0
    input_rate, output_rate, cache_read_rate, cache_creation_rate = prices
    return (
        turn.input_tokens * input_rate
        + turn.output_tokens * output_rate
        + turn.cache_read_tokens * cache_read_rate
        + turn.cache_creation_tokens * cache_creation_rate
    ) / 1_000_000
