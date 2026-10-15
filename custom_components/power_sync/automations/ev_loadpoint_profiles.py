"""Resolve logical EV profiles onto one physical non-Tesla loadpoint.

The mobile configuration has historically used the vehicle id as both the
profile id and the charger id.  That is safe only while a charger has one
profile.  This module deliberately keeps that legacy shape intact, while
giving new shared-charger profiles a stable physical key and an explicit
selected profile.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


NON_TESLA_CHARGER_TYPES = frozenset({"generic", "ocpp", "sigenergy", "zaptec"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def profile_id(profile: Mapping[str, Any]) -> str:
    """Return the persisted logical vehicle/profile id."""
    return _text(profile.get("vehicle_id"))


def charger_type(profile: Mapping[str, Any]) -> str:
    return _text(profile.get("charger_type")).lower()


def physical_loadpoint_id(profile: Mapping[str, Any]) -> str:
    """Return a conservative stable key for a physical charger.

    ``loadpoint_id`` is intentionally an escape hatch for integrations that
    expose a canonical charger id.  Otherwise only backend-specific concrete
    identifiers are used; we never group chargers merely because their type
    happens to match.
    """
    explicit = _text(profile.get("loadpoint_id"))
    if explicit:
        return explicit

    kind = charger_type(profile)
    if kind == "generic":
        for key in (
            "charger_switch_entity",
            "generic_charger_switch_entity",
            "charger_amps_entity",
            "generic_charger_amps_entity",
            "charger_status_entity",
            "generic_charger_status_entity",
        ):
            value = _text(profile.get(key))
            if value:
                return f"generic:{value.lower()}"
        return "generic_ev"
    if kind == "ocpp":
        charger = _text(profile.get("ocpp_charger_id"))
        if charger:
            return charger if charger.startswith("ocpp_") else f"ocpp_{charger}"
        return "ocpp_charger"
    if kind == "sigenergy":
        host = _text(profile.get("sigenergy_charger_host")).lower()
        port = _text(profile.get("sigenergy_charger_port"))
        slave = _text(profile.get("sigenergy_charger_slave_id"))
        if host or port or slave:
            return f"sigenergy:{host}:{port}:{slave}"
        return "sigenergy_charger"
    if kind == "zaptec":
        for key in ("zaptec_charger_id", "zaptec_device_id", "charger_switch_entity"):
            value = _text(profile.get(key))
            if value:
                return f"zaptec:{value.lower()}"
        return "zaptec_standalone"
    return profile_id(profile)


def profiles_for_loadpoint(
    profiles: list[Mapping[str, Any]], loadpoint_id: Any
) -> list[Mapping[str, Any]]:
    """Return profiles mapped to a physical loadpoint without broad matching."""
    wanted = _text(loadpoint_id)
    return [profile for profile in profiles if physical_loadpoint_id(profile) == wanted]


def selected_vehicle_id(
    stored_data: Mapping[str, Any] | None,
    loadpoint_id: Any,
) -> str | None:
    """Read one explicitly persisted selection, rejecting malformed values."""
    selections = (stored_data or {}).get("connected_ev_by_loadpoint", {})
    if not isinstance(selections, Mapping):
        return None
    value = _text(selections.get(_text(loadpoint_id)))
    return value or None


def effective_profile(
    profiles: list[Mapping[str, Any]],
    stored_data: Mapping[str, Any] | None,
    loadpoint_id: Any,
) -> Mapping[str, Any] | None:
    """Return the selected profile, or the sole legacy profile.

    A shared loadpoint without a valid explicit selection is intentionally
    inert.  A single old profile remains exactly as it behaved before this
    feature: it needs neither a new field nor selector state.
    """
    candidates = profiles_for_loadpoint(profiles, loadpoint_id)
    if len(candidates) == 1:
        return candidates[0]
    selected = selected_vehicle_id(stored_data, loadpoint_id)
    if not selected:
        return None
    matches = [profile for profile in candidates if profile_id(profile) == selected]
    return matches[0] if len(matches) == 1 else None


def profile_loadpoint_id(
    profiles: list[Mapping[str, Any]], profile_or_id: Any
) -> str | None:
    """Resolve a logical profile id or an already-physical key to its key."""
    value = _text(profile_or_id)
    by_profile = [profile for profile in profiles if profile_id(profile) == value]
    if len(by_profile) == 1:
        return physical_loadpoint_id(by_profile[0])
    by_loadpoint = profiles_for_loadpoint(profiles, value)
    return value if by_loadpoint else None


def effective_profile_for_id(
    profiles: list[Mapping[str, Any]],
    stored_data: Mapping[str, Any] | None,
    profile_or_loadpoint_id: Any,
) -> Mapping[str, Any] | None:
    """Resolve the effective profile for either public identity form."""
    loadpoint_id = profile_loadpoint_id(profiles, profile_or_loadpoint_id)
    if loadpoint_id is None:
        return None
    return effective_profile(profiles, stored_data, loadpoint_id)


def profile_is_effective(
    profiles: list[Mapping[str, Any]],
    stored_data: Mapping[str, Any] | None,
    profile_or_loadpoint_id: Any,
) -> bool:
    """Whether an identity is currently permitted to automate its loadpoint."""
    loadpoint = profile_loadpoint_id(profiles, profile_or_loadpoint_id)
    if loadpoint is None:
        return True
    candidates = profiles_for_loadpoint(profiles, loadpoint)
    if len(candidates) == 1:
        return True
    profile = effective_profile(profiles, stored_data, loadpoint)
    if profile is None:
        return False
    value = _text(profile_or_loadpoint_id)
    return value == loadpoint or profile_id(profile) == value


def set_connected_ev(
    stored_data: dict[str, Any],
    loadpoint_id: Any,
    vehicle_id: Any = None,
) -> str | None:
    """Validate and persist an explicit selection, returning the selected id.

    This pure storage operation is deliberately command-free so it can also be
    used safely by the Home Assistant service and configuration API.
    """
    configs = stored_data.get("vehicle_charging_configs", [])
    profiles = [item for item in configs if isinstance(item, Mapping)]
    loadpoint = _text(loadpoint_id)
    if not loadpoint or not profiles_for_loadpoint(profiles, loadpoint):
        raise ValueError("loadpoint_id does not identify a configured charger")
    selected = _text(vehicle_id)
    selections = stored_data.get("connected_ev_by_loadpoint")
    if not isinstance(selections, dict):
        selections = {}
        stored_data["connected_ev_by_loadpoint"] = selections
    if not selected:
        selections.pop(loadpoint, None)
        if not selections:
            stored_data.pop("connected_ev_by_loadpoint", None)
        return None
    candidates = profiles_for_loadpoint(profiles, loadpoint)
    if sum(profile_id(profile) == selected for profile in candidates) != 1:
        raise ValueError("vehicle_id is not bound to loadpoint_id")
    selections[loadpoint] = selected
    return selected


def prune_connected_ev_selections(stored_data: dict[str, Any]) -> bool:
    """Remove selections made stale by profile deletion or mapping changes."""
    selections = stored_data.get("connected_ev_by_loadpoint")
    if not isinstance(selections, dict):
        return False
    configs = stored_data.get("vehicle_charging_configs", [])
    profiles = [item for item in configs if isinstance(item, Mapping)]
    changed = False
    for loadpoint, vehicle_id in list(selections.items()):
        profile = effective_profile(profiles, {"connected_ev_by_loadpoint": selections}, loadpoint)
        if profile is None or profile_id(profile) != _text(vehicle_id):
            selections.pop(loadpoint, None)
            changed = True
    if not selections:
        stored_data.pop("connected_ev_by_loadpoint", None)
    return changed


def validate_profile_loadpoint_mappings(profiles: list[Mapping[str, Any]]) -> None:
    """Reject an explicit loadpoint key that merges incompatible backends."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for profile in profiles:
        grouped.setdefault(physical_loadpoint_id(profile), []).append(profile)
    for loadpoint, members in grouped.items():
        if len(members) < 2:
            continue
        kinds = {charger_type(member) for member in members}
        if len(kinds) != 1 or not kinds.intersection(NON_TESLA_CHARGER_TYPES):
            raise ValueError(
                f"loadpoint_id {loadpoint!r} cannot merge incompatible charger profiles"
            )


async def async_set_connected_ev(
    hass: Any,
    config_entry: Any,
    loadpoint_id: Any,
    vehicle_id: Any = None,
) -> str | None:
    """Persist a selection after rejecting an active controller hand-off.

    No action module is imported and no charger call is made here.  The next
    normal evaluation observes the selection; an in-flight owned session must
    be stopped/released first so one car's limits cannot be applied to another.
    """
    from .ev_ownership import get_ev_ownership, owner_family

    entry_data = getattr(hass, "data", {}).get("power_sync", {}).get(
        config_entry.entry_id, {}
    )
    store = entry_data.get("automation_store") if isinstance(entry_data, Mapping) else None
    data = getattr(store, "_data", None)
    if not isinstance(data, dict):
        raise ValueError("automation storage is unavailable")
    profiles = [
        item
        for item in data.get("vehicle_charging_configs", [])
        if isinstance(item, Mapping)
    ]
    loadpoint = _text(loadpoint_id)
    # Permit callers to provide a logical id only when it resolves uniquely;
    # service/API clients should otherwise retain the public physical key.
    loadpoint = profile_loadpoint_id(profiles, loadpoint) or loadpoint
    _lease_id, lease = get_ev_ownership(hass, config_entry, loadpoint)
    if isinstance(lease, Mapping) and (
        lease.get("owner") == "powersync"
        or owner_family(lease.get("owner_mode")) in {"manual", "boost"}
    ):
        raise ValueError("cannot change connected EV while the loadpoint is owned")
    selected = set_connected_ev(data, loadpoint, vehicle_id)
    save = getattr(store, "async_save", None)
    if save is not None:
        await save()
    return selected
