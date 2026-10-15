"""Access guidance follows local pairing, admission and recovery independently."""
import ast
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/power_sync"
spec = importlib.util.spec_from_file_location("_ha_access_presentation", COMPONENT / "licensing/presentation.py")
presentation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presentation)


def status(**changes):
    return {
        "access_state": "transition", "paired": True, "requires_resume": False,
        "can_optimize": True, "would_allow": True, "recovery_pending": False,
        "enforcement_mode": "shadow", "account_url": "https://powersync.cc/app/ha",
        "legacy_access_until": int(datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp()),
        **changes,
    }


def test_paired_transition_is_distinct_from_trial_and_needs_no_resume():
    result = presentation.optimizer_access_description(status())
    assert "Free existing-user transition" in result["access_summary"]
    assert "23 October 2026 at 00:00 UTC" in result["access_summary"]
    assert "separate from the seven-day trial" in result["access_summary"]
    assert result["pairing_status"].startswith("Paired")
    assert "No Resume action is needed" in result["next_step"]
    assert "close this window" in result["next_step"]
    assert "Start pairing" not in result["next_step"]
    assert "settings still determine" in result["next_step"]


def test_transition_does_not_imply_server_pairing():
    result = presentation.optimizer_access_description(status(paired=False))
    assert result["pairing_status"].startswith("Not paired")
    assert "Start pairing" in result["next_step"]
    assert "GitHub or Discord" in result["next_step"]
    assert "close this window" not in result["next_step"]


def test_pending_code_requests_approval_and_finish():
    result = presentation.optimizer_access_description(status(paired=False), "approval-code")
    assert "approval-code" in result["next_step"]
    assert "https://powersync.cc/app/ha" in result["next_step"]
    assert "Finish pairing" in result["next_step"]
    assert "Start pairing" not in result["next_step"]


@pytest.mark.parametrize("access_state", ["paid", "sponsor", "trial", "billing_pending", "payment_grace", "support"])
def test_valid_sources_do_not_show_raw_state_or_repairing(access_state):
    result = presentation.optimizer_access_description(status(access_state=access_state))
    assert result["access_summary"] != access_state
    assert "No Resume action is needed" in result["next_step"]
    assert "pairing" not in result["next_step"]


def test_recovery_takes_precedence_over_resume():
    result = presentation.optimizer_access_description(status(recovery_pending=True, requires_resume=True, can_optimize=False))
    assert "Recovery is still pending" in result["next_step"]
    assert "Choose **Resume optimisation**" not in result["next_step"]


def test_valid_access_with_resume_required_does_not_claim_ready():
    result = presentation.optimizer_access_description(status(requires_resume=True, can_optimize=False))
    assert "Choose **Resume optimisation**" in result["next_step"]
    assert "close this window" not in result["next_step"]


@pytest.mark.parametrize("access_state", ["expired", "subscription_required", "checking", "installation_revoked", "unknown_future_state"])
def test_unavailable_access_is_not_presented_as_ready(access_state):
    result = presentation.optimizer_access_description(status(
        access_state=access_state, requires_resume=True, can_optimize=False,
        would_allow=False, enforcement_mode="enforced",
    ))
    assert "Once access is restored" in result["next_step"]
    assert "No Resume action is needed" not in result["next_step"]


def flow_method(monkeypatch, manager):
    """Run the actual options method with only HA form rendering stubbed."""
    package = "_ha_access_flow_tests"
    for name in (package, f"{package}.licensing"):
        module = ModuleType(name)
        module.__path__ = []
        monkeypatch.setitem(sys.modules, name, module)
    module = ModuleType(f"{package}.licensing.manager")
    module.async_get_manager = AsyncMock(return_value=manager)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setitem(sys.modules, f"{package}.licensing.presentation", presentation)
    tree = ast.parse((COMPONENT / "config_flow.py").read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_optimizer_access")
    namespace = {
        "__package__": package,
        "vol": SimpleNamespace(Schema=lambda schema: schema, Required=lambda name, **kwargs: name),
        "SelectSelector": lambda config: config,
        "SelectSelectorConfig": lambda **kwargs: kwargs,
        "SelectSelectorMode": SimpleNamespace(DROPDOWN="dropdown"),
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), "config_flow.py", "exec"), namespace)
    return namespace[method.name]


@pytest.mark.parametrize("action", ["finish_pairing", "reset_pairing"])
def test_successful_pairing_or_reset_clears_previous_code(monkeypatch, action):
    manager = SimpleNamespace(
        finish_pairing=AsyncMock(), reset_pairing=AsyncMock(),
        status=lambda entry: status(paired=action == "finish_pairing"),
    )
    flow = SimpleNamespace(hass=object(), config_entry=SimpleNamespace(entry_id="one"),
                           _license_pairing_code="old-code", async_show_form=lambda **kwargs: kwargs)
    result = asyncio.run(flow_method(monkeypatch, manager)(flow, {"action": action}))
    assert flow._license_pairing_code is None
    assert "old-code" not in result["description_placeholders"]["next_step"]
    assert not result["errors"]
    if action == "finish_pairing":
        manager.finish_pairing.assert_awaited_once_with("old-code")
        assert "No Resume action is needed" in result["description_placeholders"]["next_step"]
    else:
        manager.reset_pairing.assert_awaited_once()
        assert "Start pairing" in result["description_placeholders"]["next_step"]


def test_failed_pairing_retains_code_for_retry(monkeypatch):
    manager = SimpleNamespace(finish_pairing=AsyncMock(side_effect=ValueError("not_approved")),
                              status=lambda entry: status(paired=False))
    flow = SimpleNamespace(hass=object(), config_entry=SimpleNamespace(entry_id="one"),
                           _license_pairing_code="retry-code", async_show_form=lambda **kwargs: kwargs)
    result = asyncio.run(flow_method(monkeypatch, manager)(flow, {"action": "finish_pairing"}))
    assert flow._license_pairing_code == "retry-code"
    assert "retry-code" in result["description_placeholders"]["next_step"]
    assert result["errors"]["base"] == "optimizer_access_unavailable"


def test_translations_render_the_actual_placeholders():
    steps = [json.loads((COMPONENT / name).read_text())["options"]["step"]["optimizer_access"]
             for name in ("strings.json", "translations/en.json")]
    assert steps[0] == steps[1]
    rendered = steps[0]["description"].format(**presentation.optimizer_access_description(status()))
    assert "Resume required: False" not in rendered
    assert "Not started" not in rendered
    assert "No Resume action is needed" in rendered
