"""TOU upload retries must never resend a stale tariff over a newer sync."""

from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = ROOT / "custom_components" / "power_sync" / "__init__.py"
FAKE_PACKAGE = "_tou_retry_test_pkg"

_EXTRACTED = (
    "_TOU_UPLOAD_GENERATIONS",
    "TOU_PERIODIC_SYNC_MAX_RETRY_AFTER_SECONDS",
    "_begin_tou_upload",
    "_tou_upload_superseded",
    "_tou_retry_after_too_long",
    "send_tariff_to_tesla",
)


def _extract_nodes(tree: ast.Module) -> list[ast.stmt]:
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        else:
            continue
        if name in _EXTRACTED:
            nodes.append(node)
    assert len(nodes) == len(_EXTRACTED)
    return nodes


class FakeResponse:
    def __init__(self, status, retry_after=None):
        self.status = status
        self.headers = {"Retry-After": str(retry_after)} if retry_after else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return {"response": {"code": 0}}

    async def text(self):
        return "rate limited" if self.status == 429 else "error"


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    def post(self, url, *, headers, json, timeout):
        self.posts.append(json["tou_settings"]["tariff_content_v2"])
        return self.responses.pop(0)


class FakeLogger:
    def __init__(self):
        self.messages = []

    def _record(self, msg, *args):
        self.messages.append(msg % args if args else msg)

    debug = info = warning = error = exception = _record


def _load(monkeypatch, session, sleep):
    tree = ast.parse(INIT_PATH.read_text())
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *_extract_nodes(tree),
        ],
        type_ignores=[],
    )
    coordinator = ModuleType(f"{FAKE_PACKAGE}.coordinator")
    coordinator._parse_retry_after = lambda response: (
        float(response.headers["Retry-After"])
        if "Retry-After" in response.headers
        else None
    )
    monkeypatch.setitem(sys.modules, FAKE_PACKAGE, ModuleType(FAKE_PACKAGE))
    monkeypatch.setitem(sys.modules, coordinator.__name__, coordinator)
    logger = FakeLogger()
    namespace = {
        "__name__": f"{FAKE_PACKAGE}.init",
        "__package__": FAKE_PACKAGE,
        "Any": object,
        "HomeAssistant": object,
        "TESLA_PROVIDER_TESLEMETRY": "teslemetry",
        "aiohttp": SimpleNamespace(
            ClientError=OSError,
            ClientTimeout=lambda *, total: total,
        ),
        "asyncio": SimpleNamespace(sleep=sleep, TimeoutError=asyncio.TimeoutError),
        "async_get_clientsession": lambda hass: session,
        "get_tesla_api_base_url": lambda provider, base: "https://api.test",
        "_LOGGER": logger,
    }
    exec(compile(ast.fix_missing_locations(module), str(INIT_PATH), "exec"), namespace)
    return namespace, logger


def _send(ns, tariff, **kwargs):
    return ns["send_tariff_to_tesla"](
        None, "site-1", tariff, "token", confirm_readback=False, **kwargs
    )


def test_newer_sync_cancels_pending_stale_retry(monkeypatch):
    """A 429 retry of an old tariff is dropped once a newer sync starts."""
    session = FakeSession([FakeResponse(429, retry_after=200), FakeResponse(200)])
    newer_sync_started = asyncio.Event()
    newer_sync_done = asyncio.Event()

    async def sleep(seconds):
        newer_sync_started.set()
        await newer_sync_done.wait()

    ns, logger = _load(monkeypatch, session, sleep)

    async def scenario():
        stale = asyncio.ensure_future(_send(ns, {"code": "old"}))
        await newer_sync_started.wait()
        newer = await _send(ns, {"code": "new"})
        newer_sync_done.set()
        return await stale, newer

    stale_result, newer_result = asyncio.run(scenario())

    assert newer_result is True
    assert stale_result is False
    assert session.posts == [{"code": "old"}, {"code": "new"}]
    assert any("Cancelled stale TOU sync retry" in m for m in logger.messages)


def test_retry_respects_retry_after_when_not_superseded(monkeypatch):
    session = FakeSession([FakeResponse(429, retry_after=30), FakeResponse(200)])
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    ns, _logger = _load(monkeypatch, session, sleep)

    assert asyncio.run(_send(ns, {"code": "current"})) is True
    assert waits == [30.0]
    assert session.posts == [{"code": "current"}, {"code": "current"}]


def test_retry_backs_off_without_retry_after(monkeypatch):
    session = FakeSession(
        [FakeResponse(429), FakeResponse(429), FakeResponse(200)]
    )
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    ns, _logger = _load(monkeypatch, session, sleep)

    assert asyncio.run(_send(ns, {"code": "current"})) is True
    assert waits == [2, 4]


def test_periodic_sync_drops_retry_after_longer_than_cap(monkeypatch):
    """A long 429 Retry-After would land on the next sync and steal its slot."""
    session = FakeSession([FakeResponse(429, retry_after=200)])
    waits = []

    async def sleep(seconds):
        waits.append(seconds)

    ns, logger = _load(monkeypatch, session, sleep)

    result = asyncio.run(
        _send(
            ns,
            {"code": "current"},
            max_retry_after_seconds=ns["TOU_PERIODIC_SYNC_MAX_RETRY_AFTER_SECONDS"],
        )
    )

    assert result is False
    assert waits == []
    assert len(session.posts) == 1
    assert any("the next sync will send a fresher tariff" in m for m in logger.messages)


def test_periodic_tou_sync_passes_retry_after_cap():
    source = INIT_PATH.read_text()
    tree = ast.parse(source)
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_handle_sync_tou_internal"
    )
    handler_source = ast.get_source_segment(source, handler)

    assert handler_source is not None
    assert (
        "max_retry_after_seconds=TOU_PERIODIC_SYNC_MAX_RETRY_AFTER_SECONDS"
        in handler_source
    )
