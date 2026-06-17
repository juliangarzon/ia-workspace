"""Tests for the read-only Docker connector.

The Docker client is fully stubbed; these tests never touch a real socket or
daemon. The critical guarantee is that the connector issues no mutating calls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import docker
import pytest

from connectors.docker_connector import DockerConnector

MUTATING_CONTAINER_METHODS = (
    "start",
    "stop",
    "restart",
    "remove",
    "kill",
    "pause",
    "unpause",
)


def _running_container() -> MagicMock:
    container = MagicMock()
    container.short_id = "abc123"
    container.name = "/web"
    container.status = "running"
    container.image = SimpleNamespace(tags=["nginx:latest"], short_id="sha256:dead")
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    container.attrs = {"State": {"StartedAt": started_at}}
    container.ports = {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"}]}
    container.stats.return_value = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 200, "percpu_usage": [1, 1]},
            "system_cpu_usage": 2000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 100},
            "system_cpu_usage": 1000,
        },
        "memory_stats": {
            "usage": 100 * 1024 * 1024,
            "stats": {"cache": 20 * 1024 * 1024},
            "limit": 512 * 1024 * 1024,
        },
    }
    return container


def _stopped_container() -> MagicMock:
    container = MagicMock()
    container.short_id = "def456"
    container.name = "/worker"
    container.status = "exited"
    container.image = SimpleNamespace(tags=[], short_id="sha256:beef")
    container.attrs = {"State": {"StartedAt": "0001-01-01T00:00:00Z"}}
    container.ports = {}
    container.stats.side_effect = docker.errors.DockerException("no stats")
    return container


def _client_with(containers: list) -> MagicMock:
    client = MagicMock()
    client.containers.list.return_value = containers
    return client


@patch("connectors.docker_connector._SOCKET")
@patch("connectors.docker_connector.docker.from_env")
def test_no_mutating_calls(from_env: MagicMock, socket: MagicMock) -> None:
    socket.exists.return_value = True
    container = _running_container()
    client = _client_with([container])
    from_env.return_value = client

    DockerConnector().docker_containers()

    client.containers.run.assert_not_called()
    client.containers.prune.assert_not_called()
    for method in MUTATING_CONTAINER_METHODS:
        getattr(container, method).assert_not_called()


@patch("connectors.docker_connector._SOCKET")
@patch("connectors.docker_connector.docker.from_env")
def test_container_mapping(from_env: MagicMock, socket: MagicMock) -> None:
    socket.exists.return_value = True
    from_env.return_value = _client_with([_running_container()])

    containers = DockerConnector().docker_containers()

    assert len(containers) == 1
    c = containers[0]
    assert c.id == "abc123"
    assert c.name == "web"
    assert c.image == "nginx:latest"
    assert c.status == "running"
    assert c.uptime_seconds is not None and c.uptime_seconds >= 0
    assert c.cpu_percent == pytest.approx((100 / 1000) * 2 * 100.0)
    assert c.memory_used_mb == pytest.approx(80.0)
    assert c.memory_limit_mb == pytest.approx(512.0)
    assert len(c.ports) == 1
    assert c.ports[0].host == 8080
    assert c.ports[0].container == 80
    assert c.ports[0].protocol == "tcp"


@patch("connectors.docker_connector._SOCKET")
def test_socket_absent(socket: MagicMock) -> None:
    socket.exists.return_value = False
    connector = DockerConnector()

    assert connector.available() is False
    assert connector.docker_containers() == []


@patch("connectors.docker_connector._SOCKET")
@patch("connectors.docker_connector.docker.from_env")
def test_docker_unavailable(from_env: MagicMock, socket: MagicMock) -> None:
    socket.exists.return_value = True
    from_env.side_effect = docker.errors.DockerException("daemon down")

    assert DockerConnector().docker_containers() == []


@patch("connectors.docker_connector._SOCKET")
@patch("connectors.docker_connector.docker.from_env")
def test_stopped_container_no_stats(from_env: MagicMock, socket: MagicMock) -> None:
    socket.exists.return_value = True
    from_env.return_value = _client_with([_stopped_container()])

    containers = DockerConnector().docker_containers()

    assert len(containers) == 1
    c = containers[0]
    assert c.status == "exited"
    assert c.cpu_percent is None
    assert c.memory_used_mb is None
    assert c.memory_limit_mb is None
    assert c.uptime_seconds == 0
    assert c.image == "sha256:beef"


def test_api_docker_shape() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        snapshot = client.get("/api/snapshot").json()
        assert "docker_containers" in snapshot

        response = client.get("/api/docker")
        assert response.status_code == 200
        body = response.json()
        assert "containers" in body
        assert isinstance(body["containers"], list)
