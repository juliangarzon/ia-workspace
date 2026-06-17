"""Docker connector: read-only container inventory from the Docker daemon.

Talks to the local Docker socket and normalizes the running container set into
:class:`~app.models.DockerContainer` records. Issues only read calls
(``containers.list``, ``container.stats``, ``container.attrs``) and never any
mutating operation. Both :meth:`collect` and :meth:`docker_containers` swallow
all errors and degrade to an empty/unavailable result.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import docker

from app.models import (
    ConnectorSnapshot,
    DockerContainer,
    PortMapping,
    TokenDataAvailability,
)
from connectors.base import Connector

_SOCKET = Path("/var/run/docker.sock")

_STATUS_MAP = {
    "running": "running",
    "exited": "exited",
    "paused": "paused",
    "created": "stopped",
    "dead": "stopped",
}


class DockerConnector(Connector):
    id = "docker"
    label = "Docker"

    @property
    def sources(self) -> list[Path]:
        return [_SOCKET]

    def available(self) -> bool:
        return _SOCKET.exists()

    def collect(self) -> ConnectorSnapshot:
        """Report connector availability. Container data is exposed separately.

        Docker contributes no token windows, so this snapshot is mostly a health
        signal for ``/healthz`` and the connector list. Returns ``available=False``
        on any error.
        """
        try:
            available = self.available() and self._client() is not None
        except Exception:
            available = False
        return ConnectorSnapshot(
            connector_id=self.id,
            label=self.label,
            available=available,
            token_data=TokenDataAvailability.unavailable,
            token_windows=None,
        )

    def docker_containers(self) -> list[DockerContainer]:
        """Return the current container list, or ``[]`` if Docker is unavailable."""
        if not self.available():
            return []
        try:
            client = self._client()
            if client is None:
                return []
            containers = client.containers.list(all=True)
        except Exception:
            return []
        return [_map_container(c) for c in containers]

    def _client(self) -> docker.DockerClient | None:
        try:
            return docker.from_env()
        except docker.errors.DockerException:
            return None


def _map_container(container: object) -> DockerContainer:
    stats = _safe_stats(container)
    return DockerContainer(
        id=container.short_id,
        name=container.name.lstrip("/"),
        image=_image_ref(container),
        status=_map_status(container.status),
        uptime_seconds=_compute_uptime(container),
        cpu_percent=_cpu_percent(container, stats),
        memory_used_mb=_memory_used_mb(stats),
        memory_limit_mb=_memory_limit_mb(stats),
        ports=_parse_ports(container),
    )


def _map_status(status: str) -> str:
    return _STATUS_MAP.get(status, "unknown")


def _image_ref(container: object) -> str:
    image = container.image
    tags = getattr(image, "tags", None) or []
    if tags:
        return tags[0]
    return image.short_id


def _safe_stats(container: object) -> dict | None:
    if container.status != "running":
        return None
    try:
        return container.stats(stream=False)
    except Exception:
        return None


def _compute_uptime(container: object) -> int:
    if container.status != "running":
        return 0
    try:
        started_raw = container.attrs["State"]["StartedAt"]
    except (KeyError, TypeError):
        return 0
    started = _parse_iso8601(started_raw)
    if started is None:
        return 0
    delta = datetime.now(timezone.utc) - started
    return max(0, int(delta.total_seconds()))


def _parse_iso8601(value: str) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    if "." in normalized:
        head, _, tail = normalized.partition(".")
        offset = ""
        for sign in ("+", "-"):
            if sign in tail:
                frac, _, off = tail.partition(sign)
                offset = sign + off
                tail = frac
                break
        normalized = f"{head}.{tail[:6]}{offset}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _cpu_percent(container: object, stats: dict | None) -> float | None:
    if stats is None:
        return None
    try:
        cpu_stats = stats["cpu_stats"]
        precpu_stats = stats["precpu_stats"]
        cpu_delta = (
            cpu_stats["cpu_usage"]["total_usage"]
            - precpu_stats["cpu_usage"]["total_usage"]
        )
        system_delta = cpu_stats["system_cpu_usage"] - precpu_stats["system_cpu_usage"]
        num_cpus = cpu_stats.get("online_cpus") or len(
            cpu_stats["cpu_usage"].get("percpu_usage", [1])
        )
    except (KeyError, TypeError):
        return None
    if system_delta > 0:
        return (cpu_delta / system_delta) * num_cpus * 100.0
    return 0.0


def _memory_used_mb(stats: dict | None) -> float | None:
    if stats is None:
        return None
    try:
        mem_stats = stats["memory_stats"]
        used_bytes = mem_stats.get("usage", 0) - mem_stats.get("stats", {}).get(
            "cache", 0
        )
    except (KeyError, TypeError):
        return None
    return used_bytes / (1024 * 1024)


def _memory_limit_mb(stats: dict | None) -> float | None:
    if stats is None:
        return None
    limit_bytes = stats.get("memory_stats", {}).get("limit")
    if limit_bytes is None:
        return None
    return limit_bytes / (1024 * 1024)


def _parse_ports(container: object) -> list[PortMapping]:
    ports = getattr(container, "ports", None) or {}
    mappings: list[PortMapping] = []
    for key, bindings in ports.items():
        if not bindings:
            continue
        container_port, _, proto = key.partition("/")
        protocol = proto if proto in ("tcp", "udp") else "tcp"
        for binding in bindings:
            host_port = binding.get("HostPort")
            if host_port is None:
                continue
            try:
                mappings.append(
                    PortMapping(
                        host=int(host_port),
                        container=int(container_port),
                        protocol=protocol,
                    )
                )
            except (ValueError, TypeError):
                continue
    return mappings
