"""Tests for the projects API, including path-traversal hardening.

The ``{name}`` path parameter is only ever matched against the known project
list in the snapshot; it is never used to build a filesystem path. Traversal
attempts therefore fall through to a 404.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import Project, Snapshot


def _snapshot_with(*projects: Project) -> Snapshot:
    return Snapshot(
        captured_at=datetime.now(timezone.utc), projects=list(projects), totals=None
    )


def _project(name: str) -> Project:
    return Project(
        name=name,
        path=f"/fake/{name}",
        branch="main",
        dirty=False,
        ahead=0,
        behind=0,
        last_commit_message="init",
        last_commit_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
    )


class _StubCache:
    def __init__(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot

    def get(self) -> Snapshot:
        return self._snapshot

    def age_seconds(self) -> float:
        return 0.0


def _client_with(*projects: Project) -> TestClient:
    client = TestClient(app)
    client.__enter__()
    app.state.cache = _StubCache(_snapshot_with(*projects))
    return client


def test_known_project_returns_200() -> None:
    client = _client_with(_project("workspace-monitor"))
    try:
        response = client.get("/api/projects/workspace-monitor")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "workspace-monitor"
    assert body["branch"] == "main"


def test_unknown_project_returns_404() -> None:
    client = _client_with(_project("workspace-monitor"))
    try:
        response = client.get("/api/projects/nope")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 404


def test_path_traversal_blocked() -> None:
    client = _client_with(_project("workspace-monitor"))
    try:
        response = client.get("/api/projects/../etc/passwd")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 404


def test_encoded_traversal_reaches_route_and_is_rejected() -> None:
    """An encoded ``../`` survives client normalization and hits the route as a
    raw ``name``. The lookup is against the known list, so it still 404s."""
    client = _client_with(_project("workspace-monitor"))
    try:
        response = client.get("/api/projects/..%2Fetc%2Fpasswd")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code == 404


def test_empty_name_handled() -> None:
    client = _client_with(_project("workspace-monitor"))
    try:
        response = client.get("/api/projects/")
    finally:
        client.__exit__(None, None, None)

    assert response.status_code in (404, 422)
