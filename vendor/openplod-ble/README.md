# OpenPlod BLE bridge (vendored)

Isolated radio helper for Plaud-local Phase 4. Source adapted from
[OpenPlod](https://github.com/RemiPelloux/OpenPlod) `src-tauri/plaud-bridge`
(MIT). Build on the host that has the Bluetooth adapter:

```bash
cd vendor/openplod-ble/plaud-bridge
cargo build --release
# binary: target/release/plaud-bridge  (or .exe on Windows)
```

Then either put it on `PATH`, copy to `./bin/plaud-bridge`, or set
`LOCALPLAUD_BLE__BRIDGE_PATH`.

Requires: Rust toolchain, platform BLE stack (WinRT / BlueZ / CoreBluetooth).
ffmpeg/ffprobe recommended for post-download convert.

See `docs/ble.md`.
