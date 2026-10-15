"""Strict verification of Cloud-signed HA permissions and denial revisions."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ISSUER = "powersync-ha-licensing"
AUDIENCE = "power_sync:ha_optimizer"
MAX_LEASE_SECONDS = 7 * 86400
SOURCES = {"paid", "trial", "billing_pending", "sponsor", "transition", "support", "payment_grace"}
DENIALS = {"subscription_required", "installation_revoked"}


class PermissionError(ValueError):
    """A permission cannot be trusted; its contents must not grant access."""


def _decode(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise PermissionError("invalid_encoding")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as error:
        raise PermissionError("invalid_encoding") from error


def _object(value: bytes) -> dict:
    def pairs(rows):
        result = {}
        for key, item in rows:
            if key in result:
                raise PermissionError("duplicate_claim")
            result[key] = item
        return result
    try:
        obj = json.loads(value, object_pairs_hook=pairs)
    except (ValueError, UnicodeDecodeError) as error:
        raise PermissionError("invalid_json") from error
    if not isinstance(obj, dict):
        raise PermissionError("invalid_claims")
    return obj


@dataclass(frozen=True)
class VerifiedPermission:
    installation_id: str
    generation: int
    revision: int
    epoch: int
    issued_at: int
    refresh_after: int
    expires_at: int
    source: str
    entitled: bool

    def allows_optimization(self, now: int) -> bool:
        return self.entitled and self.issued_at - 300 <= now < self.expires_at


def verify_permission(
    token: str, public_keys: Mapping[str, bytes], installation_id: str, now: int,
    *, generation: int = 1, minimum_epoch: int = 0, minimum_revision: int = 0,
) -> VerifiedPermission:
    if not isinstance(token, str) or len(token) > 4096:
        raise PermissionError("permission_too_large")
    parts = token.split(".")
    if len(parts) != 3:
        raise PermissionError("invalid_permission")
    header = _object(_decode(parts[0]))
    if set(header) != {"alg", "typ", "kid"} or header.get("alg") != "EdDSA" or header.get("typ") != "PSHA1":
        raise PermissionError("invalid_algorithm")
    key_id = header.get("kid")
    if not isinstance(key_id, str) or key_id not in public_keys:
        raise PermissionError("unknown_signing_key")
    try:
        Ed25519PublicKey.from_public_bytes(public_keys[key_id]).verify(_decode(parts[2]), f"{parts[0]}.{parts[1]}".encode("ascii"))
    except (InvalidSignature, ValueError) as error:
        raise PermissionError("invalid_signature") from error
    claims = _object(_decode(parts[1]))
    expected = {"schema", "issuer", "audience", "installation_id", "features", "credential_generation", "entitlement_revision", "policy_epoch", "issued_at", "refresh_after", "expires_at", "source_state"}
    if set(claims) != expected or claims["schema"] != 1 or type(claims["schema"]) is not int:
        raise PermissionError("unsupported_schema")
    if claims["issuer"] != ISSUER or claims["audience"] != AUDIENCE or claims["installation_id"] != installation_id:
        raise PermissionError("wrong_permission_scope")
    numeric = ("credential_generation", "entitlement_revision", "policy_epoch", "issued_at", "refresh_after", "expires_at")
    if any(type(claims[field]) is not int or not 0 <= claims[field] <= 2**53 - 1 for field in numeric):
        raise PermissionError("invalid_time_or_revision")
    if claims["credential_generation"] != generation or claims["policy_epoch"] < 1 or claims["policy_epoch"] < minimum_epoch:
        raise PermissionError("stale_generation")
    if claims["policy_epoch"] == minimum_epoch and claims["entitlement_revision"] < minimum_revision:
        raise PermissionError("stale_revision")
    start, refresh, end = (claims[k] for k in ("issued_at", "refresh_after", "expires_at"))
    if not start <= refresh <= end or end <= start or end - start > MAX_LEASE_SECONDS:
        raise PermissionError("invalid_permission_lifetime")
    if start > now + 300 or now >= end:
        raise PermissionError("permission_not_current")
    source = claims["source_state"]
    allowed = isinstance(source, str) and source in SOURCES and claims["features"] == ["ha_optimizer"]
    denied = isinstance(source, str) and source in DENIALS and claims["features"] == []
    if not allowed and not denied:
        raise PermissionError("invalid_features")
    return VerifiedPermission(installation_id, generation, claims["entitlement_revision"], claims["policy_epoch"], start, refresh, end, source, allowed)
