"""TOU callers share site backpressure without queuing stale force tariffs."""

from __future__ import annotations

import ast
import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def upload_harness(monkeypatch):
    source = (ROOT / "custom_components/power_sync/__init__.py").read_text()
    tree = ast.parse(source)
    names = {"send_tariff_to_tesla", "_send_tariff_to_tesla"}
    nodes = [node for node in tree.body if getattr(node, "name", None) in names]
    clock = SimpleNamespace(now=0.0, sleeping=None, resume=None, confirmed=True)

    async def sleep(delay):
        if clock.sleeping is not None:
            clock.sleeping.set()
            await clock.resume.wait()
        clock.now += delay
        await asyncio.sleep(0)

    class Response:
        def __init__(self, status):
            self.status = status
            self.headers = {"Retry-After": "282"} if status == 429 else {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def text(self):
            return "rate_limited"

        async def json(self):
            return {"response": {}}

    class Session:
        def __init__(self):
            self.responses = [429, 200, 200, 200]
            self.posts = []

        def post(self, url, **kwargs):
            self.posts.append((clock.now, url, kwargs["json"]))
            return Response(self.responses.pop(0))

    session = Session()
    coordinator = SimpleNamespace(
        _parse_retry_after=lambda response: float(response.headers["Retry-After"])
    )
    monkeypatch.setitem(sys.modules, "power_sync.coordinator", coordinator)

    async def confirm(*_args, **_kwargs):
        return clock.confirmed

    namespace = {
        "__name__": "power_sync.tariff_upload_test",
        "__package__": "power_sync",
        "asyncio": SimpleNamespace(sleep=sleep, TimeoutError=asyncio.TimeoutError),
        "time": SimpleNamespace(monotonic=lambda: clock.now),
        "aiohttp": aiohttp,
        "DOMAIN": "power_sync",
        "TESLA_PROVIDER_TESLEMETRY": "teslemetry",
        "async_get_clientsession": lambda _hass: session,
        "get_tesla_api_base_url": lambda provider, region: region or provider,
        "_confirm_tesla_tariff_uploaded": confirm,
        "_LOGGER": logging.getLogger(__name__),
    }
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "<tariff-upload>", "exec"), namespace)
    return namespace["send_tariff_to_tesla"], SimpleNamespace(data={}), session, clock


def test_final_429_defers_fresh_call_until_retry_after_even_with_rotated_token(upload_harness):
    upload, hass, session, clock = upload_harness

    async def run():
        assert await upload(hass, "site-a", {"name": "normal"}, "token", max_retries=1) is False
        accepted = {}
        assert await upload(hass, "site-a", {"name": "force"}, "new-token", accepted_status=accepted) is False
        assert accepted == {}
        assert len(session.posts) == 1
        clock.now = 281.9
        assert await upload(hass, "site-a", {"name": "restore"}, "token") is False
        assert len(session.posts) == 1
        clock.now = 282.0
        assert await upload(hass, "site-a", {"name": "fresh"}, "token") is True
        assert [post[0] for post in session.posts] == [0.0, 282.0]

    asyncio.run(run())


def test_overlapping_force_upload_is_deferred_during_normal_upload_retry(upload_harness):
    upload, hass, session, clock = upload_harness

    async def run():
        clock.sleeping, clock.resume = asyncio.Event(), asyncio.Event()
        normal = asyncio.create_task(upload(hass, "site-a", {"name": "normal"}, "token", max_retries=2))
        await clock.sleeping.wait()
        try:
            assert await upload(hass, "site-a", {"name": "force"}, "token") is False
            assert len(session.posts) == 1
        finally:
            clock.resume.set()
            assert await normal is True
        assert [post[0] for post in session.posts] == [0.0, 282.0]
        # Deferred payloads are never queued and replayed after the caller ends.
        assert all(post[2]["tou_settings"]["tariff_content_v2"]["name"] == "normal" for post in session.posts)

    asyncio.run(run())


def test_other_sites_and_api_providers_are_not_blocked(upload_harness):
    upload, hass, session, _clock = upload_harness

    async def run():
        assert await upload(hass, "site-a", {}, "token", max_retries=1) is False
        assert await upload(hass, "site-b", {}, "token") is True
        assert await upload(hass, "site-a", {}, "token", api_provider="fleet_api") is True
        assert len(session.posts) == 3

    asyncio.run(run())


def test_cancelled_retry_releases_busy_slot_but_preserves_cooldown(upload_harness):
    upload, hass, session, clock = upload_harness

    async def run():
        clock.sleeping, clock.resume = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(upload(hass, "site-a", {}, "token"))
        await clock.sleeping.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert await upload(hass, "site-a", {}, "token", max_retries=1) is False
        assert len(session.posts) == 1
        clock.now = 282.0
        assert await upload(hass, "site-a", {}, "token") is True

    asyncio.run(run())


def test_accepted_unconfirmed_upload_preserves_status_and_releases_slot(upload_harness):
    upload, hass, session, clock = upload_harness
    session.responses = [200, 200]

    async def run():
        clock.confirmed = False
        accepted, readback = {}, {}
        assert await upload(hass, "site-a", {}, "token", accepted_status=accepted, readback_status=readback) is False
        assert accepted == {"accepted": True}
        assert readback == {"status": "unconfirmed"}
        clock.confirmed = True
        assert await upload(hass, "site-a", {}, "token") is True
        assert len(session.posts) == 2

    asyncio.run(run())
