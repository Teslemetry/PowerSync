"""Signed rollout policy, separate from an installation's paid permission."""
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

from .permission import _decode, _object, PermissionError, ISSUER, MAX_LEASE_SECONDS


@dataclass(frozen=True)
class RolloutPolicy:
    epoch: int
    mode: str
    activation_at: int | None
    legacy_until: int | None
    issued_at: int
    expires_at: int

    def enforces(self, now: int) -> bool:
        return self.mode == "enforced" and now >= max(self.activation_at or 0, self.legacy_until or 0)


def verify_policy(token, keys, now, *, minimum_epoch=0):
    if not isinstance(token, str) or len(token) > 4096:
        raise PermissionError("invalid_policy")
    parts = token.split(".")
    if len(parts) != 3:
        raise PermissionError("invalid_policy")
    header = _object(_decode(parts[0]))
    if set(header) != {"alg", "typ", "kid"} or header["alg"] != "EdDSA" or header["typ"] != "PSHP1" or not isinstance(header["kid"], str) or header["kid"] not in keys:
        raise PermissionError("untrusted_policy_key")
    try:
        Ed25519PublicKey.from_public_bytes(keys[header["kid"]]).verify(_decode(parts[2]), f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (ValueError, InvalidSignature) as err:
        raise PermissionError("invalid_policy_signature") from err
    value = _object(_decode(parts[1]))
    expected = {"schema", "issuer", "audience", "policy_epoch", "rollout_mode", "activation_at", "legacy_access_until", "issued_at", "expires_at"}
    if set(value) != expected or type(value["schema"]) is not int or value["schema"] != 1 or value["issuer"] != ISSUER or value["audience"] != "power_sync:ha_policy":
        raise PermissionError("invalid_policy_scope")
    for key in ("policy_epoch", "issued_at", "expires_at"):
        if type(value[key]) is not int or not 0 <= value[key] <= 2**53 - 1:
            raise PermissionError("invalid_policy_time")
    for key in ("activation_at", "legacy_access_until"):
        if value[key] is not None and (type(value[key]) is not int or not 0 <= value[key] <= 2**53 - 1):
            raise PermissionError("invalid_policy_time")
    if value["policy_epoch"] < max(1, minimum_epoch) or value["rollout_mode"] not in ("shadow", "enforced"):
        raise PermissionError("stale_policy")
    if value["rollout_mode"] == "enforced" and (value["activation_at"] is None or value["legacy_access_until"] is None or value["legacy_access_until"] < value["activation_at"]):
        raise PermissionError("missing_fixed_cutoff")
    if not value["issued_at"] <= now + 300 or not value["issued_at"] < value["expires_at"] <= value["issued_at"] + MAX_LEASE_SECONDS or now >= value["expires_at"]:
        raise PermissionError("policy_not_current")
    return RolloutPolicy(value["policy_epoch"], value["rollout_mode"], value["activation_at"], value["legacy_access_until"], value["issued_at"], value["expires_at"])
