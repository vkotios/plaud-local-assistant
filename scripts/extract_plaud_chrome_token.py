#!/usr/bin/env python3
"""Extract Plaud web session from Chrome cookies and refresh on the right region API.

Writes ~/.config/plaud-local/tokenstr.txt (mode 0600). Never prints token values.

macOS Chrome only. Requires Keychain access to "Chrome Safe Storage" once.
Does not bypass Plaud Partner SDK authorization — gen-key may still reject a
consumer web JWT (ACCESS_TOKEN_INVALID), especially for EU accounts where no
platform-euc1 Partner host is published.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from hashlib import pbkdf2_hmac
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
OUT = Path.home() / ".config" / "plaud-local" / "tokenstr.txt"
COOKIE_DB = (
    Path.home()
    / "Library/Application Support/Google/Chrome/Default/Cookies"
)


def _chrome_key() -> bytes:
    password = subprocess.check_output(
        [
            "security",
            "find-generic-password",
            "-w",
            "-s",
            "Chrome Safe Storage",
            "-a",
            "Chrome",
        ],
        stderr=subprocess.DEVNULL,
    ).decode().strip()
    return pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, dklen=16)


def _decrypt(key: bytes, encrypted: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not (encrypted.startswith(b"v10") or encrypted.startswith(b"v11")):
        raise ValueError("unsupported Chrome cookie cipher prefix")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = decryptor.update(encrypted[3:]) + decryptor.finalize()
    pad = plain[-1]
    if isinstance(pad, int) and 1 <= pad <= 16:
        plain = plain[:-pad]
    # Chrome prefixes a 32-byte digest before the cookie value.
    return plain[32:].decode("utf-8")


def _load_plaud_cookies() -> dict[str, str]:
    if not COOKIE_DB.is_file():
        raise FileNotFoundError(f"Chrome cookie DB not found: {COOKIE_DB}")
    key = _chrome_key()
    tmp = Path(tempfile.mkdtemp(prefix="plaud-chrome-cookies-"))
    try:
        shutil.copy2(COOKIE_DB, tmp / "Cookies")
        con = sqlite3.connect(str(tmp / "Cookies"))
        out: dict[str, str] = {}
        for name, blob in con.execute(
            "SELECT name, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%plaud%' AND name IN ('pld_ut', 'pld_urt')"
        ):
            try:
                value = _decrypt(key, blob)
            except Exception as exc:  # noqa: BLE001
                print(f"decrypt_failed name={name} err={type(exc).__name__}", file=sys.stderr)
                continue
            if value.startswith("eyJ"):
                out[name] = value
                print(f"cookie_ok name={name} len={len(value)}")
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _post_json(url: str, headers: dict[str, str], body: bytes = b"{}") -> tuple[int, dict]:
    request = Request(url, data=body, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:200]}
        return exc.code, payload if isinstance(payload, dict) else {"raw": raw[:200]}


def refresh_access_token(urt: str) -> tuple[str, str, str]:
    """Return (api_base, access_token, refresh_token)."""
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://web.plaud.ai",
        "Referer": "https://web.plaud.ai/",
        "Cookie": f"pld_urt={urt}",
        "Authorization": f"Bearer {urt}",
    }
    status, payload = _post_json("https://api.plaud.ai/auth/refresh-user-token", headers)
    api = "https://api.plaud.ai"
    if payload.get("status") == -302:
        domains = (payload.get("data") or {}).get("domains") or {}
        api = domains.get("api") or api
        print(f"region_redirect api={api}")
        status, payload = _post_json(f"{api}/auth/refresh-user-token", headers)
    if status != 200 or payload.get("status") not in (0, "0", None) or not payload.get(
        "access_token"
    ):
        msg = payload.get("msg") or payload.get("detail") or payload.get("raw") or "refresh failed"
        raise RuntimeError(f"refresh_failed http={status} msg={msg}")
    access = str(payload["access_token"])
    refresh = str(payload.get("refresh_token") or urt)
    print(f"refresh_ok api={api} access_len={len(access)}")
    return api, access, refresh


def probe_partner(access: str) -> None:
    for host in ("platform-us.plaud.ai", "platform-jp.plaud.ai"):
        status, payload = _post_json(
            f"https://{host}/developer/api/open/partner/sdk/gen-key",
            {
                "User-Agent": UA,
                "Accept": "application/json",
                "Authorization": f"Bearer {access}",
            },
            body=b"",
        )
        detail = payload.get("detail") or payload.get("msg") or payload.get("raw") or ""
        print(f"partner_probe host={host} http={status} detail={detail}")


def main() -> int:
    cookies = _load_plaud_cookies()
    urt = cookies.get("pld_urt")
    if not urt:
        print(
            "missing_pld_urt: open https://web.plaud.ai in Chrome, sign in, reload once, retry",
            file=sys.stderr,
        )
        return 2
    try:
        _api, access, _refresh = refresh_access_token(urt)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        print(
            "hint: reload https://web.plaud.ai in Chrome so cookies rotate, then retry",
            file=sys.stderr,
        )
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(access + "\n", encoding="utf-8")
    OUT.chmod(0o600)
    print(f"wrote path={OUT} bytes={OUT.stat().st_size}")
    probe_partner(access)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
