"""PowerSync's authenticated transport for Amber's private battery API.

Public tariff data deliberately continues to use the public Amber API client.
Mutations are never retried here: a lost response does not prove a lost write.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timezone
from typing import Any

from aiohttp import ClientError, ClientTimeout

ENDPOINT = "https://backend.amber.com.au/graphql"
POOL_ID = "ap-southeast-2_vPQVymJLn"
CLIENT_ID = "11naqf0mbruts1osrjsnl2ee1"


class AmberError(Exception):
    """A sanitized transport or protocol failure."""


class AmberAuthError(AmberError):
    """The account needs reauthentication."""


def record(value) -> dict:
    """Reject schema drift without including private response bodies in errors."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise AmberError("Amber returned an unsupported battery response")
    return value


class AmberClient:
    def __init__(self, session, executor, email: str, password: str) -> None:
        self.session = session
        self.executor = executor
        self.email = email
        self._password = password
        self._identity = None
        self._auth_lock = asyncio.Lock()

    def _login(self) -> None:
        from pycognito import Cognito

        identity = Cognito(POOL_ID, CLIENT_ID, username=self.email)
        identity.authenticate(password=self._password)
        if not identity.id_token:
            raise AmberAuthError("Amber authentication requires an unsupported challenge")
        self._identity = identity

    async def _token(self) -> str:
        async with self._auth_lock:
            try:
                if self._identity is None:
                    await self.executor(self._login)
                token = self._identity.id_token
                payload = token.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                if float(claims["exp"]) <= datetime.now(timezone.utc).timestamp() + 60:
                    await self.executor(self._identity.renew_access_token)
                return self._identity.id_token
            except Exception:
                # Never expose botocore messages, GraphQL bodies or credentials.
                raise AmberAuthError("Amber sign-in expired or was rejected") from None

    async def request(self, document: str, variables: dict | None = None, *, mutation=False, before_write=None) -> dict:
        token = await self._token()
        for attempt in range(2 if not mutation else 1):
            try:
                # Authentication may yield long enough for ownership/settings to
                # change. Recheck immediately before starting a physical write.
                if mutation and before_write:
                    before_write()
                async with self.session.post(
                    ENDPOINT,
                    json={"query": document, "variables": variables or {}},
                    headers={"Authorization": token, "User-Agent": "PowerSync-HomeAssistant"},
                    timeout=ClientTimeout(total=15),
                ) as response:
                    if response.status in (401, 403):
                        raise AmberAuthError("Amber authentication was rejected")
                    if response.status == 429 or response.status >= 500:
                        if not mutation and attempt == 0:
                            await asyncio.sleep(2)
                            continue
                        raise AmberError("Amber is temporarily unavailable or rate limited")
                    if response.status != 200:
                        raise AmberError("Amber request was rejected")
                    body = await response.json()
                if not isinstance(body, dict) or body.get("errors") or not isinstance(body.get("data"), dict):
                    raise AmberError("Amber returned an incomplete or unsupported response")
                return body["data"]
            except (ClientError, TimeoutError, ValueError):
                if not mutation and attempt == 0:
                    await asyncio.sleep(2)
                    continue
                raise AmberError("Amber request failed; command outcome may be unknown") from None
        raise AmberError("Amber request failed")

    async def discover(self) -> tuple[str, str]:
        data = await self.request("query PowerSyncBattery { smartshift { batterySetting { siteId selectedConfigId } } }")
        setting = record(record(data.get("smartshift")).get("batterySetting"))
        site, config = setting.get("siteId"), setting.get("selectedConfigId")
        if not isinstance(site, str) or not site or not isinstance(config, str) or not config:
            raise AmberError("No Smart Shift battery is available for this account")
        return site, config

    async def stats(self, site: str) -> dict[str, Any]:
        data = await self.request("""query PowerSyncBatteryState($site: String) {
          smartshift {
            live(siteId: $site) { stateOfChargePercentage batteryPowerW powerState powerStateDescription }
            batteryOverridesInfo(siteId: $site) {
              effectiveOverride { overrideId value validFrom validTo state estimatedEndDate }
            }
            plan(siteId: $site, env: "prod") { batteryMaxEnergyWh }
          }
          smartshiftBatteryStrategyConfig(siteId: $site) { configId status }
        }""", {"site": site})
        shift = record(data.get("smartshift"))
        override = record(record(shift.get("batteryOverridesInfo")).get("effectiveOverride"))
        return {
            "live": record(shift.get("live")),
            "override": override or None,
            "capacity_wh": record(shift.get("plan")).get("batteryMaxEnergyWh"),
            "strategy": record(data.get("smartshiftBatteryStrategyConfig")),
        }

    async def earnings(self, site: str) -> dict:
        data = await self.request("""query PowerSyncInterval($site: String) {
          smartshift { live(siteId: $site) { liveMetrics {
            ... on SmartShiftMetricsWithInterval { importCostsCents exportEarningsCents totalEarningsCents }
          } } }
        }""", {"site": site})
        return record(record(record(data.get("smartshift")).get("live")).get("liveMetrics"))

    async def add(self, site, config, mode, start, end, *, before_write=None) -> dict:
        data = await self.request("""mutation PowerSyncOverride($input: AddBatteryOverrideInput!) {
          smartshift { addBatteryOverride(input: $input) { overrideId value validFrom validTo } }
        }""", {"input": {"siteId": site, "configId": config, "overrideValue": mode,
                            "validFrom": start, "validTo": end}}, mutation=True, before_write=before_write)
        result = record(record(data.get("smartshift")).get("addBatteryOverride"))
        if not result.get("overrideId"):
            raise AmberError("Amber did not acknowledge the battery override")
        return result

    async def cancel(self, site, config, override_id) -> None:
        data = await self.request("""mutation PowerSyncCancel($input: CancelBatteryOverrideInput!) {
          smartshift { cancelBatteryOverride(input: $input) { overrideId } }
        }""", {"input": {"siteId": site, "configId": config, "overrideId": override_id}}, mutation=True)
        result = record(record(data.get("smartshift")).get("cancelBatteryOverride"))
        if result.get("overrideId") != override_id:
            raise AmberError("Amber did not acknowledge override cancellation")

    async def enable(self, config, enabled: bool, *, before_write=None) -> None:
        data = await self.request("""mutation PowerSyncSmartShift($input: UpdateSmartShiftDeviceSettingsInput!) {
          updateSmartShiftDeviceSettings(input: $input) { settings { optimisationEnabled } }
        }""", {"input": {"deviceId": "CONFIG#" + config, "optimisationEnabled": enabled}}, mutation=True, before_write=before_write)
        result = record(record(data.get("updateSmartShiftDeviceSettings")).get("settings"))
        if result.get("optimisationEnabled") is not enabled:
            raise AmberError("Amber did not acknowledge the Smart Shift setting")
