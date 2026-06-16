# Multi-Provider Streaming STT

This document describes the multi-provider STT confidence comparison feature.

## Architecture

```
Browser (mic PCM16) ──WebSocket──► FastAPI /stt/ws/{session_id}
                                        │
                                        ▼
                              MultiProviderOrchestrator
                                        │
                    ┌───────────────────┼───────────────────┐
                    ▼                   ▼                   ▼
              DeepgramProvider    AzureSpeechProvider   OpenAiSttProvider ...
                    │                   │                   │
                    └───────────────────┴───────────────────┘
                                        │
                              ProviderSelector (auto/manual)
                                        │
                              WebSocket snapshot push ──► UI
```

### Key packages

| Path | Purpose |
|------|---------|
| `src/stt/base.py` | Provider-agnostic adapter interface |
| `src/stt/normalization.py` | Confidence normalization (0–100) |
| `src/stt/selection.py` | Auto selection with hysteresis |
| `src/stt/metrics.py` | Per-provider metrics |
| `src/stt/orchestrator.py` | Parallel fan-out and aggregation |
| `src/stt/providers/` | Provider implementations + registry |
| `src/api/stt_routes.py` | REST + WebSocket API |
| `frontend/src/app/stt-comparison/` | Comparison UI |

## Current vs new behavior

Previously, the platform had **no streaming STT**. Analytics “STT confidence” used placeholder values from diarization segments. This feature adds a **live multi-provider comparison** path independent of batch job processing.

## Provider configuration

Set API keys in `.env` (see `.env.example`). When a provider is not configured and `STT_ALLOW_SIMULATED=true` (default), a **simulated provider** is used so you can develop and demo without credentials.

| Provider | Env vars | Confidence |
|----------|----------|------------|
| Deepgram | `DEEPGRAM_API_KEY` | Yes (0–1 word avg) |
| Azure | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` | Yes (NBest) |
| OpenAI | `OPENAI_API_KEY` | No (N/A) |
| Google | `GOOGLE_APPLICATION_CREDENTIALS` | No (N/A) |
| AWS | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | No (N/A) |

Optional SDK packages for real providers (not required for simulated mode):

- `azure-cognitiveservices-speech`
- `google-cloud-speech`
- `amazon-transcribe`

## API

### REST

- `GET /stt/providers` — list providers and configured status
- `POST /stt/sessions` — create session, returns `session_id` + `ws_url`
- `GET /stt/sessions/{id}` — current snapshot
- `PATCH /stt/sessions/{id}/selection` — update auto/manual selection
- `GET /stt/sessions/history` — persisted session summaries

### WebSocket

`WS /stt/ws/{session_id}?token=<JWT>`

Client → server messages:

```json
{ "type": "audio", "data": "<base64 PCM16 mono 16kHz>" }
{ "type": "selection", "selection_mode": "auto|manual", "manual_provider": "azure" }
{ "type": "config", "config": { "hysteresis_threshold": 5.0 } }
{ "type": "stop" }
```

Server → client:

```json
{ "type": "snapshot", "data": { ...SttSessionSnapshot } }
```

## Confidence normalization

See `src/stt/normalization.py`. Raw provider values are mapped to 0–100. Missing confidence displays as **N/A** in the UI.

## Auto selection hysteresis

Default threshold: **5 percentage points**. A new provider must beat the current auto-selected provider by at least this margin before switching, reducing transcript flicker.

## Database

Collection: `stt_sessions` — persisted when a WebSocket session ends.

Indexes: `user_id`, `session_id` (unique), `started_at`.

## Language detection

Before STT starts, the server analyzes the **isolated user audio** (first ~45s) to detect spoken language:

1. **Whisper tiny** (default, uses existing PyTorch install) — set `STT_LANGUAGE_DETECT=false` to disable
2. **Fallback** — `STT_DEFAULT_LANGUAGE` (default `en-US`)

Detected language is mapped to each provider's expected locale/code. You can override manually via the language dropdown in the UI or `POST /stt/sessions` with `"language": "hi-IN"`.

Supported override languages: `GET /stt/languages`

## Frontend

STT comparison runs **only on isolated user audio** (`user_only.wav`). Agent audio is never sent to STT providers.

Navigate to **Call Details → STT Comparison** tab on a completed recording, or open `/stt-comparison?recordingId={id}`.

## Testing

```bash
pytest tests/test_stt_*.py -v
```

## Performance notes

- Each enabled provider receives a full copy of the audio stream (N× bandwidth to external APIs).
- Simulated providers are lightweight; real providers add network latency per provider.
- Recommended: enable only providers you need in production; use simulated mode for local dev.
