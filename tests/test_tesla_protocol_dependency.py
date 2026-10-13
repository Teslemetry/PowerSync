"""Regression coverage for the Tesla protocol/HA protobuf constraint boundary."""

from __future__ import annotations

import json
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version


MANIFEST = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "power_sync"
    / "manifest.json"
)


def test_tesla_protocol_range_has_a_candidate_for_ha_protobuf_6320():
    manifest = json.loads(MANIFEST.read_text())
    tesla_requirement = Requirement(
        next(
            requirement
            for requirement in manifest["requirements"]
            if requirement.startswith("tesla-protocol")
        )
    )

    # 1.4.0 is the latest published pre-2.0 candidate and accepts HA's
    # protobuf==6.32.0 constraint.  2.0.0 is the incompatible schema line.
    assert Version("1.4.0") in tesla_requirement.specifier
    assert Version("2.0.0") not in tesla_requirement.specifier
    assert Version("6.32.0") in Requirement("protobuf>=6.32.0,<8").specifier
