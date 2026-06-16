# STT Accuracy Analysis Report

## Pipeline trace

| Stage | Input | Output | Sample rate | Bit depth | Channels | Key issues |
|-------|-------|--------|-------------|-----------|----------|------------|
| 1. Original load | URL/file | `AudioSegment` | Source-native (often 44.1 kHz OGG) | 16-bit typical | Often mono | No normalization; ffmpeg fallback → 44.1 kHz mono |
| 2. Diarization prep | Loaded audio | Temp WAV | **48 kHz** | PCM16 | **Mono** | Diarization uses 48 kHz; cuts applied to native-rate audio |
| 3. User isolation | Segments + audio | `user_only.wav` | **Native (unchanged)** | Unchanged | Unchanged | Gaps removed → compressed timeline; no STT optimization |
| 4. STT feed reload | `user_audio_url` | PCM16 stream | **16 kHz** (pydub resample) | **16-bit** | **Mono** | Re-download; pydub resample; realtime pacing slows feed |
| 5. Language ID | First 45s clip | BCP-47 locale | — | — | — | Was `tiny`; only top-1; no multilingual fallback |
| 6. Provider STT | PCM16 chunks | Partial/final text | Provider-specific | — | — | 3/5 providers lack confidence; auto-select biased |
| 7. Selection | Provider states | Primary transcript | — | — | — | Raw confidence only; no consensus |
| 8. Persistence | Snapshot | MongoDB | — | — | — | Single provider text; no word timestamps |

## Root causes of poor accuracy

1. **Weak language ID** — Whisper `tiny` on 30s clip with no confidence gate; Hinglish/mixed calls forced to single locale.
2. **Suboptimal isolated audio** — `user_only.wav` not exported at 16 kHz mono; aggressive gap removal loses context pauses.
3. **Resampling chain** — Multiple pydub resamples (native → 48k diarization path vs 16k STT) without quality-preserving filters.
4. **No audio QA** — Clipping, silence, and isolation damage not detected before STT.
5. **Provider selection bias** — OpenAI/Google/AWS excluded from ranking (no confidence scores).
6. **No consensus** — Single provider chosen; errors not corrected by cross-provider agreement.
7. **No post-processing** — Raw STT output stored without punctuation/ITN fixes.
8. **Slow realtime feed** — 1× pacing delays final results and provider flush.

## Implemented improvements

See code in:

- `src/stt/audio_quality.py` — quality score, SNR, clipping, warnings
- `src/stt/audio_preprocess.py` — STT-ready 16 kHz mono export with peak normalize
- `src/stt/language_detection.py` — `small` default, top-k candidates, confidence threshold, multilingual mode
- `src/stt/provider_scoring.py` — composite score (confidence + completeness + language match)
- `src/stt/consensus.py` — weighted majority consensus transcript (default mode)
- `src/stt/postprocess.py` — conservative cleanup (punctuation, caps, acronyms)
- `src/stt/audio_source.py` — A/B isolated vs original with auto fallback
- `src/api/stt_debug_routes.py` — pipeline inspection endpoints
- `src/isolation/audio_extractor.py` — STT-optimized `user_only.wav` export

## Environment variables

```env
WHISPER_LID_MODEL=small
STT_LANGUAGE_CONFIDENCE_THRESHOLD=0.80
STT_TRANSCRIPT_MODE=consensus
STT_AUDIO_SOURCE=auto
STT_FEED_REALTIME=false
STT_PEAK_NORMALIZE=true
```

## Measuring improvement

Run STT on a recording and inspect:

- `GET /stt/debug/{recording_id}/pipeline`
- Session snapshot fields: `audio_quality`, `consensus_transcript`, `provider_scores`, `warnings`

Benchmark metrics stored in `stt_accuracy_metrics` collection after each session.
