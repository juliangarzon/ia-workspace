"""Tests for the connector framework: base interface, registry, aggregator."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.cache as cache_module
from app.aggregator import build_snapshot
from app.cache import SnapshotCache
from app.main import app
from app.models import (
    ConnectorSnapshot,
    DockerContainer,
    QuotaWindow,
    TokenBreakdown,
    TokenDataAvailability,
    TokenWindows,
)
from app.registry import ConnectorRegistry
from connectors.base import Connector


def _windows(five: int, week: int, month: int, **breakdown: int) -> TokenWindows:
    return TokenWindows(
        five_hour=QuotaWindow(window="five_hour", used=five, limit=None, percent=None, resets_at=None),
        weekly=QuotaWindow(window="weekly", used=week, limit=None, percent=None, resets_at=None),
        monthly=QuotaWindow(window="monthly", used=month, limit=None, percent=None, resets_at=None),
        breakdown=TokenBreakdown(**breakdown),
    )


class StubConnector(Connector):
    """Minimal in-test connector. Proves the extension point."""

    def __init__(
        self,
        connector_id: str,
        *,
        label: str | None = None,
        windows: TokenWindows | None = None,
        is_available: bool = True,
        raises: bool = False,
    ) -> None:
        self._id = connector_id
        self._label = label or connector_id.title()
        self._windows = windows
        self._available = is_available
        self._raises = raises

    @property
    def id(self) -> str:
        return self._id

    @property
    def label(self) -> str:
        return self._label

    @property
    def sources(self) -> list[Path]:
        return [Path(f"/tmp/{self._id}")]

    def available(self) -> bool:
        return self._available

    def collect(self) -> ConnectorSnapshot:
        if self._raises:
            raise RuntimeError("boom")
        return ConnectorSnapshot(
            connector_id=self._id,
            label=self._label,
            available=True,
            token_data=TokenDataAvailability.full,
            token_windows=self._windows,
        )


def test_stub_connector_contributes_to_snapshot():
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=_windows(10, 20, 30, input=5)))

    snapshot = build_snapshot(reg)

    assert len(snapshot.connectors) == 1
    contribution = snapshot.connectors[0]
    assert contribution.connector_id == "claude"
    assert contribution.available is True
    assert contribution.token_windows == _windows(10, 20, 30, input=5)


def test_registry_lookup():
    reg = ConnectorRegistry()
    claude = StubConnector("claude")
    docker = StubConnector("docker")
    reg.register(claude)
    reg.register(docker)

    assert reg.all() == [claude, docker]
    assert reg.get("claude") is claude
    assert reg.get("docker") is docker
    assert reg.get("nope") is None


def test_aggregator_sums_totals_across_connectors():
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=_windows(10, 100, 1000, input=5, output=7)))
    reg.register(StubConnector("codex", windows=_windows(1, 2, 3, input=2, output=3)))

    snapshot = build_snapshot(reg)

    assert snapshot.totals is not None
    assert snapshot.totals.five_hour.used == 11
    assert snapshot.totals.weekly.used == 102
    assert snapshot.totals.monthly.used == 1003
    assert snapshot.totals.breakdown.input == 7
    assert snapshot.totals.breakdown.output == 10
    assert snapshot.totals.five_hour.limit is None


def test_unavailable_connector_excluded_from_totals():
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=_windows(10, 20, 30)))
    unavailable = StubConnector("codex", windows=_windows(999, 999, 999))
    unavailable.collect = lambda: ConnectorSnapshot(  # type: ignore[method-assign]
        connector_id="codex",
        label="Codex",
        available=False,
        token_data=TokenDataAvailability.unavailable,
        token_windows=None,
    )
    reg.register(unavailable)

    snapshot = build_snapshot(reg)

    assert snapshot.totals is not None
    assert snapshot.totals.five_hour.used == 10


def test_failing_connector_is_isolated():
    reg = ConnectorRegistry()
    reg.register(StubConnector("good", windows=_windows(5, 5, 5)))
    reg.register(StubConnector("bad", raises=True))

    snapshot = build_snapshot(reg)

    by_id = {c.connector_id: c for c in snapshot.connectors}
    assert by_id["bad"].available is False
    assert by_id["bad"].token_data == TokenDataAvailability.unavailable
    assert by_id["bad"].token_windows is None
    assert snapshot.totals is not None
    assert snapshot.totals.five_hour.used == 5


def test_docker_containers_collected_from_docker_connector():
    container = DockerContainer(
        id="abc",
        name="web",
        image="nginx",
        status="running",
        uptime_seconds=10,
        cpu_percent=1.0,
        memory_used_mb=10.0,
        memory_limit_mb=100.0,
    )

    class DockerStub(StubConnector):
        def docker_containers(self) -> list[DockerContainer]:
            return [container]

    reg = ConnectorRegistry()
    reg.register(DockerStub("docker"))

    snapshot = build_snapshot(reg)

    assert snapshot.docker_containers == [container]


def test_no_token_data_yields_none_totals():
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=None))

    snapshot = build_snapshot(reg)

    assert snapshot.totals is None


def test_healthz_reports_per_connector_sources():
    from app.registry import registry as global_registry

    global_registry.register(StubConnector("claude", is_available=True))
    global_registry.register(StubConnector("docker", is_available=False))
    try:
        with TestClient(app) as client:
            response = client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["sources"]["claude"] is True
        assert body["sources"]["docker"] is False
    finally:
        global_registry._connectors.clear()


def _counting_build(monkeypatch) -> dict[str, int]:
    calls = {"count": 0}
    real = cache_module.build_snapshot

    def counted(reg, project_paths=None):
        calls["count"] += 1
        return real(reg, project_paths)

    monkeypatch.setattr(cache_module, "build_snapshot", counted)
    return calls


def test_cache_ttl_hit_rebuilds_once(monkeypatch):
    calls = _counting_build(monkeypatch)
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=_windows(1, 2, 3)))
    cache = SnapshotCache(ttl_seconds=60, registry=reg)

    cache.get()
    cache.get()

    assert calls["count"] == 1


def test_cache_ttl_expiry_rebuilds_each_time(monkeypatch):
    calls = _counting_build(monkeypatch)
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=_windows(1, 2, 3)))
    cache = SnapshotCache(ttl_seconds=0, registry=reg)

    cache.get()
    cache.get()

    assert calls["count"] == 2


def test_cache_invalidate_forces_rebuild(monkeypatch):
    calls = _counting_build(monkeypatch)
    reg = ConnectorRegistry()
    reg.register(StubConnector("claude", windows=_windows(1, 2, 3)))
    cache = SnapshotCache(ttl_seconds=60, registry=reg)

    cache.get()
    cache.invalidate()
    cache.get()

    assert calls["count"] == 2


def test_api_snapshot_returns_expected_shape():
    from app.registry import registry as global_registry

    global_registry.register(StubConnector("claude", windows=_windows(1, 2, 3)))
    try:
        with TestClient(app) as client:
            response = client.get("/api/snapshot")

        assert response.status_code == 200
        body = response.json()
        assert set(body) >= {
            "captured_at",
            "connectors",
            "docker_containers",
            "projects",
            "totals",
        }
    finally:
        global_registry._connectors.clear()


def test_healthz_includes_cache_age_after_snapshot():
    from app.registry import registry as global_registry

    global_registry.register(StubConnector("claude", windows=_windows(1, 2, 3)))
    try:
        with TestClient(app) as client:
            client.get("/api/snapshot")
            response = client.get("/healthz")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["cache_age_seconds"], (int, float))
    finally:
        global_registry._connectors.clear()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
