"""Worker/Python interoperability, denial replay and local admission invariants."""
from dataclasses import replace
import base64
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "custom_components/power_sync/licensing"
PACKAGE = "_ha_licensing_contract_tests"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(PATH)]
sys.modules[PACKAGE] = package


def load(name):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", PATH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


permission = load("permission")
admission = load("admission")
fixture = json.loads((ROOT / "tests/fixtures/ha_optimizer_permission.json").read_text())
keys = {fixture["key_id"]: base64.urlsafe_b64decode(fixture["public_key"] + "=")}
NOW = fixture["now"]
ID = fixture["installation_id"]
# Public RFC 8032 vector; used only to create signed malformed test claims.
private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"))


def signed(claims, header=None):
    enc = lambda obj: base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode().rstrip("=")
    body = f"{enc(header or {'alg': 'EdDSA', 'typ': 'PSHA1', 'kid': fixture['key_id']})}.{enc(claims)}"
    return body + "." + base64.urlsafe_b64encode(private.sign(body.encode())).decode().rstrip("=")


def verify(token=None, **kwargs):
    return permission.verify_permission(token or fixture["permission"], keys, ID, NOW, **kwargs)


def test_worker_signed_permission_and_denial():
    valid = verify()
    assert valid.entitled and valid.allows_optimization(NOW)
    assert valid.expires_at == NOW + 7 * 86400
    denied = verify(fixture["denial"])
    assert not denied.entitled and not denied.allows_optimization(NOW)
    with pytest.raises(permission.PermissionError, match="stale_revision"):
        verify(minimum_epoch=denied.epoch, minimum_revision=denied.revision)


@pytest.mark.parametrize("field,value", [
    ("issuer", "attacker"), ("audience", "cloud:controls"), ("installation_id", "other-instance"),
    ("schema", True), ("schema", 2), ("credential_generation", 2),
    ("policy_epoch", 0), ("entitlement_revision", False),
    ("issued_at", NOW + 301), ("expires_at", NOW), ("expires_at", NOW + 8 * 86400),
    ("refresh_after", NOW - 1), ("features", ["cloud_controls"]),
    ("features", []), ("source_state", "subscription_required"), ("source_state", []),
])
def test_signed_invalid_claims_cannot_grant_access(field, value):
    claims = {**fixture["claims"], field: value}
    with pytest.raises(permission.PermissionError):
        verify(signed(claims))


def test_integrity_unknown_key_and_algorithm():
    parts = fixture["permission"].split(".")
    parts[1] = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
    with pytest.raises(permission.PermissionError):
        verify(".".join(parts))
    for header in ({"alg": "HS256", "typ": "PSHA1", "kid": fixture["key_id"]},
                   {"alg": "EdDSA", "typ": "PSHA1", "kid": "untrusted"}):
        with pytest.raises(permission.PermissionError):
            verify(signed(fixture["claims"], header))


def test_epoch_and_explicit_resume_preserve_stale_work_block():
    gate = admission.OptimizerAdmission(enforced=True)
    gate.replace(verify())
    queued_generation = gate.generation
    assert gate.permits(NOW, generation=queued_generation)
    gate.replace(verify(fixture["denial"]))
    assert not gate.permits(NOW, generation=queued_generation)
    newer = replace(verify(), revision=9)
    gate.replace(newer)
    assert not gate.permits(NOW), "new payment must not automatically resume suspended work"
    gate.resume(NOW)
    assert gate.permits(NOW) and not gate.permits(NOW, generation=queued_generation)
    with pytest.raises(ValueError, match="stale_revision"):
        gate.replace(verify())


def test_expiry_closes_gate_and_shadow_does_not_change_existing_access():
    gate = admission.OptimizerAdmission(enforced=True)
    gate.replace(verify())
    assert not gate.permits(NOW + 7 * 86400)
    assert gate.suspended
    gate.replace(replace(verify(), revision=9, issued_at=NOW + 7 * 86400, refresh_after=NOW + 8 * 86400, expires_at=NOW + 14 * 86400))
    assert not gate.permits(NOW + 7 * 86400)
    shadow = admission.OptimizerAdmission()
    assert shadow.permits(NOW)
    assert shadow.api_status(NOW)["enforcement_mode"] == "shadow"
