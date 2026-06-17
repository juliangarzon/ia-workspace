"""Base connector interface for workspace sources.

A connector reads one external source (Claude state dir, Docker, git repos, ...)
and normalizes it into a :class:`ConnectorSnapshot`. The aggregator merges all
registered connectors into a single :class:`~app.models.Snapshot`.

Contract: ``collect()`` must never raise. On any failure it returns a snapshot
with ``available=False`` and ``token_data=unavailable``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.models import ConnectorSnapshot


class Connector(ABC):
    """Read one workspace source and produce a normalized snapshot."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Stable machine ID, e.g. ``'claude'``, ``'docker'``."""

    @property
    @abstractmethod
    def label(self) -> str:
        """Human display name, e.g. ``'Claude'``."""

    @property
    @abstractmethod
    def sources(self) -> list[Path]:
        """Declared source paths. Used by ``/healthz`` to report availability."""

    @abstractmethod
    def available(self) -> bool:
        """True if at least one source path exists and is readable."""

    @abstractmethod
    def collect(self) -> ConnectorSnapshot:
        """Read sources and return a normalized snapshot contribution.

        Must never raise. Return a :class:`ConnectorSnapshot` with
        ``available=False`` on error.
        """
