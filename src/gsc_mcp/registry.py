"""Client registry and property allowlist (spec section 6).

Prevents analyzing one client's property under another client's name. The
registry is optional — when absent, all Google-returned properties are allowed
but outputs still carry client_id/client_name as None.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import config
from .errors import ErrorCode, GscError

logger = logging.getLogger("gsc_mcp.registry")


@dataclass
class PropertyEntry:
    site_url: str
    label: str | None = None


@dataclass
class ClientEntry:
    id: str
    name: str
    active: bool = True
    properties: list[PropertyEntry] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)


@dataclass
class Registry:
    clients: list[ClientEntry] = field(default_factory=list)
    # site_url -> ClientEntry lookup (each property belongs to exactly one client)
    _by_property: dict[str, ClientEntry] = field(default_factory=dict, repr=False)

    def lookup(self, site_url: str) -> ClientEntry | None:
        return self._by_property.get(site_url)

    def allowed_properties(self) -> set[str]:
        return set(self._by_property.keys())


def _load_registry_from_path(path: str) -> Registry:
    """Parse clients.yaml and validate the no-duplicate-property rule (spec 6)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError as exc:
        raise GscError(
            ErrorCode.INTERNAL_ERROR,
            f"GSC_CLIENTS_CONFIG points to {path!r} but the file does not exist.",
            retryable=False,
        ) from exc
    except yaml.YAMLError as exc:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"Failed to parse clients config at {path!r}: {exc}",
            retryable=False,
        ) from exc

    registry = Registry()
    seen_properties: dict[str, str] = {}  # site_url -> client_id (for dup detection)

    for entry in raw.get("clients", []) or []:
        if not isinstance(entry, dict):
            continue
        client_id = str(entry.get("id") or "").strip()
        client_name = str(entry.get("name") or client_id)
        active = bool(entry.get("active", True))
        props_raw = entry.get("properties", []) or []
        defaults = entry.get("defaults", {}) or {}

        if not client_id:
            raise GscError(
                ErrorCode.INVALID_ARGUMENT,
                f"Client entry missing 'id': {entry!r}",
                retryable=False,
            )

        client = ClientEntry(id=client_id, name=client_name, active=active, defaults=defaults)
        for p in props_raw:
            if not isinstance(p, dict):
                continue
            site_url = str(p.get("site_url") or "").strip()
            if not site_url:
                continue
            if site_url in seen_properties:
                # Spec 6: a property belonging to multiple clients must fail
                # startup — otherwise analysis could be mis-attributed.
                raise GscError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"Property {site_url!r} is registered to multiple clients "
                    f"({seen_properties[site_url]!r} and {client_id!r}). "
                    "Each property must belong to exactly one client.",
                    retryable=False,
                )
            seen_properties[site_url] = client_id
            client.properties.append(PropertyEntry(site_url=site_url, label=p.get("label")))
            registry._by_property[site_url] = client
        registry.clients.append(client)

    logger.info(
        "registry loaded: %d client(s), %d property(ies)",
        len(registry.clients), len(registry._by_property),
    )
    return registry


_REGISTRY: Registry | None = None


def get_registry() -> Registry | None:
    """Return the loaded registry, or None if no clients config is set.

    Raises on startup if the config is malformed or has duplicate properties.
    """
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    if not config.CLIENTS_CONFIG:
        return None
    _REGISTRY = _load_registry_from_path(config.CLIENTS_CONFIG)
    return _REGISTRY


def assert_property_allowed(site_url: str) -> ClientEntry | None:
    """Enforce allowlist (spec 6). Returns the owning ClientEntry or None.

    If a registry is configured and the property is not in it, raises
    PROPERTY_NOT_ALLOWED. If no registry is configured, returns None (open mode).
    """
    registry = get_registry()
    if registry is None:
        return None
    client = registry.lookup(site_url)
    if client is None:
        raise GscError(
            ErrorCode.PROPERTY_NOT_ALLOWED,
            f"The requested property {site_url!r} is not in the configured "
            "client allowlist. Verify the site_url exactly matches an entry "
            "in clients.yaml.",
            retryable=False,
        )
    if not client.active:
        raise GscError(
            ErrorCode.PROPERTY_NOT_ALLOWED,
            f"Client {client.id!r} (owner of {site_url!r}) is marked inactive.",
            retryable=False,
        )
    return client


def reset_registry_for_tests() -> None:
    """Test hook: clear the cached registry so a new config can be loaded."""
    global _REGISTRY
    _REGISTRY = None


__all__ = [
    "Registry", "ClientEntry", "PropertyEntry", "get_registry",
    "assert_property_allowed", "reset_registry_for_tests",
]
