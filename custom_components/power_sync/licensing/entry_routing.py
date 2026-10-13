"""Exact config-entry routing for optimiser controls and their free restoration."""

def register_handlers(hass, entry_id, handlers):
    hass.data.setdefault("power_sync", {}).setdefault(entry_id, {})["licensing_control_handlers"] = dict(handlers)


def entry_service_data(entry_id, data, origin=None):
    result = dict(data)
    result.setdefault("entry_id", entry_id)
    if result.get("source") == "optimizer" and origin is not None:
        for name in ("_licensing_generation", "_licensing_entry_generation"):
            if name in origin.data:
                result.setdefault(name, origin.data[name])
    return result


def routed_handler(hass, entry_id, service, handler):
    async def routed(call):
        requested = call.data.get("entry_id")
        if requested is not None and not isinstance(requested, str):
            raise ValueError("invalid_control_entry")
        if requested and requested != entry_id:
            target = hass.data.get("power_sync", {}).get(requested, {}).get("licensing_control_handlers", {}).get(service)
            if target is None:
                raise ValueError("control_entry_not_available")
            return await target(call)
        return await handler(call)
    return routed
