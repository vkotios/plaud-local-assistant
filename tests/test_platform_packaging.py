"""Phase 6 packaging invariants: matrix docs, compose core profile, doctor BLE."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_platform_matrix_matches_executive_report_rows():
    text = (ROOT / "docs/platform-matrix.md").read_text(encoding="utf-8")
    assert "Fedora/Linux" in text
    assert "Yes (native/Docker)" in text
    assert "Host BlueZ" in text
    assert "Not supported" in text and "Docker" in text
    assert "Windows 11" in text
    assert "WSL2" in text or "WSL" in text
    assert "No native localplaud path" in text
    assert "macOS" in text
    assert "Strongest upstream BLE evidence" in text
    assert "inference-gateway-manager" in text or "IGM" in text


def test_compose_core_profile_sets_runtime_and_documents_ble():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["core", "cpu"]' in compose
    assert "LOCALPLAUD_RUNTIME: docker" in compose
    assert "do NOT support BLE" in compose
    assert 'profiles: ["core", "cpu", "gpu", "mac"]' in compose
    # AMD guidance: do not steer Strix Halo to CUDA gpu profile by default
    assert "AMD" in compose
    assert "IGM" in compose


def test_fedora_windows_ble_host_docs_exist():
    for rel in (
        "docs/deploy-fedora.md",
        "docs/windows.md",
        "docs/ble-host.md",
        "docs/platform-matrix.md",
        "deploy/caddy/Caddyfile.host-native",
        "scripts/packaging/build-plaud-bridge.sh",
        "scripts/deploy/bootstrap-fedora.sh",
    ):
        assert (ROOT / rel).is_file(), rel


def test_bridge_packaging_script_skips_without_vendor_crate():
    import subprocess

    script = ROOT / "scripts/packaging/build-plaud-bridge.sh"
    result = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "skipped: plaud-bridge crate not present" in result.stdout
    # Ensure we did not invent a vendor tree as a side effect
    assert not (ROOT / "vendor/openplod-ble/plaud-bridge/Cargo.toml").exists()


def test_doctor_reports_runtime_and_ble_packaging(monkeypatch, tmp_path):
    import localplaud.db.session as db_session
    from localplaud.config import get_settings
    from localplaud.db.session import init_db

    monkeypatch.setenv("LOCALPLAUD_STORE__DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setenv("LOCALPLAUD_RUNTIME", "docker")
    monkeypatch.setenv("LOCALPLAUD_BLE__ENABLED", "true")
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setattr(db_session, "_Session", None)
    get_settings(reload=True)
    init_db()

    from localplaud.cli import app

    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.stdout
    assert "runtime" in result.stdout
    assert "docker" in result.stdout.lower()
    assert "ble packaging" in result.stdout.lower()
    assert "unsupported" in result.stdout.lower() or "not supported" in result.stdout.lower()


def test_ble_packaging_status_container_ok_when_disabled(monkeypatch):
    from localplaud.platform_runtime import ble_packaging_status

    monkeypatch.setenv("LOCALPLAUD_RUNTIME", "docker")
    monkeypatch.delenv("LOCALPLAUD_BLE__ENABLED", raising=False)
    status = ble_packaging_status()
    assert status["ok"] is True
    assert status["in_container"] is True
    assert status["requested"] is False
