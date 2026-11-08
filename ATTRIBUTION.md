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

## Deferred — OpenPlod / openplaud (Bluetooth adapter)

Not vendored in Phase 2. Future Phase 4 attribution will list:

- OpenPlod MIT contributions and third-party crate/npm notices
- openplaud provenance status after compliance review

## Explicitly not incorporated

Private/RE Plaud API stacks (Applaud, plaud-tools API, plaud-toolkit API,
PlaudNotes, Riffado/AGPL) are rejected as sync or product dependencies.
