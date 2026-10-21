"""Execute startup provider selection and title migration without HA/network setup."""

import ast
from copy import deepcopy
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture(scope="module")
def migrate_title():
    source = (Path(__file__).parents[1] / "custom_components/power_sync/__init__.py").read_text()
    setup = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_setup_entry"
    )
    start = next(
        i for i, node in enumerate(setup.body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "electricity_provider" for target in node.targets)
    )
    end = next(
        i for i, node in enumerate(setup.body[start:], start)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Attribute)
        and node.test.left.attr == "title"
    )
    probe = ast.FunctionDef(
        name="migrate_title",
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg="hass"), ast.arg(arg="entry")],
                           kwonlyargs=[], kw_defaults=[], defaults=[]),
        body=setup.body[start:end + 1],
        decorator_list=[],
    )
    namespace = {
        "CONF_ELECTRICITY_PROVIDER": "electricity_provider",
        "CONF_AMBER_API_TOKEN": "amber_api_token",
        "CONF_AEMO_SPIKE_ENABLED": "aemo_spike_enabled",
        "_sync_covau_withdrawn_plan_issue": Mock(),
        "_LOGGER": logging.getLogger(__name__),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[probe], type_ignores=[])),
                 "<startup-title-migration>", "exec"), namespace)
    return namespace["migrate_title"]


@pytest.mark.parametrize("old_title", ["PowerSync Octopus", "PowerSync Amber", "PowerSync Custom TOU"])
@pytest.mark.parametrize("options_override", [False, True])
def test_custom_provider_keeps_identity_on_startup_and_reload(migrate_title, old_title, options_override):
    """Custom saved after Octopus must repair the heading without changing rates."""
    data = {"electricity_provider": "octopus" if options_override else "other",
            "aemo_spike_enabled": True, "initial_custom_tariff": {"peak": 29.5, "off_peak": 7.5}}
    options = {"electricity_provider": "other"} if options_override else {}
    entry = SimpleNamespace(title=old_title, data=data, options=options)
    before = deepcopy((data, options))

    def update(target, **changes):
        assert changes == {"title": "PowerSync Custom TOU"}
        target.title = changes["title"]

    updater = Mock(side_effect=update)
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=updater))
    migrate_title(hass, entry)
    migrate_title(hass, entry)  # Reload is idempotent after migration.
    assert entry.title == "PowerSync Custom TOU"
    assert updater.call_count == (0 if old_title == "PowerSync Custom TOU" else 1)
    assert (entry.data, entry.options) == before


@pytest.mark.parametrize(("provider", "token", "spike", "expected"), [
    ("aemo_vpp", False, False, "PowerSync AEMO"),
    ("globird", False, False, "PowerSync Globird"),
    ("flow_power", False, False, "PowerSync Flow Power"),
    ("agl", False, False, "PowerSync AGL Battery Rewards"),
    ("localvolts", False, False, "PowerSync Localvolts"),
    ("octopus", False, True, "PowerSync Octopus"),
    ("epex", False, False, "PowerSync EPEX"),
    ("nz", False, False, "PowerSync NZ"),
    ("covau", False, True, "PowerSync CovaU SolarMax"),
    ("amber", True, True, "PowerSync Amber"),
    ("amber", False, True, "PowerSync Globird"),
    ("", False, True, "PowerSync Globird"),
    (None, False, False, "PowerSync Amber"),
])
def test_existing_provider_titles(migrate_title, provider, token, spike, expected):
    data = {"amber_api_token": "token" if token else "", "aemo_spike_enabled": spike}
    if provider is not None:
        data["electricity_provider"] = provider
    entry = SimpleNamespace(title="Old title", data=data, options={})
    updater = Mock()
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=updater))
    migrate_title(hass, entry)
    updater.assert_called_once_with(entry, title=expected)
