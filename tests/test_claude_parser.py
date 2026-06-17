"""Tests for the Claude transcript JSONL parser."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

from connectors.claude_parser import ParsedTurn, estimate_cost, parse_transcript

FIXTURES = Path(__file__).parent / "fixtures" / "claude"


def _by_id(turns: list[ParsedTurn]) -> dict[str, ParsedTurn]:
    return {turn.message_id: turn for turn in turns}


def test_dedup_drops_zero_token_turn() -> None:
    turns, _ = parse_transcript(FIXTURES / "valid_transcript.jsonl")
    ids = {turn.message_id for turn in turns}
    assert ids == {"msg_001", "msg_003"}
    assert len(turns) == 2


def test_last_chunk_wins_for_duplicate_id() -> None:
    turns, _ = parse_transcript(FIXTURES / "valid_transcript.jsonl")
    msg_001 = _by_id(turns)["msg_001"]
    assert msg_001.input_tokens == 200
    assert msg_001.output_tokens == 80
    assert msg_001.cost_usd is None  # B's null replaces A's 0.001


def test_sidechain_turn_kept() -> None:
    turns, _ = parse_transcript(FIXTURES / "valid_transcript.jsonl")
    msg_003 = _by_id(turns)["msg_003"]
    assert msg_003.is_sidechain is True


def test_tiered_cache_parsed() -> None:
    turns, _ = parse_transcript(FIXTURES / "valid_transcript.jsonl")
    msg_001 = _by_id(turns)["msg_001"]
    assert msg_001.cache_creation_5m == 1234
    assert msg_001.cache_creation_1h == 0


def test_timestamp_is_utc() -> None:
    turns, _ = parse_transcript(FIXTURES / "valid_transcript.jsonl")
    assert all(turn.timestamp.tzinfo == timezone.utc for turn in turns)


def test_malformed_counts_errors_without_raising() -> None:
    turns, error_count = parse_transcript(FIXTURES / "malformed.jsonl")
    assert error_count >= 2
    assert len(turns) == 1
    assert turns[0].message_id == "msg_100"


def test_malformed_file_returns_partial_results() -> None:
    turns, error_count = parse_transcript(FIXTURES / "malformed.jsonl")
    assert turns  # partial results survive the bad lines
    assert error_count >= 2


def test_estimate_cost_known_model() -> None:
    turn = ParsedTurn(
        message_id="m",
        session_id="s",
        timestamp=None,  # type: ignore[arg-type]
        model="claude-opus-4-7",
        git_branch=None,
        is_sidechain=False,
        cost_usd=None,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_tokens=1_000_000,
        cache_read_tokens=1_000_000,
        cache_creation_5m=0,
        cache_creation_1h=0,
        service_tier="standard",
    )
    # opus-4 prefix: input 5, output 25, cache_read 0.5, cache_creation 6.25
    assert estimate_cost(turn) == 5.0 + 25.0 + 0.5 + 6.25


def test_estimate_cost_unknown_model_is_zero() -> None:
    turn = ParsedTurn(
        message_id="m",
        session_id="s",
        timestamp=None,  # type: ignore[arg-type]
        model="gpt-9000",
        git_branch=None,
        is_sidechain=False,
        cost_usd=None,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cache_creation_5m=0,
        cache_creation_1h=0,
        service_tier=None,
    )
    assert estimate_cost(turn) == 0.0
