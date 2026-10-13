"""Read-only rollout status; no activation or hardware write is exposed here."""
from __future__ import annotations

import time
from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .admission import OptimizerAdmission

DATA_KEY = "power_sync_licensing"


def licensing_status(hass) -> dict:
    """Keep trial/access status visible even without an optimizer coordinator."""
    admission = hass.data.get(DATA_KEY)
    if admission is None:
        admission = OptimizerAdmission(enforced=False)
        hass.data[DATA_KEY] = admission
    return admission.api_status(int(time.time()))


class LicensingStatusView(HomeAssistantView):
    url = "/api/power_sync/licensing"
    name = "api:power_sync:licensing"
    requires_auth = True

    def __init__(self, hass):
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        return web.json_response(licensing_status(self._hass))
