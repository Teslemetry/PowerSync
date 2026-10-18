"""PV production controls using existing, model-scoped inverter transports.

Export-only adapters intentionally have no native implementation. An explicitly
selected PV-production HA entity provides their control surface instead.
"""
from __future__ import annotations

from copy import deepcopy
from .solar_production import finite_number

NATIVE_BRANDS = frozenset({"enphase", "fronius", "sungrow", "solaredge", "zeversolar", "sigenergy"})


class NativeProductionTarget:
    def __init__(self, controller, identity):
        self.controller = controller
        self.identity = identity
        self.brand = identity["brand"]
        self.refresh = self.brand == "enphase"

    @property
    def effective(self):
        return self.brand != "sigenergy" or getattr(self, "_pv_limit_effective", False)

    async def read(self):
        c = self.controller
        if not await c.connect():
            return None
        if self.brand == "sigenergy":
            async with c._modbus_transaction():
                value = await c._get_current_pv_limit()
                enabled = await c._read_holding_registers(c.REG_REMOTE_EMS_ENABLE, 1)
                mode = await c._read_holding_registers(c.REG_REMOTE_EMS_CONTROL_MODE, 1)
                self._pv_limit_effective = bool(enabled == [1] and mode and mode[0] in (3, 4, 5, 6))
                return {"pv_limit": value} if value is not None and 0 <= value < 0xFFFFFFFF else None
        if self.brand == "enphase":
            raw = await c._get_dpel_settings()
            data = raw.get("dynamic_pel_settings", raw) if isinstance(raw, dict) else None
            if not isinstance(data, dict) or not isinstance(data.get("enable"), bool) or not isinstance(data.get("export_limit"), bool):
                return None
            # Gateway (static watts) and digital-input (relay table) modes
            # expose different controls. Require the active mode's baseline,
            # retaining any inactive controls actually returned for restoration.
            if not isinstance(data.get("enable_dynamic_limiting"), bool) or finite_number(data.get("slew_rate")) is None:
                return None
            dynamic = data["enable_dynamic_limiting"]
            if (not dynamic or "limit_value_W" in data) and finite_number(data.get("limit_value_W")) is None:
                return None
            if (dynamic or "relay_config" in data) and not isinstance(data.get("relay_config"), (dict, bool)):
                return None
            keys = ("enable", "export_limit", "limit_value_W", "enable_dynamic_limiting", "relay_config", "slew_rate")
            return deepcopy({key: data[key] for key in keys if key in data})
        if self.brand == "fronius":
            state = {}
            for key, address in (("enabled", c.REG_WMAXLIM_ENA), ("limit", c.REG_WMAXLIMPCT), ("revert", c.REG_WMAXLIMPCT_RVRT)):
                values = await c._read_register(address, 1)
                if not values or not 0 <= values[0] <= (10000 if key == "limit" else 65534):
                    return None
                state[key] = values[0]
            return state if state["enabled"] in (0, 1) else None
        if self.brand == "sungrow":
            # SG-only stop register; never stop an SH hybrid/battery inverter.
            if not getattr(c, "production_stop_model_supported", False):
                return None
            values = await c._read_register(c.REGISTER_RUN_MODE, 1)
            if values and values[0] in (c.RUN_MODE_ENABLED, c.RUN_MODE_SHUTDOWN):
                return {"run_mode": values[0]}
            return None
        if self.brand == "solaredge":
            value = await c._get_active_power_limit()
            return {"percent": value} if value is not None and 0 <= value <= 100 else None
        if self.brand == "zeversolar":
            # connect() refreshes /adv.cgi; read the full setting explicitly so
            # a constructor's optimistic 100% cache can never become a snapshot.
            async with c._session.get(f"{c.base_url}/adv.cgi") as response:
                if response.status != 200:
                    return None
                lines = (await response.text()).strip().splitlines()
            if len(lines) < 16 or lines[8].strip() not in ("0", "1"):
                return None
            fields = {"enlim": "on" if lines[8].strip() == "1" else "off"}
            for index, key in ((9, "drm_sp"), (10, "ac_sys"), (11, "ac_value1"), (12, "ac_value2"), (13, "ac_value3"), (14, "ac_mode"), (15, "em_ml")):
                value = lines[index].strip()
                if finite_number(value) is None:
                    return None
                fields[key] = value
            return fields
        return None

    def stopped(self, original):
        state = deepcopy(original)
        if self.brand == "sigenergy":
            if not getattr(self, "_pv_limit_effective", False):
                return None
            state["pv_limit"] = 0
            return state
        if self.brand == "enphase":
            state.update(enable=True, export_limit=False)
            if "limit_value_W" in state:
                state["limit_value_W"] = 0.0
            if state["enable_dynamic_limiting"]:
                state["relay_config"] = self.controller._dpel_relay_config(0.0)
        elif self.brand == "fronius":
            # Preserve the existing adapter's indefinite-limit semantics.
            # A new reversion lease could restore 100% over a user's prior cap.
            state.update(enabled=1, limit=0, revert=0)
        elif self.brand == "sungrow":
            state["run_mode"] = self.controller.RUN_MODE_SHUTDOWN
        elif self.brand == "solaredge":
            state["percent"] = 0
        elif self.brand == "zeversolar":
            state.update(enlim="on", ac_mode="1", ac_value1="0")
        else:
            return None
        return state

    def matches(self, observed, expected):
        """Match old full-surface journals against mode-specific DPEL reads."""
        if self.brand != "enphase" or not isinstance(observed, dict) or not isinstance(expected, dict):
            return observed == expected
        mode = observed.get("enable_dynamic_limiting")
        if not isinstance(mode, bool) or expected.get("enable_dynamic_limiting") is not mode:
            return False
        expected = deepcopy(expected)
        inactive = "limit_value_W" if mode else "relay_config"
        if inactive not in observed:
            expected.pop(inactive, None)
        # Mode, active controls, common fields and any returned inactive field
        # still match exactly. Never infer an absent active setting or a mode.
        return observed == expected

    def owns_partial(self, observed, original, stopped):
        """Recognize interrupted multi-register updates, field by field."""
        return (
            self.brand == "fronius" and isinstance(observed, dict)
            and observed.keys() == original.keys() == stopped.keys()
            and all(observed[key] in (original[key], stopped[key]) for key in observed)
        )

    async def write(self, state):
        c = self.controller
        if not await c.connect() or not getattr(self, "allowed", lambda: True)():
            return False
        if self.brand == "sigenergy":
            async with c._modbus_transaction():
                if state["pv_limit"] == 0:
                    enabled = await c._read_holding_registers(c.REG_REMOTE_EMS_ENABLE, 1)
                    mode = await c._read_holding_registers(c.REG_REMOTE_EMS_CONTROL_MODE, 1)
                    if enabled != [1] or not mode or mode[0] not in (3, 4, 5, 6):
                        return False
                if not getattr(self, "allowed", lambda: True)():
                    return False
                return await c._write_holding_registers(
                    c.REG_PV_MAX_POWER_LIMIT, c._from_unsigned32(state["pv_limit"])
                )
        if self.brand == "enphase":
            raw = await c._get_dpel_settings()
            settings = raw.get("dynamic_pel_settings", raw) if isinstance(raw, dict) else None
            if not isinstance(settings, dict):
                return False
            settings = deepcopy(settings)
            settings.update(deepcopy(state))
            if not getattr(self, "allowed", lambda: True)():
                return False
            # Preserve the captured Gateway/relay mode. One production payload
            # only; no opposite export flag, zero-export or DER export fallback.
            ok, _ = await c._post(c.ENDPOINT_DPEL, {"dynamic_pel_settings": settings})
            return ok
        if self.brand == "fronius":
            # Do not transiently disable an existing limit before applying 0%.
            # Check every write; the durable journal survives partial failure.
            for address, value in ((c.REG_WMAXLIMPCT, state["limit"]), (c.REG_WMAXLIMPCT_RVRT, state["revert"]), (c.REG_WMAXLIM_ENA, state["enabled"])):
                if not getattr(self, "allowed", lambda: True)() or not await c._write_register(address, value):
                    return False
            return True
        if self.brand == "sungrow":
            return await c._write_register(c.REGISTER_RUN_MODE, state["run_mode"])
        if self.brand == "solaredge":
            return await c._set_active_power_limit(state["percent"])
        if self.brand == "zeversolar":
            async with c._session.post(f"{c.base_url}/pwrlim.cgi", data=state, headers={"Content-Type": "application/x-www-form-urlencoded"}) as response:
                return response.status == 200
        return False
