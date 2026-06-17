"""Configuration loading for the workspace monitor.

Reads ``config.json`` from the project root, expands user paths, and exposes a
typed :class:`Config` model with sane defaults for any missing optional keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"


class QuotaLimits(BaseModel):
    """Optional quota ceilings. ``None`` means no configured limit."""

    five_hour: int | None = None
    weekly: int | None = None
    monthly: int | None = None


class Config(BaseModel):
    """Top-level application configuration."""

    poll_interval_seconds: int = 5
    cache_ttl_seconds: int = 60
    claude_state_path: str = "~/.claude"
    projects: list[str] = Field(default_factory=list)
    quota_limits: QuotaLimits = Field(default_factory=QuotaLimits)

    @property
    def claude_state_dir(self) -> Path:
        return Path(self.claude_state_path).expanduser()


def load_config(path: Path | str | None = None) -> Config:
    """Load configuration from ``config.json``.

    Missing optional keys fall back to the model defaults. A missing file
    yields a fully defaulted configuration.
    """

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return Config()

    try:
        raw = json.loads(config_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in config.json: {e}") from e
    return Config.model_validate(raw)
