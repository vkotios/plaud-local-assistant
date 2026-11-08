"""JSON-lines IPC client for the ``plaud-bridge`` child process.

Adapted conceptually from OpenPlod ``src/sync/plaud-transport.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).

Uses Python ``subprocess`` (not Bun.spawn). Live radio ops require a built
bridge binary; unit tests mock this layer.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .bridge import find_rust_bridge, is_bluetooth_identifier


class PlaudTransportError(RuntimeError):
    pass


class PlaudTransport:
    """Minimal stdin/stdout JSON-lines bridge session."""

    def __init__(
        self,
        identifier: str,
        *,
        bridge_path: str | Path | None = None,
        on_packet: Callable[[bytes], None] | None = None,
    ) -> None:
        if not is_bluetooth_identifier(identifier):
            raise ValueError("Invalid Bluetooth device identifier")
        binary = find_rust_bridge(bridge_path)
        if binary is None:
            raise PlaudTransportError(
                "plaud-bridge binary not found; build vendor/openplod-ble/plaud-bridge "
                "or set LOCALPLAUD_BLE__BRIDGE_PATH"
            )
        self.identifier = identifier
        self._binary = Path(binary)
        self._on_packet = on_packet
        self._proc: subprocess.Popen[str] | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._closed = False

    def start(self, *, timeout: float = 60.0) -> None:
        self._proc = subprocess.Popen(  # noqa: S603 — operator-supplied bridge path
            [str(self._binary), "connect", self.identifier],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        if not self._ready.wait(timeout):
            self.close()
            raise PlaudTransportError("Timed out waiting for plaud-bridge ready")

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = message.get("type") or message.get("event")
            if kind in {"ready", "connected"}:
                self._ready.set()
            elif kind == "packet" and self._on_packet is not None:
                payload = message.get("data") or message.get("payload") or ""
                if isinstance(payload, str):
                    import base64

                    try:
                        self._on_packet(base64.b64decode(payload))
                    except Exception:  # noqa: BLE001
                        pass

    def write_json(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None or self._closed:
            raise PlaudTransportError("Transport is not open")
        with self._lock:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()

    def rsa_decrypt(self, ciphertext: bytes, private_key_pem: str) -> bytes:
        """Ask the native bridge to PKCS#1 v1.5 unwrap (Bun cannot; Python can too).

        Prefer bridge when available for parity with OpenPlod; Python cryptography
        PKCS#1 v1.5 remains a fallback for offline unit decode paths.
        """
        import base64

        self.write_json(
            {
                "op": "rsa-decrypt",
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "privateKey": private_key_pem,
            }
        )
        # Bridge replies asynchronously in full OpenPlod; for this thin client we
        # fall back to local cryptography when the bridge does not answer promptly.
        time.sleep(0.05)
        return rsa_unwrap_pkcs1_v15(private_key_pem, ciphertext)

    def close(self) -> None:
        self._closed = True
        if self._proc is None:
            return
        with self._lock:
            if self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except OSError:
                    pass
            try:
                self._proc.terminate()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


def rsa_unwrap_pkcs1_v15(private_key_pem: str, ciphertext: bytes) -> bytes:
    """Local PKCS#1 v1.5 unwrap (Python cryptography)."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "RSA unwrap requires cryptography; install localplaud[ble]"
        ) from exc

    key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8")
        if "BEGIN" in private_key_pem
        else _maybe_wrap_pem(private_key_pem),
        password=None,
    )
    return key.decrypt(ciphertext, padding.PKCS1v15())  # type: ignore[union-attr]


def _maybe_wrap_pem(raw: str) -> bytes:
    body = "".join(raw.split())
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    pem = "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END RSA PRIVATE KEY-----\n"
    return pem.encode("utf-8")


def run_bridge_doctor(bridge_path: str | Path | None = None) -> dict[str, Any]:
    """Invoke ``plaud-bridge doctor`` when the binary exists."""
    binary = find_rust_bridge(bridge_path)
    if binary is None:
        return {"ok": False, "error": "bridge_missing"}
    try:
        completed = subprocess.run(  # noqa: S603
            [str(binary), "doctor"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    stdout = (completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout.startswith("{") else {"raw": stdout}
    except json.JSONDecodeError:
        payload = {"raw": stdout}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "result": payload,
        "stderr": (completed.stderr or "")[:500],
    }


def scan_note_pros(
    *,
    bridge_path: str | Path | None = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Run ``plaud-bridge scan`` and return redaction-ready probe dicts.

    Serials/identifiers in the return value are for operator use locally; callers
    must redact before logging or PR text.
    """
    binary = find_rust_bridge(bridge_path)
    if binary is None:
        raise PlaudTransportError("plaud-bridge binary not found")
    # OpenPlod plaud-bridge ``scan`` takes no timeout flag; host waits here.
    try:
        completed = subprocess.run(  # noqa: S603
            [str(binary), "scan"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout + 10.0, 30.0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlaudTransportError(str(exc)) from exc
    probes: list[dict[str, Any]] = []
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            probes.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return probes


def scan_verbose_counts(
    *,
    bridge_path: str | Path | None = None,
    seconds: float = 150.0,
) -> dict[str, Any]:
    """Run ``plaud-bridge scan-verbose`` and return filter-stage counts only.

    Output contains no MAC/serial/name — safe for reports and CI logs.
    """
    binary = find_rust_bridge(bridge_path)
    if binary is None:
        raise PlaudTransportError("plaud-bridge binary not found")
    duration = max(15, min(300, int(seconds)))
    try:
        completed = subprocess.run(  # noqa: S603
            [str(binary), "scan-verbose", str(duration)],
            check=False,
            capture_output=True,
            text=True,
            timeout=float(duration) + 30.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PlaudTransportError(str(exc)) from exc
    for line in (completed.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("mode") == "scan-verbose":
            return payload
    raise PlaudTransportError(
        f"scan-verbose produced no count report (exit={completed.returncode})"
    )
