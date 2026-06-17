"""Aggregates workspace state from registered connectors into one snapshot."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from app.models import (
    ConnectorSnapshot,
    DockerContainer,
    QuotaWindow,
    Project,
    Snapshot,
    TokenBreakdown,
    TokenDataAvailability,
    TokenWindows,
)
from app.registry import ConnectorRegistry, registry
from connectors.git_connector import read_projects

logger = logging.getLogger(__name__)


def _safe_collect(connector) -> ConnectorSnapshot:
    """Collect from a connector, defending against contract violations.

    ``collect()`` is documented never to raise. If one does anyway, log it and
    substitute an unavailable snapshot so a single bad connector cannot take
    down the whole aggregation.
    """
    try:
        return connector.collect()
    except Exception:
        logger.exception("Connector %s raised during collect()", connector.id)
        return ConnectorSnapshot(
            connector_id=connector.id,
            label=connector.label,
            available=False,
            token_data=TokenDataAvailability.unavailable,
            token_windows=None,
        )


def _sum_breakdowns(breakdowns: list[TokenBreakdown]) -> TokenBreakdown:
    return TokenBreakdown(
        input=sum(b.input for b in breakdowns),
        output=sum(b.output for b in breakdowns),
        cache_read=sum(b.cache_read for b in breakdowns),
        cache_creation=sum(b.cache_creation for b in breakdowns),
        cache_creation_5m=sum(b.cache_creation_5m for b in breakdowns),
        cache_creation_1h=sum(b.cache_creation_1h for b in breakdowns),
    )


def _sum_window(window, windows: list[TokenWindows]) -> QuotaWindow:
    used = sum(getattr(w, window).used for w in windows)
    return QuotaWindow(window=window, used=used, limit=None, percent=None, resets_at=None)


def _compute_totals(contributions: list[ConnectorSnapshot]) -> TokenWindows | None:
    windows = [
        c.token_windows
        for c in contributions
        if c.available
        and c.token_data != TokenDataAvailability.unavailable
        and c.token_windows is not None
    ]
    if not windows:
        return None

    return TokenWindows(
        five_hour=_sum_window("five_hour", windows),
        weekly=_sum_window("weekly", windows),
        monthly=_sum_window("monthly", windows),
        breakdown=_sum_breakdowns([w.breakdown for w in windows]),
    )


def _docker_containers(reg: ConnectorRegistry) -> list[DockerContainer]:
    docker = reg.get("docker")
    if docker is None:
        return []
    getter = getattr(docker, "docker_containers", None)
    if getter is None:
        return []
    return list(getter())


def _projects(project_paths: list[Path] | None) -> list[Project]:
    if not project_paths:
        return []
    return read_projects([Path(p).expanduser() for p in project_paths])


def build_snapshot(
    reg: ConnectorRegistry = registry,
    project_paths: list[Path] | None = None,
) -> Snapshot:
    """Collect every registered connector and merge into one Snapshot.

    Sums token windows across connectors that report data into ``totals``.
    Docker containers come from the connector with id ``"docker"`` (if any).
    Projects come from ``project_paths`` (read-only git state); empty if none.
    """
    contributions = [_safe_collect(c) for c in reg.all()]

    return Snapshot(
        captured_at=datetime.now(timezone.utc),
        connectors=contributions,
        docker_containers=_docker_containers(reg),
        projects=_projects(project_paths),
        totals=_compute_totals(contributions),
    )
