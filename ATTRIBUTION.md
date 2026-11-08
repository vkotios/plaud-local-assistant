# Attribution

## localplaud (foundation)

- **Project:** [skyhong2002/localplaud](https://github.com/skyhong2002/localplaud)
- **License:** MIT (Copyright (c) 2026 Sky Hong)
- **Pinned commit:** see [docs/UPSTREAM.md](docs/UPSTREAM.md)
- **Reuse:** Plaud-local tracks localplaud as the application foundation
  (package layout, pipeline, official Open API client, UI, tests). Product
  overlays live in this repository on top of that history.

## inference-gateway-manager (external inference host)

- **Project:** [vkotios/inference-gateway-manager](https://github.com/vkotios/inference-gateway-manager)
- **License:** MIT
- **Reuse:** Client-only. Plaud-local does not vendor IGM. Configure
  `llm.ai_gateway.base_url` to the gateway’s OpenAI-compatible `/v1` endpoint.

## OpenPlod / openplaud (Bluetooth adapter — Phase 4)

- **Project:** [RemiPelloux/OpenPlod](https://github.com/RemiPelloux/OpenPlod)
- **License:** MIT (Copyright (c) 2026 Remi Pelloux and OpenPlod contributors)
- **Pinned revision:** `d5c27989b05837cd49ff7780595514e133bd1c0d`
- **Reuse (selective):**
  - Python adaptations in `src/localplaud/ble/` from OpenPlod `src/sync/`
    (provision, protocol, session cipher, audio, transfer checksum, bridge
    locate/spawn concepts).
  - Vendored Rust `plaud-bridge` under `vendor/openplod-ble/plaud-bridge/`.
- **Not reused:** OpenPlod vault, React/Tauri UI, transcription stack, MCP
  product server, Android companion, cloud-import product flows.
- **Provenance note:** OpenPlod derives historically from openplaud; see
  `vendor/openplod-ble/NOTICE`. Residual openplaud LICENSE-file gap is an
  accepted owner risk for this adapter.
- **Third-party (bridge):** btleplug (MIT/Apache-2.0/BSD-3-Clause), rsa crate
  (MIT/Apache-2.0); Python optional `cryptography` for ChaCha20 / RSA unwrap.

## Explicitly not incorporated

Private/RE Plaud API stacks (Applaud, plaud-tools API, plaud-toolkit API,
PlaudNotes, Riffado/AGPL) are rejected as sync or product dependencies.
