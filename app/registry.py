"""Connector registry.

Holds the set of connectors the aggregator collects from. A module-level
:data:`registry` singleton is used by the running app; tests create their own
:class:`ConnectorRegistry` instances and pass them explicitly.
"""

from __future__ import annotations

from connectors.base import Connector


class ConnectorRegistry:
    """Ordered collection of connectors keyed by ``connector.id``."""

    def __init__(self) -> None:
        self._connectors: dict[str, Connector] = {}

    def register(self, connector: Connector) -> None:
        """Register a connector. Re-registering the same ID overwrites it."""
        self._connectors[connector.id] = connector

    def all(self) -> list[Connector]:
        """Return all registered connectors in registration order."""
        return list(self._connectors.values())

    def get(self, connector_id: str) -> Connector | None:
        """Return the connector with the given ID, or ``None`` if absent."""
        return self._connectors.get(connector_id)


registry = ConnectorRegistry()
