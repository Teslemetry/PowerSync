"""Powerwall schemas must work without replacing Home Assistant's protobuf."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from google.protobuf import descriptor_pool
from packaging.requirements import Requirement
from packaging.version import Version
import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/power_sync"
SCHEMAS = COMPONENT / "powerwall_local/energy_device"
FIXTURE = json.loads((ROOT / "tests/fixtures/powerwall_energy_device_wire.json").read_text())


def _load_schemas():
    name = "ps_dependency_energy_device"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, SCHEMAS / "__init__.py", submodule_search_locations=[str(SCHEMAS)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_optional_powerwall_schemas_do_not_force_a_core_protobuf_upgrade():
    requirements = [
        Requirement(item)
        for item in json.loads((COMPONENT / "manifest.json").read_text())["requirements"]
    ]
    assert not any(item.name == "tesla-protocol" for item in requirements)
    protobuf = next(item for item in requirements if item.name == "protobuf")
    # HA Core 2024.8.0, 2025.10.0 and 2026.10.0 package_constraints.txt pins.
    for pin in ("4.25.1", "6.32.0", "7.36.0"):
        assert Version(pin) in protobuf.specifier


def test_setup_and_local_diagnostics_do_not_import_external_tesla_package():
    # HA installs requirements before choosing a provider. Include lazy imports.
    for relative in (
        "__init__.py", "powerwall_local/transport.py", "powerwall_local/fleet_api_bms.py"
    ):
        path = COMPONENT / relative
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("tesla_protocol"), path
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("tesla_protocol") for a in node.names), path


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_published_tesla_wire_messages_are_unchanged(case):
    schemas = _load_schemas()
    cls = getattr(getattr(schemas, case["module"]), case["message"])
    raw = bytes.fromhex(case["hex"])
    message = cls.FromString(raw)
    for path, expected in case["expected"].items():
        value = message
        for part in path.split("."):
            value = getattr(value, part)
        assert value == expected
    assert message.SerializeToString() == raw
    # Future gateway fields survive decode/re-encode without being understood.
    raw_with_unknown = raw + b"\xf8\x7f\x01"  # field 2047, varint 1
    assert cls.FromString(raw_with_unknown).SerializeToString() == raw_with_unknown


@pytest.mark.parametrize("external_first", [True, False])
def test_private_schema_pool_coexists_with_other_tesla_schemas(external_first):
    # Different schema revision, same file/type names, tested in both orders.
    code = f'''
import importlib.util, sys
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
path = {str(SCHEMAS)!r}
default = descriptor_pool.Default()
foreign = descriptor_pb2.FileDescriptorProto(name="signed_message.proto", package="tesla.proto.energy_device.v1", syntax="proto3")
message = foreign.message_type.add(name="RoutableMessage")
message.field.add(name="foreign_only", number=1000, type=9, label=1)
def register_foreign():
    descriptor = default.Add(foreign)
    return message_factory.GetMessageClass(descriptor.message_types_by_name["RoutableMessage"])
if {external_first!r}:
    other = register_foreign()
spec = importlib.util.spec_from_file_location("isolated_energy", path + "/__init__.py", submodule_search_locations=[path])
bundled = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bundled
spec.loader.exec_module(bundled)
if not {external_first!r}:
    other = register_foreign()
local = bundled.signed_message_pb2.RoutableMessage
assert local.DESCRIPTOR.file.pool is not default
assert "foreign_only" not in local.DESCRIPTOR.fields_by_name
assert other(foreign_only="preserved").foreign_only == "preserved"
assert local(to_destination={{"domain": 7}}).to_destination.domain == 7
event = bundled.transport_pb2.MessageEnvelope().teg.get_backup_events_response.manual_backup_event.scheduling_info
event.start_time.FromJsonString("2026-10-14T00:00:00Z")
assert event.start_time.ToJsonString() == "2026-10-14T00:00:00Z"
'''
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


def test_bundled_pool_does_not_register_tesla_types_globally():
    schemas = _load_schemas()
    assert schemas.transport_pb2.DESCRIPTOR.pool is not descriptor_pool.Default()
    assert schemas.signed_message_pb2.Domain.Name(7) == "DOMAIN_ENERGY_DEVICE"
