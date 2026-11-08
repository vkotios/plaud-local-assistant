# Fedora + inference-gateway-manager (Plaud-local overlay)

Primary operator OS for Plaud-local is **Fedora/Linux**. Local text inference
goes through **inference-gateway-manager (IGM)** as an OpenAI-compatible client.
Windows 11 is supported in v1 via **WSL2 or Docker**, not as a native first-class
host.

This overlay complements upstream [deploy.md](deploy.md). It does **not** replace
IGM’s own install docs.

## Architecture (client, not engine manager)

```
Plaud-local (localplaud)  --OpenAI /v1-->  IGM :9000  -->  loaded engine/model
```

- Plaud-local never starts, loads, or unloads GPU engines.
- IGM concurrency is **1**: a busy gateway returns **HTTP 409**.
- Cloud LLM/ASR providers remain **opt-in** (explicit config + secrets).

## Example LLM profile (IGM)

Copy `config.example.toml` → `config.toml`, then set:

```toml
[llm]
provider = "ai-gateway"

  [llm.ai_gateway]
  # Inference Bearer key via env / secret_ref — never commit the value.
  # LOCALPLAUD_LLM__AI_GATEWAY__API_KEY=...
  base_url = "http://127.0.0.1:9000/v1"
  model = "loaded-model-id"   # must match the model IGM currently has loaded
  api_mode = "chat"
  client_name = "plaud-local" # X-Client-Name
  serial_calls = true
  busy_max_attempts = 8
  busy_backoff_base_seconds = 1.0
  busy_backoff_max_seconds = 60.0
  quota_guard = false         # IGM is not a Codex subscription gateway
```

Environment override examples:

```bash
export LOCALPLAUD_LLM__PROVIDER=ai-gateway
export LOCALPLAUD_LLM__AI_GATEWAY__BASE_URL=http://127.0.0.1:9000/v1
export LOCALPLAUD_LLM__AI_GATEWAY__API_KEY=igm-inference-key
export LOCALPLAUD_LLM__AI_GATEWAY__MODEL=your-loaded-model-id
export LOCALPLAUD_LLM__AI_GATEWAY__CLIENT_NAME=plaud-local
export LOCALPLAUD_LLM__AI_GATEWAY__SERIAL_CALLS=true
export LOCALPLAUD_LLM__AI_GATEWAY__QUOTA_GUARD=false
```

### Operator checklist

1. Start IGM and **explicitly load** an engine/model (picker does not switch engines).
2. Use the **inference** key in Plaud-local — never the control-plane key.
3. Confirm readiness with `GET http://127.0.0.1:9000/v1/models` (auth required).
   HTTP liveness alone does not mean a model is loaded.
4. Expect **409** under contention; the `ai-gateway` client retries with backoff.
5. Keep cloud providers disabled unless you intentionally set `llm.provider` /
   ASR fallbacks and supply keys.

## Fedora core install (native sketch)

```bash
sudo dnf install -y python3.12 python3.12-devel git ffmpeg
# Optional local ASR stack deps as needed; prefer CPU / ROCm paths — see extras-matrix.md
git clone https://github.com/vkotios/plaud-local-assistant.git
cd plaud-local-assistant
uv sync --extra dev --extra cloud   # cloud extra = SDKs only; providers stay opt-in
cp config.example.toml config.toml
cp .env.example .env                # fill LOCALPLAUD_LLM__AI_GATEWAY__API_KEY
# Point [llm] at ai-gateway as above, then:
uv run localplaud run
```

Docker remains valid for the **core** app (`docker compose --profile cpu …`).
Do not assume GPU/ROCm or Bluetooth work inside the default containers.

## Windows 11 (v1 policy)

- Run the core app under **WSL2 (Fedora/Ubuntu)** or Docker Desktop.
- Point `base_url` at an IGM instance reachable from that environment
  (localhost forwarded, or LAN host running IGM on Fedora).
- Native Windows is **not** promised for v1.

## Out of scope here

- Bluetooth / OpenPlod host requirements (Phase 4; see NOTICE).
- Private/RE Plaud API sync clients (permanently rejected).
- Reimplementing IGM engine management inside this repository.
