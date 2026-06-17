"""API surface and resilience tests.

Covers endpoint response shapes, the project lookup hardening, the root HTML
smoke test, and two degraded-mode scenarios (a connector that raises mid-collect
and a connector reporting itself unavailable). Resilience cases build a real
snapshot via :func:`build_snapshot` over mock connectors, then inject it through
a stub cache so the endpoint exercises the same serialization path as production.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.aggregator import build_snapshot
from app.main import app
from app.models import (
    ConnectorSnapshot,
    QuotaWindow,
    Snapshot,
    TokenBreakdown,
    TokenDataAvailability,
    TokenWindows,
)
from app.registry import ConnectorRegistry
from connectors.base import Connector


def _windows(used: int) -> TokenWindows:
    return TokenWindows(
        five_hour=QuotaWindow(window="five_hour", used=used, limit=None, percent=None, resets_at=None),
        weekly=QuotaWindow(window="weekly", used=used, limit=None, percent=None, resets_at=None),
        monthly=QuotaWindow(window="monthly", used=used, limit=None, percent=None, resets_at=None),
        breakdown=TokenBreakdown(),
    )


class MockConnector(Connector):
    """In-test connector matching the test_framework.py pattern."""

    def __init__(
        self,
        connector_id: str,
        *,
        is_available: bool = True,
        raises: bool = False,
    ) -> None:
        self._id = connector_id
        self._available = is_available
        self._raises = raises

    @property
    def id(self) -> str:
        return self._id

    @property
    def label(self) -> str:
        return self._id.title()

    @property
    def sources(self) -> list[Path]:
        return [Path(f"/tmp/{self._id}")]

    def available(self) -> bool:
        return self._available

    def collect(self) -> ConnectorSnapshot:
        if self._raises:
            raise RuntimeError("truncated JSONL midway")
        return ConnectorSnapshot(
            connector_id=self._id,
            label=self.label,
            available=self._available,
            token_data=(
                TokenDataAvailability.full
                if self._available
                else TokenDataAvailability.unavailable
            ),
            token_windows=_windows(1) if self._available else None,
        )


class _StubCache:
    def __init__(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot

    def get(self) -> Snapshot:
        return self._snapshot

    def age_seconds(self) -> float:
        return 0.0


def _client() -> TestClient:
    client = TestClient(app)
    client.__enter__()
    return client


def _client_with_snapshot(snapshot: Snapshot) -> TestClient:
    client = _client()
    app.state.cache = _StubCache(snapshot)
    return client


def test_snapshot_endpoint_shape() -> None:
    client = _client()
    try:
        response = client.get("/api/snapshot")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "captured_at",
        "connectors",
        "docker_containers",
        "projects",
        "totals",
    }


def test_docker_endpoint_shape() -> None:
    client = _client()
    try:
        response = client.get("/api/docker")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    body = response.json()
    assert "containers" in body
    assert isinstance(body["containers"], list)


def test_healthz_shape() -> None:
    client = _client()
    try:
        response = client.get("/healthz")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "sources" in body
    assert "cache_age_seconds" in body


def test_unknown_project_returns_404() -> None:
    client = _client()
    try:
        response = client.get("/api/projects/unknown")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 404


def test_path_traversal_blocked() -> None:
    client = _client()
    try:
        response = client.get("/api/projects/../etc/passwd")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code in (404, 422)


def test_resilience_connector_raises_midway_returns_200() -> None:
    reg = ConnectorRegistry()
    reg.register(MockConnector("good"))
    reg.register(MockConnector("bad", raises=True))
    snapshot = build_snapshot(reg)

    client = _client_with_snapshot(snapshot)
    try:
        response = client.get("/api/snapshot")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    by_id = {c["connector_id"]: c for c in response.json()["connectors"]}
    assert by_id["bad"]["available"] is False


def test_resilience_unavailable_source_reported() -> None:
    reg = ConnectorRegistry()
    reg.register(MockConnector("codex", is_available=False))
    snapshot = build_snapshot(reg)

    client = _client_with_snapshot(snapshot)
    try:
        response = client.get("/api/snapshot")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    by_id = {c["connector_id"]: c for c in response.json()["connectors"]}
    assert by_id["codex"]["available"] is False


def test_root_serves_html() -> None:
    client = _client()
    try:
        response = client.get("/")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
