"""Compatibility helpers for Home Assistant registry API transitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import inspect
from typing import Any


def iter_device_entries(device_registry: Any) -> Iterable[Any]:
    """Iterate device entries on supported Home Assistant registry versions.

    Home Assistant 2024.8 exposes ``devices`` as a mapping, while newer
    releases expose an iterable view and deprecate mapping methods on it.
    """
    devices = getattr(device_registry, "devices", ())
    if isinstance(devices, Mapping):
        return devices.values()
    return devices


def device_parent_info(
    hass: Any | None,
    parent_id: str,
    parent_identifier: tuple[str, str],
) -> dict[str, Any]:
    """Return the supported Home Assistant child-device link field.

    ``via_device`` is accepted by the minimum supported HA release, while
    newer releases expose the resolved ``via_device_id`` field.  Inspect the
    live registry contract so the metadata passed to entity registration never
    contains an argument that the installed HA version rejects.
    """
    if hass is not None:
        try:
            from homeassistant.helpers import device_registry as dr

            registry = dr.async_get(hass)
            parameters = inspect.signature(
                registry.async_get_or_create
            ).parameters
        except (ImportError, AttributeError, OSError, TypeError, ValueError):
            parameters = {}
        if "via_device_id" in parameters:
            return {"via_device_id": parent_id}

    return {"via_device": parent_identifier}
