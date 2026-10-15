"""Public-client Sign in with ChatGPT for the optimizer.

Only authenticated administrator endpoints may expose the authorization URL or
accept a callback. Tokens live in a private Home Assistant Store, never config
entries, status responses, logs, or diagnostics. Pending PKCE state is ephemeral.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import json
import logging
import math
import os
import stat
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp

_LOGGER = logging.getLogger(__name__)

ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
REDIRECT_URI = "http://127.0.0.1:1455/auth/callback"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED_SCOPES = frozenset(SCOPES.split())
LOGIN_LIFETIME = 600
# Kept outside hass.data["power_sync"], whose values are all config entries.
CHATGPT_AUTH_RETAINED_KEY = "power_sync_chatgpt_auth_retained"
MAX_RESPONSE_BYTES = 1024 * 1024
CLIENT_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,200}\Z")
MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_TERMINAL_ERRORS = {"invalid_grant", "invalid_client", "unauthorized_client", "access_denied"}
REMOTE_DISCONNECTION_WARNING = "Local credentials were removed. Remote disconnection could not be confirmed; disconnect PowerSync in ChatGPT Settings."


class ChatGPTAuthError(Exception):
    """An intentionally sanitized error suitable for an administrator response."""

    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(repr=False)
class _PendingLogin:
    owner_id: str
    login_id: str
    state: str
    nonce: str
    verifier: str
    expires_at: float
    client_id: str | None
    committing: bool = False


def _owned_operation(method):
    """Let credential work settle even if its HTTP or explanation caller leaves."""
    @wraps(method)
    async def owned(self, *args, **kwargs):
        if asyncio.current_task() in self._operations:
            return await method(self, *args, **kwargs)
        self._ensure_active()
        operation = asyncio.create_task(method(self, *args, **kwargs))
        self._operations.add(operation)
        operation.add_done_callback(self._operation_finished)
        return await asyncio.shield(operation)
    return owned


class ChatGPTAuthManager:
    """Manage one entry's registration and rotating credentials.

    ``session``, ``store``, and ``clock`` are injectable for isolated tests. Store
    must supply async_load/async_save; saves must replace the complete record.
    """

    def __init__(self, session: Any, store: Any, clock: Callable[[], float] = time.time) -> None:
        self._session = session
        self._store = store
        self._clock = clock
        self._lock = asyncio.Lock()
        self._loaded = False
        self._record: dict[str, Any] = {}
        self._pending: _PendingLogin | None = None
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_at = 0.0
        self._closed = False
        self._operations: set[asyncio.Task] = set()
        self._record_needs_save = False

    def _ensure_active(self) -> None:
        if self._closed:
            raise ChatGPTAuthError("integration_unavailable", "ChatGPT connection is restarting. Try again shortly.", 409)

    def _operation_finished(self, operation: asyncio.Task) -> None:
        self._operations.discard(operation)
        if not operation.cancelled():
            # A cancelled caller no longer retrieves the owned task's result.
            operation.exception()

    @_owned_operation
    async def async_load(self) -> None:
        async with self._lock:
            self._ensure_active()
            await self._load_locked()
            if self._record_needs_save:
                await self._save(self._record)

    async def _load_locked(self) -> None:
        if self._loaded:
            return
        try:
            if self._record_needs_save:
                # Preserve retirement from a failed validation write instead of
                # reloading the old durable credential record over it.
                await self._save(self._record)
                self._loaded = True
                return
            saved = await self._store.async_load()
            self._record = saved if isinstance(saved, dict) else {}
            host_id = self._record.get("host_id")
            if not isinstance(host_id, str) or not _valid_host_id(host_id):
                self._record["host_id"] = f"urn:uuid:{uuid.uuid4()}"
                await self._save(self._record)
            client = self._record.get("client_id")
            if client is not None and not _valid_client(client):
                self._record.pop("client_id", None)
                self._record.pop("credentials", None)
                self._record.pop("pending_refresh", None)
                self._record["status"] = "reconnect_required"
                await self._save(self._record)
            credentials = self._record.get("credentials")
            if credentials is not None and (not _valid_stored_credentials(credentials)
                                           or not _valid_scopes(self._record.get("scopes"))
                                           or not _nonempty_string(self._record.get("subject"))
                                           or not isinstance(self._record.get("identity"), dict) or not _valid_client(self._record.get("client_id"))):
                await self._disconnect_locked()
            rotation = self._record.get("pending_refresh")
            if rotation is not None and not _valid_rotation(rotation):
                await self._disconnect_locked()
            self._loaded = True
        except ChatGPTAuthError:
            raise
        except Exception:
            raise ChatGPTAuthError("storage_unavailable", "ChatGPT credential storage is unavailable.", 503) from None

    async def _save(self, record: dict[str, Any]) -> None:
        try:
            await self._store.async_save(copy.deepcopy(record))
        except Exception:
            raise ChatGPTAuthError("storage_unavailable", "ChatGPT credentials could not be saved securely.", 503) from None
        self._record = record
        self._record_needs_save = False

    def status(self) -> dict[str, Any]:
        """Return public fields only; never return a credential or callback state."""
        pending = self._pending
        if pending and pending.expires_at <= self._clock():
            self._pending = pending = None
        connected = bool(self._record.get("credentials")) and self._record.get("status") == "connected"
        identity = self._record.get("identity", {})
        if not isinstance(identity, dict):
            identity = {}
        status = {
            "connected": connected,
            "status": "connected" if connected else self._record.get("status", "disconnected"),
            "account": {key: identity[key] for key in ("email", "name") if isinstance(identity.get(key), str)} if connected else None,
            "scopes": list(self._record.get("scopes", [])) if connected else [],
            "pending": {"login_id": pending.login_id, "expires_at": pending.expires_at} if pending else None,
        }
        if self._record.get("remote_disconnection_pending") is True and not self._record_needs_save:
            status["warning"] = REMOTE_DISCONNECTION_WARNING
        return status

    async def _request(self, method: str, url: str, *, data: dict[str, str] | None = None,
                       token: str | None = None, empty_ok: bool = False) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with self._session.request(method, url, data=data, headers=headers,
                                             timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False) as response:
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ChatGPTAuthError("invalid_response", "ChatGPT returned an invalid response.", 502)
                try:
                    parsed = json.loads(body) if body else {}
                except (ValueError, UnicodeError):
                    parsed = {}
                if response.status < 200 or response.status >= 300:
                    provider_code = parsed.get("error") if isinstance(parsed, dict) else None
                    if isinstance(provider_code, dict):
                        provider_code = provider_code.get("code") or provider_code.get("type")
                    if isinstance(provider_code, str) and provider_code in _TERMINAL_ERRORS:
                        raise ChatGPTAuthError(provider_code, "Your ChatGPT connection is no longer valid. Sign in again.", 401)
                    if response.status == 401:
                        raise ChatGPTAuthError("invalid_grant", "Your ChatGPT connection is no longer valid. Sign in again.", 401)
                    raise ChatGPTAuthError("provider_unavailable", "ChatGPT could not complete the request. Try again shortly.", 503)
                if not isinstance(parsed, dict) or (not body and not empty_ok):
                    raise ChatGPTAuthError("invalid_response", "ChatGPT returned an invalid response.", 502)
                return parsed
        except ChatGPTAuthError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
            # The underlying exception may contain tokens, request bodies, or a
            # callback URL. Emit only fixed labels and a bounded errno, never
            # its message/repr, traceback, URL, headers, or account metadata.
            operation = "provider_request"
            if method == "POST" and data:
                if data.get("grant_type") == "authorization_code":
                    operation = "authorization_code_exchange"
                elif data.get("grant_type") == "refresh_token":
                    operation = "token_refresh"
                elif data.get("token_type_hint") == "refresh_token":
                    operation = "session_revocation"
            elif method == "GET":
                if url == f"{ISSUER}/.well-known/openid-configuration":
                    operation = "discovery"
                elif url == f"{RESOURCE}/models":
                    operation = "model_catalog"
                elif self._discovery and url == self._discovery.get("jwks_uri"):
                    operation = "identity_keys"
            errno = getattr(error, "errno", None)
            if not isinstance(errno, int) or isinstance(errno, bool) or not -4096 <= errno <= 4096:
                errno = None
            _LOGGER.warning("ChatGPT transport failure: operation=%s category=%s errno=%s",
                            operation, _network_failure_category(error), errno)
            raise ChatGPTAuthError("network_error", "ChatGPT is temporarily unreachable. Try again shortly.", 503) from None

    async def _configuration(self) -> dict[str, Any]:
        if self._discovery is None:
            data = await self._request("GET", f"{ISSUER}/.well-known/openid-configuration")
            if data.get("issuer") != ISSUER:
                raise ChatGPTAuthError("discovery_failed", "ChatGPT sign-in configuration could not be verified.", 503)
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri", "revocation_endpoint"):
                value = data.get(key)
                if key == "revocation_endpoint" and value is None:
                    continue
                if not isinstance(value, str) or not _trusted_endpoint(value):
                    raise ChatGPTAuthError("discovery_failed", "ChatGPT sign-in configuration could not be verified.", 503)
            self._discovery = data
        return self._discovery

    @_owned_operation
    async def async_start_login(self, owner_id: str) -> dict[str, Any]:
        if not isinstance(owner_id, str) or not owner_id:
            raise ChatGPTAuthError("owner_required", "An authenticated administrator must start sign-in.", 403)
        async with self._lock:
            self._ensure_active()
            await self._load_locked()
            self.status()
            if self._pending and self._pending.owner_id != owner_id:
                raise ChatGPTAuthError("login_owned", "Another administrator has a pending ChatGPT sign-in.", 409)
            config = await self._configuration()
            pending = _PendingLogin(owner_id, secrets.token_urlsafe(32), secrets.token_urlsafe(32),
                                    secrets.token_urlsafe(32), secrets.token_urlsafe(32),
                                    self._clock() + LOGIN_LIFETIME, self._record.get("client_id"))
            challenge = base64.urlsafe_b64encode(hashlib.sha256(pending.verifier.encode()).digest()).rstrip(b"=").decode()
            params = {"client_id": pending.client_id or "dynamic_agent_client", "response_type": "code",
                      "redirect_uri": REDIRECT_URI, "scope": SCOPES, "resource": RESOURCE,
                      "state": pending.state, "nonce": pending.nonce, "code_challenge_method": "S256",
                      "code_challenge": challenge, "ext_agent_host_id": self._record["host_id"]}
            if not pending.client_id:
                params["agent_name_hint"] = "PowerSync"
            self._pending = pending
            return {"login_id": pending.login_id, "auth_url": config["authorization_endpoint"] + "?" + urlencode(params),
                    "expires_at": pending.expires_at}

    def _require_pending(self, login_id: str, owner_id: str) -> _PendingLogin:
        pending = self._pending
        if not pending or pending.expires_at <= self._clock():
            if pending and pending.expires_at <= self._clock():
                self._pending = None
            raise ChatGPTAuthError("login_expired", "ChatGPT sign-in expired. Start sign-in again.", 410)
        if (pending.owner_id != owner_id or not isinstance(login_id, str) or not login_id.isascii()
                or not hmac.compare_digest(pending.login_id, login_id)):
            raise ChatGPTAuthError("login_mismatch", "This ChatGPT sign-in belongs to another session.", 403)
        return pending

    def login_restart_required(self, login_id: str, owner_id: str) -> bool:
        """Report whether this caller's login can still accept corrected input."""
        if self._closed:
            return True
        try:
            self._require_pending(login_id, owner_id)
        except ChatGPTAuthError:
            return True
        return False

    @_owned_operation
    async def async_complete_login(self, callback_url: str, login_id: str, owner_id: str) -> dict[str, Any]:
        async with self._lock:
            self._ensure_active()
            await self._load_locked()
            pending = self._require_pending(login_id, owner_id)
            try:
                if not isinstance(callback_url, str) or len(callback_url) > 16384:
                    raise ValueError
                parsed = urlsplit(callback_url.strip())
                if parsed.scheme != "http" or parsed.netloc != "127.0.0.1:1455" or parsed.path != "/auth/callback" or parsed.fragment:
                    raise ValueError
                params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=30)
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError
                state = params.get("state", [""])[0]
                if not hmac.compare_digest(state.encode(), pending.state.encode()):
                    raise ValueError
            except (ValueError, TypeError):
                raise ChatGPTAuthError("invalid_callback", "Paste the full callback URL from this sign-in session.") from None
            if "error" in params:
                self._pending = None
                raise ChatGPTAuthError("authorization_denied", "ChatGPT sign-in was declined or cancelled.")
            code = params.get("code", [""])[0]
            returned_client = params.get("client_id", [None])[0]
            client = returned_client or pending.client_id
            if not code or not _valid_client(client) or (pending.client_id and returned_client and returned_client != pending.client_id):
                raise ChatGPTAuthError("registration_incomplete", "ChatGPT app registration was incomplete. Start sign-in again.")
            # Preserve the issued registration even when the one-time exchange fails.
            await self._save({**self._record, "client_id": client})
            try:
                if self._pending is not pending:
                    raise ChatGPTAuthError("cancelled", "ChatGPT sign-in was cancelled.", 409)
                config = await self._configuration()
                data = await self._request("POST", config["token_endpoint"], data={"grant_type": "authorization_code",
                                           "client_id": client, "code": code, "code_verifier": pending.verifier,
                                           "redirect_uri": REDIRECT_URI, "resource": RESOURCE})
                fields = self._token_fields(data)
                identity = await self._verify_identity(data.get("id_token"), client, nonce=pending.nonce)
                if self._record.get("subject") and identity["subject"] != self._record["subject"]:
                    raise ChatGPTAuthError("account_mismatch", "Sign in with the ChatGPT account already connected to PowerSync.")
                if self._pending is not pending:
                    raise ChatGPTAuthError("cancelled", "ChatGPT sign-in was cancelled.", 409)
                self._require_pending(login_id, owner_id)
                record = {key: value for key, value in self._record.items() if key not in ("pending_refresh", "credentials", "identity", "subject", "scopes", "remote_disconnection_pending")}
                # Once the durable write begins, cancellation must wait for its
                # result rather than report a disconnected state that can change.
                pending.committing = True
                await self._save({**record, **identity, **fields, "status": "connected"})
            except ChatGPTAuthError as error:
                if error.code in {"invalid_client", "unauthorized_client"}:
                    try:
                        await self._disconnect_locked(retire_client=True, reconnect_required=bool(self._record.get("subject")))
                    except ChatGPTAuthError:
                        pass  # Keep the provider error when retiring the registration cannot be saved.
                raise
            finally:
                if self._pending is pending:
                    self._pending = None
            return self.status()

    @_owned_operation
    async def async_cancel_login(self, login_id: str, owner_id: str) -> dict[str, Any]:
        # Clear promptly even while the code exchange is waiting on the network.
        self._ensure_active()
        pending = self._require_pending(login_id, owner_id)
        if pending.committing:
            async with self._lock:
                return self.status()
        self._pending = None
        return self.status()

    def _token_fields(self, data: dict[str, Any], previous_scopes: list[str] | None = None) -> dict[str, Any]:
        scope = data.get("scope")
        if scope is None and previous_scopes is not None:
            scope = " ".join(previous_scopes)
        if not isinstance(scope, str) or not REQUIRED_SCOPES.issubset(scope.split()):
            raise ChatGPTAuthError("missing_scope", "ChatGPT did not grant the permissions PowerSync requires. Sign in again.")
        expiry = data.get("expires_in")
        if (not isinstance(expiry, (int, float)) or isinstance(expiry, bool) or not math.isfinite(expiry)
                or expiry <= 0 or expiry > 366 * 86400 or str(data.get("token_type", "")).lower() != "bearer"
                or not _valid_token(data.get("access_token")) or not _valid_token(data.get("refresh_token"))):
            raise ChatGPTAuthError("invalid_token_response", "ChatGPT returned incomplete credentials. Sign in again.")
        return {"scopes": scope.split(), "credentials": {"access_token": data["access_token"],
                "refresh_token": data["refresh_token"], "expires_at": self._clock() + expiry}}

    async def _verify_identity(self, token: Any, client: str, *, nonce: str | None = None,
                               received_at: float | None = None) -> dict[str, Any]:
        if not _nonempty_string(token):
            raise ChatGPTAuthError("invalid_id_token", "ChatGPT did not return a verifiable identity. Sign in again.")
        try:
            import jwt
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError
        except Exception as error:
            # No untrusted parser details are exposed or logged.
            if isinstance(error, ImportError):
                raise ChatGPTAuthError("identity_verification_unavailable", "ChatGPT identity verification is unavailable.", 503) from None
            raise ChatGPTAuthError("invalid_id_token", "ChatGPT identity could not be verified. Sign in again.") from None
        config = await self._configuration()
        try:
            if self._jwks is None or self._clock() - self._jwks_at > 3600:
                self._jwks = await self._request("GET", config["jwks_uri"])
                self._jwks_at = self._clock()
            keys = self._jwks.get("keys")
            if not isinstance(keys, list):
                raise ValueError
            matches = [key for key in keys if isinstance(key, dict) and key.get("kid") == header["kid"] and key.get("kty") == "RSA"]
            if not matches:
                self._jwks = await self._request("GET", config["jwks_uri"])
                keys = self._jwks.get("keys", [])
                matches = [key for key in keys if isinstance(key, dict) and key.get("kid") == header["kid"] and key.get("kty") == "RSA"]
            if len(matches) != 1:
                raise ValueError
            key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
        except Exception:
            self._jwks = None
            raise ChatGPTAuthError("identity_verification_unavailable", "ChatGPT identity verification is temporarily unavailable. Try again shortly.", 503) from None
        try:
            claims = jwt.decode(token, key, algorithms=["RS256"], issuer=ISSUER, audience=client,
                                options={"require": ["iss", "aud", "sub", "iat", "exp"], "verify_exp": False, "verify_iat": False, "verify_nbf": False})
            now = self._clock() if received_at is None else received_at
            if (not isinstance(claims["exp"], (int, float)) or isinstance(claims["exp"], bool) or not math.isfinite(claims["exp"])
                    or claims["exp"] < now - 5 or not isinstance(claims["iat"], (int, float))
                    or isinstance(claims["iat"], bool) or not math.isfinite(claims["iat"]) or claims["iat"] > now + 5
                    or ("nbf" in claims and (not isinstance(claims["nbf"], (int, float)) or isinstance(claims["nbf"], bool)
                                           or not math.isfinite(claims["nbf"]) or claims["nbf"] > now + 5))
                    or not _nonempty_string(claims["sub"]) or (nonce is not None and claims.get("nonce") != nonce)
                    or ("azp" in claims and claims["azp"] != client)
                    or (isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client)):
                raise ValueError
            return {"subject": claims["sub"], "identity": {key: claims[key] for key in ("email", "name") if isinstance(claims.get(key), str)}}
        except Exception:
            raise ChatGPTAuthError("invalid_id_token", "ChatGPT identity could not be verified. Sign in again.") from None

    async def _disconnect_locked(self, *, retire_client: bool = False, reconnect_required: bool = True) -> None:
        retired = {"credentials", "pending_refresh", "identity", "scopes"}
        if retire_client:
            retired.add("client_id")
        record = {key: value for key, value in self._record.items() if key not in retired}
        disconnected = {**record, "status": "reconnect_required" if reconnect_required else "disconnected"}
        try:
            await self._save(disconnected)
        except ChatGPTAuthError:
            # A consumed or rejected grant cannot remain usable in memory just
            # because its durable removal failed. Block handoff until saved.
            self._record = disconnected
            self._record_needs_save = True
            raise

    @_owned_operation
    async def async_access_token(self, force_refresh: bool = False, rejected_token: str | None = None) -> str:
        async with self._lock:
            self._ensure_active()
            await self._load_locked()
            credentials = self._record.get("credentials")
            if self._record.get("status") != "connected" or not credentials:
                raise ChatGPTAuthError("not_connected", "Sign in with ChatGPT to use your subscription.", 401)
            if (not self._record.get("pending_refresh") and credentials["expires_at"] > self._clock() + 180
                    and (not force_refresh or (rejected_token is not None and credentials["access_token"] != rejected_token))):
                return credentials["access_token"]
            try:
                rotation = self._record.get("pending_refresh")
                if rotation is None:
                    config = await self._configuration()
                    data = await self._request("POST", config["token_endpoint"], data={"grant_type": "refresh_token",
                                               "client_id": self._record["client_id"], "refresh_token": credentials["refresh_token"], "resource": RESOURCE})
                    fields = self._token_fields(data, self._record["scopes"])
                    rotation = {**fields, "received_at": self._clock()}
                    if "id_token" in data:
                        rotation["id_token"] = data["id_token"]
                    # A grant may rotate before JWKS retrieval succeeds. Persist it
                    # first, and resume verification rather than consume it again.
                    checkpoint = {**self._record, "pending_refresh": rotation}
                    try:
                        await self._save(checkpoint)
                    except ChatGPTAuthError:
                        # Keep the consumed grant in memory if durable storage is
                        # temporarily unavailable. Never resend its old token.
                        self._record = checkpoint
                        self._record_needs_save = True
                        raise
                identity = {}
                if "id_token" in rotation:
                    identity = await self._verify_identity(rotation["id_token"], self._record["client_id"], received_at=rotation["received_at"])
                    if identity["subject"] != self._record["subject"]:
                        raise ChatGPTAuthError("account_mismatch", "The refreshed ChatGPT account did not match. Sign in again.", 401)
                record = {key: value for key, value in self._record.items() if key != "pending_refresh"}
                await self._save({**record, **identity, "credentials": rotation["credentials"], "scopes": rotation["scopes"], "status": "connected"})
                return self._record["credentials"]["access_token"]
            except ChatGPTAuthError as error:
                if error.code in _TERMINAL_ERRORS | {"invalid_id_token", "account_mismatch", "missing_scope", "invalid_token_response"}:
                    await self._disconnect_locked(retire_client=error.code in {"invalid_client", "unauthorized_client"})
                raise

    @_owned_operation
    async def async_models(self) -> list[dict[str, str]]:
        token = await self.async_access_token()
        data = await self._request("GET", f"{RESOURCE}/models", token=token)
        # SIWC's account catalog differs from API-key catalogs. Only entries
        # marked for listing may appear in the subscription model picker.
        subscription_catalog = "models" in data
        catalog = data.get("models" if subscription_catalog else "data")
        if not isinstance(catalog, list):
            raise ChatGPTAuthError("invalid_response", "ChatGPT returned an invalid model list.", 502)
        models = []
        seen: set[str] = set()
        for model in catalog:
            if not isinstance(model, dict):
                continue
            if subscription_catalog and model.get("visibility") != "list":
                continue
            if not subscription_catalog and model.get("visibility", "list") != "list":
                continue
            model_id = model.get("slug" if subscription_catalog else "id")
            if not isinstance(model_id, str) or not MODEL_ID_PATTERN.fullmatch(model_id) or model_id in seen:
                continue
            display_name = model.get("display_name" if subscription_catalog else "name")
            if (not isinstance(display_name, str) or not display_name.strip() or len(display_name) > 256
                    or any(ord(character) < 32 or ord(character) == 127 for character in display_name)):
                display_name = model_id
            seen.add(model_id)
            models.append({"id": model_id, "name": display_name.strip()})
        return models

    @_owned_operation
    async def async_logout(self) -> dict[str, Any]:
        self._pending = None
        async with self._lock:
            self._ensure_active()
            await self._load_locked()
            self._pending = None
            rotation = self._record.get("pending_refresh", {})
            credentials = rotation.get("credentials", self._record.get("credentials", {}))
            warning = REMOTE_DISCONNECTION_WARNING if self._record.get("remote_disconnection_pending") is True else None
            try:
                if credentials.get("refresh_token"):
                    config = await self._configuration()
                    endpoint = config.get("revocation_endpoint")
                    if not endpoint:
                        raise ChatGPTAuthError("revocation_failed", "Remote disconnection could not be confirmed.")
                    await self._request("POST", endpoint, data={"token": credentials["refresh_token"],
                                        "token_type_hint": "refresh_token", "client_id": self._record["client_id"]}, empty_ok=True)
                    warning = None
            except ChatGPTAuthError:
                warning = REMOTE_DISCONNECTION_WARNING
            finally:
                record = {key: self._record[key] for key in ("host_id", "client_id") if key in self._record}
                disconnected = {**record, "status": "disconnected", **({"remote_disconnection_pending": True} if warning else {})}
                try:
                    await self._save(disconnected)
                except ChatGPTAuthError:
                    # Logout has retired this session, even if its durable
                    # tombstone failed. Never restore or hand off its old grant.
                    self._record = disconnected
                    self._record_needs_save = True
                    raise
            result = self.status()
            if warning:
                result["warning"] = warning
            return result

    async def async_revoke_for_removal(self) -> dict[str, Any]:
        """Revoke the newest grant after unload, without writing a deleted store."""
        self._closed = True
        self._pending = None
        async with self._lock:
            record = self._record if self._loaded or self._record_needs_save else await self._store.async_load()
            if not record:
                return {}
            credentials = record.get("pending_refresh", {}).get("credentials", record.get("credentials", {}))
            warning = REMOTE_DISCONNECTION_WARNING if record.get("remote_disconnection_pending") else None
            if credentials.get("refresh_token"):
                try:
                    config = await self._configuration()
                    endpoint = config.get("revocation_endpoint")
                    if not endpoint:
                        return {"warning": REMOTE_DISCONNECTION_WARNING}
                    await self._request("POST", endpoint, data={"token": credentials["refresh_token"],
                                        "token_type_hint": "refresh_token", "client_id": record["client_id"]}, empty_ok=True)
                    warning = None
                except ChatGPTAuthError:
                    warning = REMOTE_DISCONNECTION_WARNING
            return {"warning": warning} if warning else {}

    async def async_shutdown(self) -> None:
        # Fence before the first await. Existing operations own their provider
        # and storage work until it settles, including a consumed refresh grant.
        self._closed = True
        self._pending = None
        operations = tuple(self._operations)
        cancelled = False
        if operations:
            drain = asyncio.gather(*operations, return_exceptions=True)
            while not drain.done():
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:
                    # Unload cancellation must not release a replacement while
                    # the old manager still owns a rotating grant or store write.
                    cancelled = True
        if self._record_needs_save:
            flush = asyncio.create_task(self._flush_dirty_record())
            self._operations.add(flush)
            flush.add_done_callback(self._operation_finished)
            while not flush.done():
                try:
                    await asyncio.shield(flush)
                except asyncio.CancelledError:
                    cancelled = True
            flush.result()
        self._pending = None
        if cancelled:
            raise asyncio.CancelledError

    async def _flush_dirty_record(self) -> None:
        async with self._lock:
            if self._record_needs_save:
                # One attempt only. On failure, unload retains this manager so
                # replacement setup cannot load a consumed credential record.
                await self._save(self._record)


def _network_failure_category(error: BaseException) -> str:
    """Return a fixed transport category without formatting the exception."""
    if isinstance(error, asyncio.TimeoutError):
        return "timeout"
    if isinstance(error, (aiohttp.ClientSSLError, aiohttp.ClientConnectorCertificateError)):
        return "tls"
    if isinstance(error, getattr(aiohttp, "ClientConnectorDNSError", ())):
        return "dns"
    if isinstance(error, aiohttp.ClientPayloadError):
        return "response_body"
    if isinstance(error, aiohttp.ClientConnectionError):
        return "connection"
    if isinstance(error, aiohttp.ClientError):
        return "http_transport"
    return "socket"


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_RESPONSE_BYTES


def _valid_token(value: Any) -> bool:
    return _nonempty_string(value) and all(33 <= ord(character) <= 126 for character in value)


def _valid_client(value: Any) -> bool:
    return isinstance(value, str) and bool(CLIENT_ID_PATTERN.fullmatch(value)) and value != "dynamic_agent_client"


def _valid_host_id(value: str) -> bool:
    try:
        return value.startswith("urn:uuid:") and str(uuid.UUID(value[9:])) == value[9:]
    except (ValueError, AttributeError):
        return False


def _trusted_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and parsed.netloc == "auth.openai.com" and not parsed.fragment
    except ValueError:
        return False


def _valid_stored_credentials(value: Any) -> bool:
    return (isinstance(value, dict) and _valid_token(value.get("access_token"))
            and _valid_token(value.get("refresh_token")) and isinstance(value.get("expires_at"), (float, int))
            and not isinstance(value.get("expires_at"), bool) and math.isfinite(value["expires_at"]))


def _valid_scopes(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(scope, str) for scope in value) and REQUIRED_SCOPES.issubset(value)


def _valid_rotation(value: Any) -> bool:
    return (isinstance(value, dict) and _valid_stored_credentials(value.get("credentials"))
            and _valid_scopes(value.get("scopes"))
            and isinstance(value.get("received_at"), (int, float)) and not isinstance(value.get("received_at"), bool)
            and math.isfinite(value["received_at"]) and ("id_token" not in value or _nonempty_string(value["id_token"])))


class _PrivateCredentialStore:
    """Confirm HA's atomic save succeeded; its Store logs write errors internally."""

    def __init__(self, hass: Any, store: Any) -> None:
        self._hass = hass
        self._store = store

    async def async_load(self) -> dict[str, Any] | None:
        record = await self._store.async_load()
        if record is not None:
            await self._hass.async_add_executor_job(self._verify_saved, record)
        return record

    async def async_save(self, record: dict[str, Any]) -> None:
        await self._store.async_save(record)
        await self._hass.async_add_executor_job(self._verify_saved, record)

    def _verify_saved(self, record: dict[str, Any]) -> None:
        # Do not expose disk content or credentials in exceptions. Read through
        # the open descriptor so permissions and content describe the same file.
        with open(self._store.path, "rb") as saved:
            info = os.fstat(saved.fileno())
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_uid != os.geteuid()):
                raise OSError("Credential storage permissions are not private")
            body = saved.read(MAX_RESPONSE_BYTES * 4 + 1)
        if len(body) > MAX_RESPONSE_BYTES * 4:
            raise OSError("Credential storage exceeds its limit")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            raise OSError("Credential storage could not be verified") from None
        if not isinstance(payload, dict) or payload.get("data") != record:
            raise OSError("Credential storage could not be verified")


def get_chatgpt_auth(hass: Any, entry_id: str) -> ChatGPTAuthManager:
    """Get the entry manager, loading Home Assistant integrations only on demand."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.storage import Store

    entry_data = hass.data["power_sync"][entry_id]
    manager = entry_data.get("_optimization_chatgpt_auth")
    if manager is None:
        manager = hass.data.get(CHATGPT_AUTH_RETAINED_KEY, {}).pop(entry_id, None)
        if manager is not None:
            manager._closed = False
            entry_data["_optimization_chatgpt_auth"] = manager
    if manager is None:
        # HA's private Store uses atomic writes with owner-only permissions.
        store = Store(hass, 1, f"power_sync.chatgpt_auth.{entry_id}", private=True, atomic_writes=True)
        manager = ChatGPTAuthManager(async_get_clientsession(hass), _PrivateCredentialStore(hass, store))
        entry_data["_optimization_chatgpt_auth"] = manager
    return manager
