//! Cross-platform Bluetooth Low Energy bridge for Plaud Note Pro recorders.
//!
//! The desktop vault talks to a Plaud recorder over a small JSON-lines protocol
//! on stdin/stdout.  This binary implements that protocol on top of `btleplug`
//! so the vault can talk to a recorder on Linux (BlueZ), Windows (WinRT) and
//! macOS (CoreBluetooth) with the same code.
//!
//! Two sub-commands are supported:
//!
//! * `plaud-bridge scan` — scan for an advertising Plaud recorder and print a
//!   single `DesktopPlaudProbe` JSON object, then exit.  This mirrors
//!   `scripts/scan-plaud.swift`.
//! * `plaud-bridge connect <identifier>` — connect to a recorder and speak the
//!   JSON-lines bridge protocol until stdin closes or the session ends.  This
//!   mirrors `scripts/plaud-bridge.swift`.
//! * `plaud-bridge doctor` — report the host Bluetooth stack (backend, adapter,
//!   power state) as a single JSON object without scanning.  The vault uses it
//!   to autodetect what this machine can do before offering a transfer.
//!
//! `<identifier>` may be a Bluetooth address (`AA:BB:CC:DD:EE:FF`) or the
//! CoreBluetooth UUID used by the macOS identity file.  When it does not match
//! an address seen during the scan the bridge falls back to the first
//! recorder-like peripheral it can see, which keeps a single identity file
//! portable across operating systems.

use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::time::{Duration, Instant};

use base64::engine::general_purpose::STANDARD as BASE64;
use base64::Engine as _;
use btleplug::api::{
    Central, CentralState, CharPropFlags, Manager as _, Peripheral as _, PeripheralProperties,
    ScanFilter, WriteType,
};
use btleplug::platform::{Adapter, Manager, Peripheral};
use futures::stream::StreamExt;
use rsa::pkcs1::DecodeRsaPrivateKey;
use rsa::pkcs8::DecodePrivateKey;
use rsa::{Pkcs1v15Encrypt, RsaPrivateKey};
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::mpsc;
use uuid::Uuid;

/// Plaud GATT service exposed by the recorder command channel.
const SERVICE_UUID: Uuid = Uuid::from_u128(0x00001910_0000_1000_8000_00805f9b34fb);
/// Notify characteristic carrying recorder responses.
const NOTIFY_UUID: Uuid = Uuid::from_u128(0x00002bb0_0000_1000_8000_00805f9b34fb);
/// Write characteristic carrying vault commands.
const WRITE_UUID: Uuid = Uuid::from_u128(0x00002bb1_0000_1000_8000_00805f9b34fb);
/// Advertised name fragment used to recognise a recorder.
const NAME_HINT: &str = "plaud";

const DISCOVERY_TIMEOUT: Duration = Duration::from_secs(35);
/// A cold BlueZ cache makes the first connect-and-discover of an unbonded
/// recorder far slower than a warm one, so the probe allows the same budget the
/// connect path does.  Anything tighter reports a healthy recorder as
/// unreachable on the first scan after boot.
const VERIFY_TIMEOUT: Duration = Duration::from_secs(30);
const SESSION_DEADLINE: Duration = Duration::from_secs(600);
const SCAN_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_REQUEST_BYTES: usize = 16 * 1024;

type Emitter = mpsc::UnboundedSender<Value>;

fn emit(tx: &Emitter, value: Value) {
    let _ = tx.send(value);
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let mode = args.get(1).map(String::as_str).unwrap_or("");
    let runtime = match tokio::runtime::Builder::new_multi_thread().enable_all().build() {
        Ok(runtime) => runtime,
        Err(error) => {
            eprintln!("plaud-bridge: could not start runtime: {error}");
            std::process::exit(1);
        }
    };
    let result = match mode {
        "doctor" => runtime.block_on(run_doctor()),
        "scan" => runtime.block_on(run_scan()),
        "scan-verbose" => {
            let seconds = args
                .get(2)
                .and_then(|value| value.parse::<u64>().ok())
                .unwrap_or(150)
                .clamp(15, 300);
            runtime.block_on(run_scan_verbose(Duration::from_secs(seconds)))
        }
        "connect" => {
            let identifier = args.get(2).cloned().unwrap_or_default();
            runtime.block_on(run_connect(identifier))
        }
        _ => {
            eprintln!("usage: plaud-bridge <doctor|scan|scan-verbose [seconds]|connect> [identifier]");
            std::process::exit(2);
        }
    };
    if let Err(error) = result {
        eprintln!("plaud-bridge: {error}");
        std::process::exit(1);
    }
}

async fn adapter() -> Result<Adapter, String> {
    let manager = Manager::new()
        .await
        .map_err(|error| format!("Bluetooth is unavailable: {error}"))?;
    let adapters = manager
        .adapters()
        .await
        .map_err(|error| format!("Bluetooth is unavailable: {error}"))?;
    adapters
        .into_iter()
        .next()
        .ok_or_else(|| "No Bluetooth adapter was found".to_string())
}

fn normalize_identifier(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_ascii_alphanumeric())
        .collect::<String>()
        .to_ascii_lowercase()
}

/// Why a peripheral matched the recorder filter (for verbose diagnostics only).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum PlaudMatch {
    Name,
    Service,
    Manufacturer,
}

/// WinRT often omits local name and incomplete service UUID lists while still
/// exposing manufacturer payloads (and sometimes service-data sections). Mac
/// CoreBluetooth `scan-plaud.swift` matches name only; OpenPlod's Rust bridge
/// matches name OR `0x1910` in `services`. We widen further for WinRT:
/// name OR service UUID in `services`/`service_data` OR Note Pro manufacturer
/// framing (projects 881/883).
fn classify_plaud(properties: &PeripheralProperties) -> Option<PlaudMatch> {
    let named = properties
        .local_name
        .as_deref()
        .map(|name| name.to_ascii_lowercase().contains(NAME_HINT))
        .unwrap_or(false);
    if named {
        return Some(PlaudMatch::Name);
    }
    if advertises_service_1910(properties) {
        return Some(PlaudMatch::Service);
    }
    if manufacturer_looks_like_note_pro(&properties.manufacturer_data) {
        return Some(PlaudMatch::Manufacturer);
    }
    None
}

fn advertises_service_1910(properties: &PeripheralProperties) -> bool {
    properties.services.contains(&SERVICE_UUID)
        || properties.service_data.contains_key(&SERVICE_UUID)
}

fn is_plaud(properties: &PeripheralProperties) -> bool {
    classify_plaud(properties).is_some()
}

/// Raw manufacturer map from btleplug (company id → payload without company bytes).
fn manufacturer_looks_like_note_pro(manufacturer_data: &HashMap<u16, Vec<u8>>) -> bool {
    for (company, payload) in manufacturer_data {
        // Path A: restore company id LE prefix (OpenPlod / btleplug framing).
        let mut framed = Vec::with_capacity(payload.len() + 2);
        framed.extend_from_slice(&company.to_le_bytes());
        framed.extend_from_slice(payload);
        if note_pro_framed_ad(&framed).is_some() {
            return true;
        }
        // Path B: some stacks already include company bytes in the payload.
        if note_pro_framed_ad(payload).is_some() {
            return true;
        }
        // Path C: looser project-id scan when TLV markers are shifted/truncated.
        if payload_mentions_note_pro_project(payload) || payload_mentions_note_pro_project(&framed) {
            return true;
        }
    }
    false
}

fn payload_mentions_note_pro_project(bytes: &[u8]) -> bool {
    if bytes.len() < 4 {
        return false;
    }
    // Look for project 881/883 as little-endian u16 in the first 8 bytes.
    let end = bytes.len().min(8).saturating_sub(1);
    for i in 0..end {
        let project = u16::from_le_bytes([bytes[i], bytes[i + 1]]);
        if project == 881 || project == 883 {
            return true;
        }
    }
    false
}

/// Returns `(project, protocol_version)` when framing matches Note Pro ads.
fn note_pro_framed_ad(bytes: &[u8]) -> Option<(u16, u16)> {
    if bytes.len() < 22 || bytes[2] != 2 || bytes[5] != 4 || bytes[10] != 8 {
        return None;
    }
    let project = u16::from_le_bytes([bytes[3], bytes[4]]);
    if project != 881 && project != 883 {
        return None;
    }
    let protocol_version = u16::from_le_bytes([bytes[20], bytes[21]]);
    Some((project, protocol_version))
}

/// Find a recorder, preferring an exact address match but falling back to the
/// first recorder-like peripheral so identities stay portable across platforms.
async fn find_peripheral(
    adapter: &Adapter,
    identifier: &str,
    timeout: Duration,
) -> Result<Option<Peripheral>, String> {
    adapter
        .start_scan(ScanFilter::default())
        .await
        .map_err(|error| format!("Bluetooth scan could not start: {error}"))?;
    let target = normalize_identifier(identifier);
    let deadline = Instant::now() + timeout;
    let mut fallback: Option<Peripheral> = None;
    let mut exact: Option<Peripheral> = None;
    'outer: loop {
        if Instant::now() >= deadline {
            break;
        }
        tokio::time::sleep(Duration::from_millis(400)).await;
        let peripherals = adapter
            .peripherals()
            .await
            .map_err(|error| format!("Bluetooth scan failed: {error}"))?;
        for peripheral in peripherals {
            if !target.is_empty()
                && normalize_identifier(&peripheral.address().to_string()) == target
            {
                exact = Some(peripheral);
                break 'outer;
            }
            if fallback.is_none() {
                if let Some(properties) = peripheral.properties().await.ok().flatten() {
                    if is_plaud(&properties) {
                        fallback = Some(peripheral);
                    }
                }
            }
        }
        if fallback.is_some() {
            break;
        }
    }
    let _ = adapter.stop_scan().await;
    Ok(exact.or(fallback))
}

/// The Bluetooth backend `btleplug` binds to on this target.  Reported so the
/// vault can name the host stack in diagnostics instead of guessing from the
/// operating system.
const fn backend() -> &'static str {
    if cfg!(target_os = "macos") {
        "corebluetooth"
    } else if cfg!(target_os = "windows") {
        "winrt"
    } else {
        "bluez"
    }
}

/// Report the host Bluetooth stack without scanning.  Always exits 0: an
/// unusable adapter is a diagnosis, not a crash, and the vault renders it.
async fn run_doctor() -> Result<(), String> {
    let report = match adapter().await {
        Err(error) => json!({
            "backend": backend(),
            "adapterAvailable": false,
            "poweredOn": false,
            "adapter": null,
            "detail": error,
        }),
        Ok(adapter) => {
            let name = adapter.adapter_info().await.ok();
            let state = adapter.adapter_state().await.ok();
            let powered = matches!(state, Some(CentralState::PoweredOn));
            // A present-but-unpowered adapter is the common Linux case (rfkill
            // soft block), so it gets its own actionable message.
            let detail = match state {
                Some(CentralState::PoweredOn) => "Bluetooth adapter is available and powered on.",
                Some(CentralState::PoweredOff) => {
                    "Bluetooth adapter is powered off. Turn Bluetooth on and retry."
                }
                _ => "Bluetooth adapter state is unknown. Turn Bluetooth on and retry.",
            };
            json!({
                "backend": backend(),
                "adapterAvailable": true,
                "poweredOn": powered,
                "adapter": name,
                "detail": detail,
            })
        }
    };
    println!("{report}");
    let _ = std::io::stdout().flush();
    Ok(())
}

async fn run_scan() -> Result<(), String> {
    let adapter = adapter().await?;
    let found = find_peripheral(&adapter, "", SCAN_TIMEOUT).await?;
    let probe = match found {
        None => json!({
            "detected": false,
            "name": null,
            "identifier": null,
            "serial": null,
            "protocolVersion": null,
            "rssi": null,
            "manufacturerData": [],
            "connectionVerified": false,
            "detail": "No advertising Plaud found. Wake the device and keep it near this computer.",
        }),
        Some(peripheral) => {
            let address = peripheral.address().to_string();
            let properties = peripheral.properties().await.ok().flatten();
            let name = properties
                .as_ref()
                .and_then(|properties| properties.local_name.clone())
                .unwrap_or_else(|| "Plaud".to_string());
            let rssi = properties.as_ref().and_then(|properties| properties.rssi);
            // Company-id keyed manufacturer payloads.  `btleplug` strips the
            // two company-identifier bytes that CoreBluetooth keeps, so they are
            // restored here: the vault then parses one identical layout on every
            // platform (`parseNoteProAdvertisement`).
            let manufacturer_data: Vec<Value> = properties
                .as_ref()
                .map(|properties| {
                    properties
                        .manufacturer_data
                        .iter()
                        .map(|(company, bytes)| {
                            let mut framed = Vec::with_capacity(bytes.len() + 2);
                            framed.extend_from_slice(&company.to_le_bytes());
                            framed.extend_from_slice(bytes);
                            json!({ "companyId": company, "data": BASE64.encode(framed) })
                        })
                        .collect()
                })
                .unwrap_or_default();
            let (serial, protocol_version) = parse_note_pro_advertisement(&manufacturer_data);
            let verified = verify_connection(&peripheral).await;
            let _ = peripheral.disconnect().await;
            json!({
                "detected": true,
                "name": name,
                "identifier": address,
                "serial": serial,
                "protocolVersion": protocol_version,
                "rssi": rssi,
                "manufacturerData": manufacturer_data,
                "connectionVerified": verified,
                "detail": if verified {
                    "Bluetooth connection verified. Recording access is not authenticated."
                } else {
                    "Plaud detected, but the Bluetooth connection failed. Retry with other Plaud clients disconnected."
                },
            })
        }
    };
    println!("{probe}");
    let _ = std::io::stdout().flush();
    Ok(())
}

/// Best-effort decode of the Plaud Note Pro advertisement payload.
///
/// Mirrors `parseNoteProAdvertisement` in `src/sync/plaud-protocol.ts`: the
/// serial lives at bytes 11..19 and the protocol version at byte 20.
fn parse_note_pro_advertisement(manufacturer_data: &[Value]) -> (Option<String>, Option<u16>) {
    for entry in manufacturer_data {
        let Some(encoded) = entry.get("data").and_then(Value::as_str) else {
            continue;
        };
        let Ok(bytes) = BASE64.decode(encoded) else {
            continue;
        };
        let Some((_project, protocol_version)) = note_pro_framed_ad(&bytes) else {
            continue;
        };
        let serial = bytes[11..19]
            .iter()
            .map(|byte| format!("{byte:02X}"))
            .collect::<String>();
        return (Some(serial), Some(protocol_version));
    }
    (None, None)
}

/// Continuous scan that prints filter-stage **counts only** (no MAC/serial/name).
///
/// Used to diagnose WinRT advertisement gaps vs CoreBluetooth: how many
/// peripherals appear, and how many fail each recognition stage.
async fn run_scan_verbose(duration: Duration) -> Result<(), String> {
    let adapter = adapter().await?;
    adapter
        .start_scan(ScanFilter::default())
        .await
        .map_err(|error| format!("Bluetooth scan could not start: {error}"))?;

    let mut seen: HashSet<String> = HashSet::new();
    let mut with_local_name = 0usize;
    let mut name_contains_plaud = 0usize;
    let mut service_1910_count = 0usize;
    let mut with_manufacturer_data = 0usize;
    let mut manufacturer_note_pro_shape = 0usize;
    let mut accepted = 0usize;
    let mut via_name = 0usize;
    let mut via_service = 0usize;
    let mut via_manufacturer = 0usize;
    let mut legacy_name_or_service = 0usize;
    let mut properties_missing = 0usize;

    let deadline = Instant::now() + duration;
    while Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(400)).await;
        let peripherals = adapter
            .peripherals()
            .await
            .map_err(|error| format!("Bluetooth scan failed: {error}"))?;
        for peripheral in peripherals {
            let key = normalize_identifier(&peripheral.address().to_string());
            if key.is_empty() || !seen.insert(key) {
                continue;
            }
            let Some(properties) = peripheral.properties().await.ok().flatten() else {
                properties_missing += 1;
                continue;
            };
            if properties.local_name.as_ref().is_some_and(|name| !name.is_empty()) {
                with_local_name += 1;
            }
            if properties
                .local_name
                .as_deref()
                .is_some_and(|name| name.to_ascii_lowercase().contains(NAME_HINT))
            {
                name_contains_plaud += 1;
            }
            if advertises_service_1910(&properties) {
                service_1910_count += 1;
            }
            if !properties.manufacturer_data.is_empty() {
                with_manufacturer_data += 1;
            }
            if manufacturer_looks_like_note_pro(&properties.manufacturer_data) {
                manufacturer_note_pro_shape += 1;
            }
            let legacy = properties
                .local_name
                .as_deref()
                .is_some_and(|name| name.to_ascii_lowercase().contains(NAME_HINT))
                || properties.services.contains(&SERVICE_UUID);
            if legacy {
                legacy_name_or_service += 1;
            }
            match classify_plaud(&properties) {
                Some(PlaudMatch::Name) => {
                    accepted += 1;
                    via_name += 1;
                }
                Some(PlaudMatch::Service) => {
                    accepted += 1;
                    via_service += 1;
                }
                Some(PlaudMatch::Manufacturer) => {
                    accepted += 1;
                    via_manufacturer += 1;
                }
                None => {}
            }
        }
    }
    let _ = adapter.stop_scan().await;

    let report = json!({
        "mode": "scan-verbose",
        "backend": backend(),
        "durationSeconds": duration.as_secs(),
        "uniquePeripherals": seen.len(),
        "propertiesMissing": properties_missing,
        "withLocalName": with_local_name,
        "nameContainsPlaud": name_contains_plaud,
        "advertisesService1910": service_1910_count,
        "withManufacturerData": with_manufacturer_data,
        "manufacturerNoteProShape": manufacturer_note_pro_shape,
        "acceptedByFilter": accepted,
        "acceptedVia": {
            "name": via_name,
            "service": via_service,
            "manufacturer": via_manufacturer,
        },
        "legacyFilterWouldAccept": legacy_name_or_service,
        "detail": if accepted > 0 {
            "At least one peripheral matched the widened Plaud filter (name, 0x1910, or Note Pro manufacturer framing)."
        } else if seen.is_empty() {
            "No BLE advertisements observed. Check adapter power, radio interference, or OS Bluetooth permissions."
        } else {
            "BLE advertisements seen, but none matched name/0x1910/Note Pro manufacturer framing. Device may not be advertising, or WinRT is stripping usable AD fields."
        },
    });
    println!("{report}");
    let _ = std::io::stdout().flush();
    Ok(())
}

async fn verify_connection(peripheral: &Peripheral) -> bool {
    if !matches!(
        tokio::time::timeout(VERIFY_TIMEOUT, peripheral.connect()).await,
        Ok(Ok(()))
    ) {
        return false;
    }
    if !matches!(
        tokio::time::timeout(VERIFY_TIMEOUT, peripheral.discover_services()).await,
        Ok(Ok(()))
    ) {
        return false;
    }
    peripheral
        .services()
        .iter()
        .any(|service| service.uuid == SERVICE_UUID)
}

async fn run_connect(identifier: String) -> Result<(), String> {
    let (tx, mut rx) = mpsc::unbounded_channel::<Value>();
    tokio::spawn(async move {
        while let Some(value) = rx.recv().await {
            let stdout = std::io::stdout();
            let mut out = stdout.lock();
            if serde_json::to_writer(&mut out, &value).is_ok() {
                let _ = out.write_all(b"\n");
                let _ = out.flush();
            }
        }
    });

    let adapter = adapter().await?;
    let peripheral = find_peripheral(&adapter, &identifier, SCAN_TIMEOUT)
        .await?
        .ok_or_else(|| "connection_timeout".to_string())?;

    if !matches!(
        tokio::time::timeout(DISCOVERY_TIMEOUT, peripheral.connect()).await,
        Ok(Ok(()))
    ) {
        emit(&tx, json!({ "event": "closed", "reason": "connection_failed" }));
        return Ok(());
    }
    emit(&tx, json!({ "event": "connected" }));

    if !matches!(
        tokio::time::timeout(DISCOVERY_TIMEOUT, peripheral.discover_services()).await,
        Ok(Ok(()))
    ) {
        emit(&tx, json!({ "event": "closed", "reason": "characteristic_discovery_failed" }));
        return Ok(());
    }

    let characteristics = peripheral.characteristics();
    if !peripheral
        .services()
        .iter()
        .any(|service| service.uuid == SERVICE_UUID)
    {
        emit(&tx, json!({ "event": "closed", "reason": "missing_command_service" }));
        return Ok(());
    }
    let notify = characteristics
        .iter()
        .find(|characteristic| characteristic.uuid == NOTIFY_UUID)
        .cloned();
    let writer = characteristics
        .iter()
        .find(|characteristic| characteristic.uuid == WRITE_UUID)
        .cloned();
    let (Some(notify), Some(writer)) = (notify, writer) else {
        emit(&tx, json!({ "event": "closed", "reason": "missing_command_characteristics" }));
        return Ok(());
    };

    if peripheral.subscribe(&notify).await.is_err() {
        emit(&tx, json!({ "event": "closed", "reason": "subscription_failed" }));
        return Ok(());
    }

    // Drain notifications on their own task so commands never block on them.
    match peripheral.notifications().await {
        Ok(mut notifications) => {
            let tx = tx.clone();
            tokio::spawn(async move {
                while let Some(notification) = notifications.next().await {
                    let is_packet = notification.uuid == NOTIFY_UUID;
                    emit(
                        &tx,
                        json!({
                            "event": if is_packet { "packet" } else { "metadata" },
                            "uuid": notification.uuid.to_string().to_ascii_uppercase(),
                            "data": BASE64.encode(&notification.value),
                        }),
                    );
                }
            });
        }
        Err(_) => {
            emit(&tx, json!({ "event": "closed", "reason": "notification_failed" }));
            return Ok(());
        }
    }

    // Publish any readable characteristics as metadata, mirroring the macOS bridge.
    for characteristic in characteristics
        .iter()
        .filter(|characteristic| characteristic.properties.contains(CharPropFlags::READ))
    {
        if let Ok(Ok(value)) =
            tokio::time::timeout(Duration::from_secs(5), peripheral.read(characteristic)).await
        {
            emit(
                &tx,
                json!({
                    "event": "metadata",
                    "uuid": characteristic.uuid.to_string().to_ascii_uppercase(),
                    "data": BASE64.encode(value),
                }),
            );
        }
    }

    emit(&tx, json!({ "event": "ready", "maxWrite": 512 }));

    let stdin = BufReader::new(tokio::io::stdin());
    let mut lines = stdin.lines();
    let mut health = tokio::time::interval(Duration::from_secs(2));
    health.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    let deadline = tokio::time::sleep(SESSION_DEADLINE);
    tokio::pin!(deadline);

    loop {
        tokio::select! {
            _ = &mut deadline => {
                emit(&tx, json!({ "event": "closed", "reason": "session_deadline" }));
                break;
            }
            _ = health.tick() => {
                if !peripheral.is_connected().await.unwrap_or(false) {
                    emit(&tx, json!({ "event": "closed", "reason": "disconnected" }));
                    break;
                }
            }
            line = lines.next_line() => {
                match line {
                    Ok(Some(text)) => {
                        if !handle_request(&text, &tx, &peripheral, &writer).await {
                            break;
                        }
                    }
                    _ => {
                        emit(&tx, json!({ "event": "closed", "reason": "client_eof" }));
                        break;
                    }
                }
            }
        }
    }

    let _ = peripheral.disconnect().await;
    Ok(())
}

/// Handle one JSON-lines request.  Returns `false` when the session should end.
async fn handle_request(
    text: &str,
    tx: &Emitter,
    peripheral: &Peripheral,
    writer: &btleplug::api::Characteristic,
) -> bool {
    if text.len() > MAX_REQUEST_BYTES {
        emit(tx, json!({ "event": "closed", "reason": "invalid_request" }));
        return false;
    }
    let Ok(request) = serde_json::from_str::<Value>(text) else {
        emit(tx, json!({ "event": "closed", "reason": "invalid_request" }));
        return false;
    };
    let id = request.get("id").and_then(Value::as_i64).unwrap_or(-1);
    match request.get("op").and_then(Value::as_str) {
        Some("write") => {
            let data = request
                .get("data")
                .and_then(Value::as_str)
                .and_then(|value| BASE64.decode(value).ok());
            let ok = match data {
                Some(bytes) if !bytes.is_empty() => peripheral
                    .write(writer, &bytes, WriteType::WithResponse)
                    .await
                    .is_ok(),
                _ => false,
            };
            emit(tx, json!({ "event": "reply", "id": id, "ok": ok }));
        }
        Some("rsa-decrypt") => {
            let key = request
                .get("key")
                .and_then(Value::as_str)
                .and_then(|value| BASE64.decode(value).ok());
            let ciphertext = request
                .get("data")
                .and_then(Value::as_str)
                .and_then(|value| BASE64.decode(value).ok());
            let plaintext = match (key, ciphertext) {
                (Some(key), Some(ciphertext)) if ciphertext.len() == 256 => decode_private_key(&key)
                    .and_then(|private| {
                        private
                            .decrypt(Pkcs1v15Encrypt, &ciphertext)
                            .map_err(|_| "decrypt failed".to_string())
                    })
                    .ok(),
                _ => None,
            };
            match plaintext {
                Some(plaintext) => emit(
                    tx,
                    json!({ "event": "reply", "id": id, "ok": true, "data": BASE64.encode(plaintext) }),
                ),
                None => emit(tx, json!({ "event": "reply", "id": id, "ok": false })),
            }
        }
        Some("close") => {
            emit(tx, json!({ "event": "closed", "reason": "client_closed" }));
            return false;
        }
        _ => emit(tx, json!({ "event": "reply", "id": id, "ok": false })),
    }
    true
}

fn decode_private_key(bytes: &[u8]) -> Result<RsaPrivateKey, String> {
    RsaPrivateKey::from_pkcs1_der(bytes)
        .or_else(|_| RsaPrivateKey::from_pkcs8_der(bytes))
        .map_err(|_| "invalid RSA private key".to_string())
}
