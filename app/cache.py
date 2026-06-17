"""In-process snapshot cache with a time-to-live.

The aggregator is cheap but not free: it reads connector state on every call.
This cache holds the last :class:`~app.models.Snapshot` and rebuilds it only
once the TTL has elapsed, so bursts of requests share one build.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.aggregator import build_snapshot
from app.models import Snapshot
from app.registry import ConnectorRegistry


class SnapshotCache:
    """In-process cache for the aggregated snapshot. Thread-safe via a lock."""

    def __init__(
        self,
        ttl_seconds: int,
        registry: ConnectorRegistry,
        project_paths: list[Path] | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._registry = registry
        self._project_paths = project_paths
        self._lock = threading.Lock()
        self._snapshot: Snapshot | None = None
        self._built_at: float | None = None

    def get(self) -> Snapshot:
        """Return cached snapshot if fresh, else rebuild and cache it."""
        with self._lock:
            if self._snapshot is not None and self._is_fresh():
                return self._snapshot
            snapshot = build_snapshot(self._registry, self._project_paths)
            self._snapshot = snapshot
            self._built_at = time.monotonic()
            return snapshot

    def invalidate(self) -> None:
        """Force next get() to rebuild."""
        with self._lock:
            self._built_at = None

    def age_seconds(self) -> float | None:
        """Seconds since the last build, or ``None`` if never built."""
        with self._lock:
            if self._built_at is None:
                return None
            return time.monotonic() - self._built_at

    def _is_fresh(self) -> bool:
        if self._built_at is None:
            return False
        return time.monotonic() - self._built_at < self._ttl_seconds
