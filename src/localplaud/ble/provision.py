"""Plaud Note Pro identity provisioning (paste-token path).

Adapted from OpenPlod ``src/sync/plaud-provision.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).

Primary UX: paste a consumer Plaud sign-in JWT (``tokenstr`` from web.plaud.ai).
Partner portal ``client_id`` / ``client_secret`` is intentionally not required.
Live acceptance of a fresh consumer JWT by Plaud Partner SDK endpoints remains
unverified upstream — treat failures honestly.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge import is_bluetooth_identifier
from .identity import PlaudDeviceIdentity, write_stored_identity

PLAUD_DOMAINS = ("platform-us.plaud.ai", "platform-jp.plaud.ai")
DEFAULT_PLAUD_DOMAIN = "platform-us.plaud.ai"

BINDING_TOKEN_PATTERN = re.compile(r"^[\x21-\x7e]{1,64}$")
PLAUD_SERIAL_PATTERN = re.compile(r"^[0-9A-F]{16}$")

Fetcher = Callable[[str, dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class PlaudAccessTokenClaims:
    sub: str
    user_id: str
    client_id: str
    expires_at: int  # epoch ms, or 0


def is_plaud_domain(value: str) -> bool:
    return value in PLAUD_DOMAINS


def normalize_access_token(raw: str) -> str:
    """Accept bare JWT, quotes, Bearer header, or browser-storage JSON blob."""
    token = (raw or "").strip()
    if token.startswith("{"):
        try:
            parsed = json.loads(token)
            if isinstance(parsed, dict):
                token = str(
                    parsed.get("tokenstr")
                    or parsed.get("access_token")
                    or parsed.get("token")
                    or ""
                ).strip()
        except json.JSONDecodeError:
            pass
    if len(token) >= 2 and (
        (token.startswith('"') and token.endswith('"'))
        or (token.startswith("'") and token.endswith("'"))
    ):
        token = token[1:-1].strip()
    if re.match(r"^bearer\s", token, flags=re.IGNORECASE):
        token = re.sub(r"^bearer\s+", "", token, flags=re.IGNORECASE).strip()
    return token


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def parse_access_token(raw: str) -> PlaudAccessTokenClaims:
    token = normalize_access_token(raw)
    parts = token.split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise ValueError("That does not look like a Plaud sign-in token.")
    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The Plaud sign-in token could not be read.") from exc
    if not isinstance(payload, dict):
        raise ValueError("The Plaud sign-in token could not be read.")
    sub = payload.get("sub") if isinstance(payload.get("sub"), str) else ""
    if not BINDING_TOKEN_PATTERN.match(sub):
        raise ValueError(
            "The Plaud sign-in token is missing a usable device binding token."
        )
    raw_expiry = float(payload.get("exp") or 0)
    user_id = payload.get("user_id")
    client_id = payload.get("client_id")
    return PlaudAccessTokenClaims(
        sub=sub,
        user_id=user_id if isinstance(user_id, str) and user_id else sub,
        client_id=client_id if isinstance(client_id, str) else "",
        expires_at=int(raw_expiry * 1000) if raw_expiry > 0 else 0,
    )


def device_type_for_serial(serial: str) -> str:
    if not PLAUD_SERIAL_PATTERN.match(serial):
        raise ValueError("A 16-character Plaud serial number is required.")
    return {
        "880": "notepin",
        "881": "notepro",
        "882": "notepins",
        "883": "notepro",
    }.get(serial[:3], "note")


def _describe_plaud_error(status: int, detail: str) -> str:
    if detail == "ACCESS_TOKEN_INVALID":
        return "Plaud rejected the sign-in token. Sign in again and paste a fresh token."
    if detail == "CLIENT_USER_NOT_FOUND":
        return (
            "This Plaud account is not enabled for device authorization in that region."
        )
    if detail == "TOKEN_EXPIRED":
        return "The Plaud sign-in token has expired. Sign in again and paste a fresh token."
    return f"Plaud authorization failed (HTTP {status})."


def _default_fetcher(url: str, init: dict[str, Any]) -> Mapping[str, Any]:
    headers = dict(init.get("headers") or {})
    # Cloudflare on platform-*.plaud.ai returns opaque 1010 without a UA.
    headers.setdefault(
        "User-Agent",
        "localplaud-ble/0.1 (+https://github.com/vkotios/plaud-local-assistant)",
    )
    headers.setdefault("Accept", "application/json")
    body = init.get("body")
    data = None if body is None else (body if isinstance(body, bytes) else str(body).encode("utf-8"))
    request = Request(url, data=data, headers=headers, method=init.get("method", "POST"))
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 — fixed Plaud HTTPS hosts only
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Plaud returned an unreadable authorization response.")
            return payload
    except HTTPError as exc:
        detail = ""
        raw = b""
        try:
            raw = exc.read()
            err_body = json.loads(raw.decode("utf-8"))
            if isinstance(err_body, dict) and isinstance(err_body.get("detail"), str):
                detail = err_body["detail"]
        except Exception:  # noqa: BLE001
            # Cloudflare interstitial (e.g. "error code: 1010") — keep empty detail.
            detail = ""
        raise ValueError(_describe_plaud_error(exc.code, detail)) from None
    except URLError as exc:
        raise ValueError("Plaud could not be reached to authorize this recorder.") from exc


class PlaudIdentityProvisioner:
    """Mints key material + serial signature via Partner SDK endpoints."""

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self._fetcher = fetcher or _default_fetcher

    def _post(
        self,
        path: str,
        token: str,
        domain: str,
        body: Any | None = None,
    ) -> Mapping[str, Any]:
        if not is_plaud_domain(domain):
            raise ValueError("Unsupported Plaud region.")
        headers = {"Authorization": f"Bearer {token}"}
        init: dict[str, Any] = {"method": "POST", "headers": headers, "body": None}
        if body is not None:
            headers["Content-Type"] = "application/json"
            init["body"] = json.dumps(body)
        return self._fetcher(f"https://{domain}{path}", init)

    def generate_key_pair(
        self, token: str, domain: str = DEFAULT_PLAUD_DOMAIN
    ) -> dict[str, str]:
        result = self._post(
            "/developer/api/open/partner/sdk/gen-key", token, domain
        )
        public_key = result.get("public_key") if isinstance(result.get("public_key"), str) else ""
        private_key = (
            result.get("private_key") if isinstance(result.get("private_key"), str) else ""
        )
        if not public_key or not private_key:
            raise ValueError("Plaud returned no recorder key material.")
        return {"publicKey": public_key, "privateKey": private_key}

    def sign_serial(
        self,
        token: str,
        serial: str,
        domain: str = DEFAULT_PLAUD_DOMAIN,
        device_type: str | None = None,
    ) -> str:
        dtype = device_type or device_type_for_serial(serial)
        result = self._post(
            "/developer/api/open/partner/sdk/sn-sign",
            token,
            domain,
            {"type": dtype, "sn": serial},
        )
        signature = result.get("signature") if isinstance(result.get("signature"), str) else ""
        if not signature:
            raise ValueError("Plaud returned no recorder signature.")
        return signature

    def provision(
        self,
        *,
        token: str,
        serial: str,
        identifier: str,
        domain: str = DEFAULT_PLAUD_DOMAIN,
    ) -> PlaudDeviceIdentity:
        if not PLAUD_SERIAL_PATTERN.match(serial):
            raise ValueError("A 16-character Plaud serial number is required.")
        if not is_bluetooth_identifier(identifier):
            raise ValueError("A Bluetooth address for the recorder is required.")
        claims = parse_access_token(token)
        normalized = normalize_access_token(token)
        device_type = device_type_for_serial(serial)
        keys = self.generate_key_pair(normalized, domain)
        signature = self.sign_serial(normalized, serial, domain, device_type)
        return {
            "identifier": identifier,
            "serial": serial,
            "bindingToken": claims.sub,
            "publicKey": keys["publicKey"],
            "privateKey": keys["privateKey"],
            "signature": signature,
            "deviceType": device_type,
        }


def provision_device(
    *,
    token: str,
    serial: str,
    identifier: str,
    domain: str = DEFAULT_PLAUD_DOMAIN,
    identity_path: str | None = None,
    provisioner: PlaudIdentityProvisioner | None = None,
    write: bool = True,
) -> PlaudDeviceIdentity:
    """Provision identity from a pasted sign-in token and optionally persist it."""
    worker = provisioner or PlaudIdentityProvisioner()
    identity = worker.provision(
        token=token, serial=serial, identifier=identifier, domain=domain
    )
    if write:
        write_stored_identity(identity, identity_path)
    return identity
