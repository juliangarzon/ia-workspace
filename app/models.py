"""Pydantic models for workspace state and quota data."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "QuotaWindow",
    "TokenBreakdown",
    "TokenWindows",
    "ActivityState",
    "Session",
    "ScheduledTask",
    "PortMapping",
    "DockerContainer",
    "Project",
    "TokenDataAvailability",
    "ConnectorSnapshot",
    "Snapshot",
]


class QuotaWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    window: Literal["five_hour", "weekly", "monthly"]
    used: int
    limit: int | None
    percent: float | None
    resets_at: datetime | None

    @model_validator(mode="after")
    def _derive_percent(self) -> QuotaWindow:
        if self.limit is None:
            if self.percent is not None:
                object.__setattr__(self, "percent", None)
        elif self.percent is None:
            value = (self.used / self.limit * 100) if self.limit else None
            object.__setattr__(self, "percent", value)
        return self


class TokenBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    cache_creation_5m: int = 0
    cache_creation_1h: int = 0


class TokenWindows(BaseModel):
    model_config = ConfigDict(frozen=True)

    five_hour: QuotaWindow
    weekly: QuotaWindow
    monthly: QuotaWindow
    breakdown: TokenBreakdown


class ActivityState(str, Enum):
    thinking = "thinking"
    active = "active"
    idle = "idle"
    stale = "stale"


class Session(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    cwd: str | None
    git_branch: str | None
    model: str | None
    activity_state: ActivityState
    last_event_at: datetime | None
    is_sidechain: bool = False
    started_at: datetime | None
    cost_usd: float | None


class ScheduledTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    schedule: str | None
    next_run: datetime | None


class PortMapping(BaseModel):
    model_config = ConfigDict(frozen=True)

    host: int
    container: int
    protocol: Literal["tcp", "udp"] = "tcp"


class DockerContainer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    image: str
    status: Literal["running", "stopped", "paused", "exited", "unknown"]
    uptime_seconds: int | None
    cpu_percent: float | None
    memory_used_mb: float | None
    memory_limit_mb: float | None
    ports: list[PortMapping] = []


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    path: str
    branch: str | None
    dirty: bool | None
    ahead: int | None
    behind: int | None
    last_commit_message: str | None
    last_commit_at: datetime | None
    last_activity_at: datetime | None


class TokenDataAvailability(str, Enum):
    full = "full"
    best_effort = "best_effort"
    unavailable = "unavailable"


class ConnectorSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    connector_id: str
    label: str
    available: bool
    token_data: TokenDataAvailability
    token_windows: TokenWindows | None
    sessions: list[Session] = []
    scheduled_tasks: list[ScheduledTask] = []
    parse_errors: int = 0


class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    captured_at: datetime
    connectors: list[ConnectorSnapshot] = []
    docker_containers: list[DockerContainer] = []
    projects: list[Project] = []
    totals: TokenWindows | None
