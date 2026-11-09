# Optional extras matrix (AMD / CPU first)

Plaud-local does **not** assume NVIDIA CUDA. On AMD Strix Halo and other Fedora
hosts, prefer CPU ASR extras locally and send LLM traffic to
**inference-gateway-manager** (ROCm/HIP engines live there, not in this repo).
Do **not** install the `cuda` extra or Compose `--profile gpu` on AMD-only
machines — that profile is NVIDIA-only. See [platform-matrix.md](platform-matrix.md)
and [deploy-fedora.md](deploy-fedora.md).

| Extra (`pyproject.toml`) | Purpose | Plaud-local guidance |
| --- | --- | --- |
| *(base)* | App, SQLite, UI, official Open API | Always install |
| `dev` | pytest, ruff, mypy, respx | CI and local development |
| `cloud` | openai / deepgram / assemblyai / anthropic SDKs | Install for tests or when explicitly enabling a cloud provider; **providers stay opt-in** |
| `faster-whisper` | Local CTranslate2 ASR | Default local ASR path; use `device=cpu` on non-NVIDIA hosts |
| `cuda` | faster-whisper + NVIDIA cuBLAS/cuDNN wheels | **Do not** install on AMD-only hosts |
| `mlx` | Apple Silicon ASR | Not for Fedora/AMD |
| `diarize` | pyannote + torch | Heavy; CPU possible, follow HF ToS; no CUDA assumption |
| `forced-align` | WhisperX | Optional; large torch stack |
| `vad` | silero-vad for non-faster-whisper paths | Optional |
| `local-llm` | sentence-transformers embeddings | Local Ask/search without cloud embeddings |

## Recommended Fedora (AMD / CPU) sync

```bash
# Application + CI tooling + optional cloud SDKs (keys still required to use them)
uv sync --extra dev --extra cloud

# Local ASR on CPU (no NVIDIA wheels)
uv sync --extra dev --extra cloud --extra faster-whisper

# Optional diarization (CPU torch from your chosen index — not the cuda extra)
uv sync --extra dev --extra cloud --extra faster-whisper --extra diarize
```

Point `[llm]` at `ai-gateway` → IGM (`docs/deploy-fedora-igm.md`). Leave
`[asr].fallback` empty unless you intentionally opt into paid cloud ASR.

## CI extras

GitHub Actions runs:

```bash
uv sync --locked --extra dev --extra cloud
uv pip install "torch>=2.8" --index-url https://download.pytorch.org/whl/cpu
uv run ruff check src tests
uv run pytest -q
```

Focused gateway checks (fast smoke while iterating):

```bash
uv run pytest -q tests/test_ai_gateway.py tests/test_config.py
```
