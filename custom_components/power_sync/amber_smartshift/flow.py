"""Native HA setup and options forms for Amber battery control."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from homeassistant.exceptions import HomeAssistantError

from . import ALLOW_ENABLE, BATTERY_SYSTEM, CONFIG, EMAIL, MANAGED, PASSWORD, SITE
from .client import AmberAuthError, AmberClient, AmberError

METER_KEYS = ("custom_grid_power_entity", "custom_solar_power_entity", "custom_load_power_entity")


def schema(current=None):
    current = current or {}
    fields = {
        vol.Required(EMAIL, default=current.get(EMAIL, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)),
        vol.Optional(PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        vol.Required(MANAGED, default=current.get(MANAGED, False)): selector.BooleanSelector(),
        vol.Required(ALLOW_ENABLE, default=current.get(ALLOW_ENABLE, False)): selector.BooleanSelector(),
    }
    for key in METER_KEYS:
        fields[vol.Optional(key, description={"suggested_value": current[key]} if current.get(key) else {})] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor"))
    return vol.Schema(fields)


async def validate(hass, data, pricing_site, provider):
    if provider != "amber" or not pricing_site:
        raise AmberError("Configure Amber pricing before connecting an Amber battery")
    if not data.get(EMAIL) or not data.get(PASSWORD):
        raise AmberAuthError("Enter Amber account credentials")
    client = AmberClient(async_get_clientsession(hass), hass.async_add_executor_job, data[EMAIL], data[PASSWORD])
    site, config = await client.discover()
    if site != pricing_site:
        raise AmberError("Amber battery and pricing sites do not match")
    stats = await client.stats(site)
    if stats.get("strategy", {}).get("configId") != config:
        raise AmberError("Amber battery configuration is unavailable")
    if data.get(MANAGED) and not all(data.get(key) for key in METER_KEYS):
        raise AmberError("Select grid, solar and home-load meters for PowerSync-managed operation")
    # Include blanks so removed optional meter selections do not survive a save.
    return {**data, **{key: data.get(key, "") for key in METER_KEYS}, SITE: site, CONFIG: config,
            "battery_system": BATTERY_SYSTEM, "battery_connection_profile": "amber_smartshift_native"}


class AmberSetupMixin:
    async def async_step_amber_smartshift(self, user_input=None):
        errors = {}
        current = getattr(self, "_amber_smartshift_data", {})
        if user_input is not None:
            try:
                pricing_site = self._site_data.get("amber_site_id") or self._amber_data.get("amber_site_id")
                current = await validate(self.hass, user_input, pricing_site, self._selected_electricity_provider)
                self._amber_smartshift_data = current
                return self._create_final_entry()
            except AmberAuthError:
                errors["base"] = "amber_smartshift_auth"
            except AmberError:
                errors["base"] = "amber_smartshift_connection"
        return self.async_show_form(step_id="amber_smartshift", data_schema=schema(current), errors=errors)

    async def async_step_amber_smartshift_reauth(self, user_input=None):
        entry = self._reauth_entry
        current = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            try:
                updated = await validate(self.hass, {**current, **user_input}, current.get("amber_site_id"), current.get("electricity_provider", "amber"))
                if updated[SITE] != current[SITE] or updated[CONFIG] != current[CONFIG]:
                    raise AmberError("Use connection settings to change battery identity")
                data = {**entry.data, **updated}
                options = {k: v for k, v in entry.options.items() if k not in (EMAIL, PASSWORD)}
                self.hass.config_entries.async_update_entry(entry, data=data, options=options)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            except AmberAuthError:
                errors["base"] = "amber_smartshift_auth"
            except AmberError:
                errors["base"] = "amber_smartshift_connection"
        return self.async_show_form(step_id="amber_smartshift_reauth", data_schema=schema(current), errors=errors)


class AmberOptionsMixin:
    async def async_step_amber_smartshift(self, user_input=None):
        entry = self.config_entry
        current = {**entry.data, **entry.options}
        errors = {}
        if user_input is not None:
            try:
                proposed = {**user_input, PASSWORD: user_input.get(PASSWORD) or current.get(PASSWORD)}
                updated = await validate(self.hass, proposed, current.get("amber_site_id"), current.get("electricity_provider", "amber"))
                runtime = self.hass.data.get("power_sync", {}).get(entry.entry_id, {}).get("amber_smartshift_coordinator")
                if runtime:
                    # Do not replace identity/credentials while an owned command
                    # may still need the old connection to clean it up.
                    same_identity = updated[SITE] == runtime.site and updated[CONFIG] == runtime.config
                    replacing_credentials = updated[PASSWORD] != current.get(PASSWORD) or updated[EMAIL] != current.get(EMAIL)
                    if not (same_identity and replacing_credentials):
                        await runtime.restore_normal()
                    # New credentials for the same battery can reconcile its
                    # durable journal after reload even if old auth is revoked.
                    runtime.stopping = True
                self._save_battery_system_selection(BATTERY_SYSTEM)
                options = {k: v for k, v in updated.items() if k not in (EMAIL, PASSWORD)}
                return self._save_connection_and_reload(updated, options)
            except AmberAuthError:
                errors["base"] = "amber_smartshift_auth"
            except (AmberError, HomeAssistantError):
                errors["base"] = "amber_smartshift_connection"
        return self.async_show_form(step_id="amber_smartshift", data_schema=schema(current), errors=errors)
