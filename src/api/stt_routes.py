"""REST and WebSocket routes for multi-provider streaming STT."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from src.auth.dependencies import get_current_user
from src.auth.jwt import decode_access_token
from src.db.mongodb import col_recordings, col_stt_sessions, get_db
from src.stt.audio_feeder import feed_isolated_user_audio
from src.stt.audio_source import resolve_stt_audio_source
from src.stt.benchmarks import persist_stt_accuracy_metrics
from src.stt.language_detection import (
    SUPPORTED_LANGUAGES,
    detect_language_from_audio_url,
    effective_stt_language,
)
from src.stt.models import (
    AudioQualityInfo,
    LanguageCandidateInfo,
    LanguageMode,
    SelectionMode,
    SttAudioSource,
    SttSessionConfig,
    SttSessionSnapshot,
    TranscriptMode,
)
from src.stt.orchestrator import MultiProviderOrchestrator
from src.stt.persistence import persist_user_stt_results
from src.stt.providers.registry import DISPLAY_NAMES, ProviderRegistry
from src.stt.session_manager import build_session_record, session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stt", tags=["stt"])


def _default_transcript_mode() -> TranscriptMode:
    mode = os.getenv("STT_TRANSCRIPT_MODE", "consensus").lower()
    return TranscriptMode.CONSENSUS if mode == "consensus" else TranscriptMode.SINGLE


class ProviderInfo(BaseModel):
    id: str
    display_name: str
    configured: bool


class CreateSessionRequest(BaseModel):
    recording_id: str
    enabled_providers: list[str] = Field(
        default_factory=lambda: list(ProviderRegistry.available_provider_ids())
    )
    selection_mode: SelectionMode = SelectionMode.AUTO
    manual_provider: Optional[str] = None
    hysteresis_threshold: float = 5.0
    sample_rate: int = 16000
    auto_detect_language: bool = True
    language: Optional[str] = None
    transcript_mode: Optional[TranscriptMode] = None
    audio_source: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    ws_url: str


class UpdateSelectionRequest(BaseModel):
    selection_mode: SelectionMode
    manual_provider: Optional[str] = None
    hysteresis_threshold: Optional[float] = None


@router.get("/providers")
async def list_providers(_user: dict = Depends(get_current_user)) -> dict:
    providers = []
    for pid in ProviderRegistry.available_provider_ids():
        real_cls = __import__(
            "src.stt.providers.registry", fromlist=["REAL_PROVIDERS"]
        ).REAL_PROVIDERS[pid]
        providers.append(
            ProviderInfo(
                id=pid,
                display_name=DISPLAY_NAMES[pid],
                configured=real_cls.is_configured(),
            )
        )
    return {"providers": providers}


@router.get("/languages")
async def list_languages(_user: dict = Depends(get_current_user)) -> dict:
    return {"languages": SUPPORTED_LANGUAGES}


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> CreateSessionResponse:
    """Create an STT session that compares providers on isolated **user** audio only."""
    if not ObjectId.is_valid(body.recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")

    rec = await col_recordings(db).find_one(
        {"_id": ObjectId(body.recording_id), "user_id": user["id"]}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Recording is not fully processed yet")

    user_audio_url = rec.get("user_audio_url")
    if not user_audio_url:
        raise HTTPException(
            status_code=400,
            detail="Isolated user audio is not available for this recording",
        )

    session_id = str(uuid.uuid4())
    config = SttSessionConfig(
        enabled_providers=body.enabled_providers,
        selection_mode=body.selection_mode,
        manual_provider=body.manual_provider,
        hysteresis_threshold=body.hysteresis_threshold,
        sample_rate=body.sample_rate,
        language=body.language or "en-US",
        auto_detect_language=body.auto_detect_language,
        language_override=body.language,
        transcript_mode=body.transcript_mode or _default_transcript_mode(),
        source=SttAudioSource.ISOLATED_USER_AUDIO,
        recording_id=body.recording_id,
        user_audio_url=user_audio_url,
        recording_file_name=rec.get("file_name"),
    )
    orchestrator = MultiProviderOrchestrator(session_id=session_id, config=config)
    orchestrator._audio_source_preference = body.audio_source  # noqa: SLF001
    orchestrator._original_audio_url = rec.get("original_audio_url") or rec.get("recording_url")  # noqa: SLF001
    await session_manager.create(orchestrator)
    return CreateSessionResponse(
        session_id=session_id,
        ws_url=f"/stt/ws/{session_id}",
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    user: dict = Depends(get_current_user),
) -> SttSessionSnapshot:
    orchestrator = await session_manager.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return orchestrator.current_snapshot()


@router.patch("/sessions/{session_id}/selection")
async def update_selection(
    session_id: str,
    body: UpdateSelectionRequest,
    user: dict = Depends(get_current_user),
) -> SttSessionSnapshot:
    orchestrator = await session_manager.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="Session not found or expired")

    config = orchestrator.config.model_copy(
        update={
            "selection_mode": body.selection_mode,
            "manual_provider": body.manual_provider,
            **(
                {"hysteresis_threshold": body.hysteresis_threshold}
                if body.hysteresis_threshold is not None
                else {}
            ),
        }
    )
    await orchestrator.update_config(config)
    return orchestrator.current_snapshot()


@router.get("/sessions/history")
async def session_history(
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    cursor = (
        col_stt_sessions(db)
        .find({"user_id": user["id"]})
        .sort("started_at", -1)
        .limit(limit)
    )
    sessions = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id", ""))
        sessions.append(doc)
    return {"sessions": sessions}


@router.get("/metrics/{recording_id}")
async def stt_accuracy_metrics(
    recording_id: str,
    user: dict = Depends(get_current_user),
    db=Depends(get_db),
) -> dict:
    """Return stored STT accuracy benchmark rows for a recording."""
    from src.db.mongodb import col_stt_accuracy_metrics

    if not ObjectId.is_valid(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    rec = await col_recordings(db).find_one(
        {"_id": ObjectId(recording_id), "user_id": user["id"]}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")

    cursor = col_stt_accuracy_metrics(db).find({"recording_id": recording_id}).sort("created_at", -1)
    metrics = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id", ""))
        metrics.append(doc)
    return {"recording_id": recording_id, "metrics": metrics}


async def _authenticate_ws(token: Optional[str]) -> str:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user_id


def _language_mode_from_detection(detection) -> LanguageMode:
    if detection.language_mode == "multilingual":
        return LanguageMode.MULTILINGUAL
    if detection.language_mode == "auto":
        return LanguageMode.AUTO
    return LanguageMode.FIXED


async def _detect_language_with_keepalive(
    audio_url: str,
    send: Callable[[dict], Awaitable[bool]],
    *,
    interval_seconds: float = 15.0,
):
    """Run LID in a thread and ping the client so the WebSocket stays alive."""
    task = asyncio.create_task(asyncio.to_thread(detect_language_from_audio_url, audio_url))
    tick = 0
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval_seconds)
            break
        except asyncio.TimeoutError:
            tick += 1
            if not await send(
                {
                    "type": "language_detecting",
                    "message": "Analyzing spoken language…",
                    "tick": tick,
                }
            ):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise WebSocketDisconnect()
    return await task


@router.websocket("/ws/{session_id}")
async def stt_websocket(
    websocket: WebSocket,
    session_id: str,
    token: Optional[str] = Query(default=None),
) -> None:
    await websocket.accept()

    user_id = decode_access_token(token) if token else None
    if not user_id:
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
            auth_msg = json.loads(raw)
            if auth_msg.get("type") == "auth":
                user_id = decode_access_token(auth_msg.get("token") or "")
        except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
            user_id = None

    if not user_id:
        await websocket.send_json({"type": "error", "message": "Missing or invalid token — log in again."})
        await websocket.close(code=4401)
        return

    orchestrator = await session_manager.get(session_id)
    if not orchestrator:
        await websocket.send_json(
            {
                "type": "error",
                "message": "Session not found or expired. Click Compare again (server may have restarted).",
            }
        )
        await websocket.close(code=4404)
        return

    started_at = datetime.now(timezone.utc)
    client_connected = True

    async def safe_send(payload: dict) -> bool:
        nonlocal client_connected
        if not client_connected:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except WebSocketDisconnect:
            client_connected = False
            return False
        except RuntimeError:
            client_connected = False
            return False

    async def push_snapshot(snapshot: SttSessionSnapshot) -> None:
        await safe_send({"type": "snapshot", "data": snapshot.model_dump(mode="json")})

    orchestrator._on_snapshot = push_snapshot  # noqa: SLF001

    feed_url = orchestrator.config.user_audio_url
    feed_task: asyncio.Task | None = None

    try:
        if orchestrator.config.user_audio_url:
            original_url = getattr(orchestrator, "_original_audio_url", None)
            source_pref = getattr(orchestrator, "_audio_source_preference", None)
            if not await safe_send({"type": "audio_inspecting"}):
                raise WebSocketDisconnect()
            source_decision = await asyncio.to_thread(
                resolve_stt_audio_source,
                user_audio_url=orchestrator.config.user_audio_url,
                original_audio_url=original_url,
                preference=source_pref,
            )
            if not client_connected:
                raise WebSocketDisconnect()
            feed_url = source_decision.url
            orchestrator.add_warnings(source_decision.warnings)
            chosen_quality = (
                source_decision.isolated_quality
                if source_decision.source_type == "isolated_user_audio"
                else source_decision.original_quality
            )
            quality_info = None
            if chosen_quality:
                quality_info = AudioQualityInfo(**chosen_quality.to_dict())

            if orchestrator.config.auto_detect_language and not orchestrator.config.language_override:
                if not await safe_send({"type": "language_detecting", "message": "Starting language detection…"}):
                    raise WebSocketDisconnect()
                detection = await _detect_language_with_keepalive(feed_url, safe_send)
                if not client_connected:
                    raise WebSocketDisconnect()
                stt_language = effective_stt_language(detection)
                orchestrator.config = orchestrator.config.model_copy(
                    update={
                        "language": stt_language,
                        "detected_language": detection.language,
                        "language_code": detection.language_code,
                        "language_confidence": detection.confidence,
                        "language_detection_method": detection.method,
                        "language_mode": _language_mode_from_detection(detection),
                        "language_candidates": [
                            LanguageCandidateInfo(
                                language=c.language,
                                language_code=c.language_code,
                                confidence=c.confidence,
                            )
                            for c in detection.candidates
                        ],
                        "language_hints": detection.language_hints,
                        "audio_source_type": source_decision.source_type,
                        "audio_quality": quality_info,
                        "user_audio_url": feed_url,
                    }
                )
                await orchestrator.update_config(orchestrator.config)
                if not await safe_send({"type": "language_detected", "data": detection.to_dict()}):
                    raise WebSocketDisconnect()
            else:
                orchestrator.config = orchestrator.config.model_copy(
                    update={
                        "language": orchestrator.config.language_override or orchestrator.config.language,
                        "language_detection_method": "manual",
                        "audio_source_type": source_decision.source_type,
                        "audio_quality": quality_info,
                        "user_audio_url": feed_url,
                    }
                )
                if orchestrator.config.language_override:
                    await orchestrator.update_config(orchestrator.config)

        await orchestrator.start()
        ready = orchestrator.ready_provider_count()
        if ready == 0:
            await safe_send(
                {
                    "type": "error",
                    "message": "No STT providers connected. Add API keys to .env or enable STT_ALLOW_SIMULATED=true.",
                }
            )
        elif ready < len(orchestrator.config.enabled_providers):
            await safe_send(
                {
                    "type": "providers_ready",
                    "ready": ready,
                    "total": len(orchestrator.config.enabled_providers),
                }
            )
        await push_snapshot(orchestrator.current_snapshot())

        if orchestrator.config.source == SttAudioSource.ISOLATED_USER_AUDIO:
            if not feed_url:
                await safe_send({"type": "error", "message": "No isolated user audio URL configured"})
            else:

                async def run_feed() -> None:
                    try:
                        await safe_send({"type": "feed_started"})
                        await feed_isolated_user_audio(
                            orchestrator,
                            feed_url,
                            sample_rate=orchestrator.config.sample_rate,
                            on_progress=orchestrator.set_feed_progress,
                        )
                        await orchestrator.mark_feed_complete()
                        await safe_send({"type": "feed_complete"})
                    except Exception as exc:
                        logger.exception("Failed feeding isolated user audio")
                        await safe_send({"type": "error", "message": str(exc)})

                feed_task = asyncio.create_task(run_feed())

        while client_connected:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            msg_type = message.get("type")

            if msg_type == "config":
                partial = message.get("config", {})
                merged = orchestrator.config.model_copy(update=partial)
                await orchestrator.update_config(merged)
            elif msg_type == "audio":
                if orchestrator.config.source != SttAudioSource.ISOLATED_USER_AUDIO:
                    pcm = base64.b64decode(message.get("data", ""))
                    await orchestrator.send_audio(pcm)
                else:
                    await safe_send(
                        {
                            "type": "error",
                            "message": "Live audio is disabled; STT runs on isolated user audio only",
                        }
                    )
            elif msg_type == "selection":
                current = orchestrator.config.model_copy(
                    update={
                        "selection_mode": SelectionMode(message["selection_mode"]),
                        "manual_provider": message.get("manual_provider"),
                    }
                )
                if "hysteresis_threshold" in message:
                    current.hysteresis_threshold = message["hysteresis_threshold"]
                await orchestrator.update_config(current)
            elif msg_type == "ping":
                await safe_send({"type": "pong"})
            elif msg_type == "stop":
                break
    except WebSocketDisconnect:
        logger.info("STT WebSocket disconnected: session=%s", session_id)
    except Exception as exc:
        logger.exception("STT WebSocket error: session=%s", session_id)
        await safe_send({"type": "error", "message": str(exc)})
    finally:
        if feed_task and not feed_task.done():
            feed_task.cancel()
            try:
                await feed_task
            except asyncio.CancelledError:
                pass
        await orchestrator.stop()
        final_snapshot = orchestrator.current_snapshot()
        record = build_session_record(
            user_id=user_id,
            orchestrator=orchestrator,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
        )
        try:
            db = await get_db()
            await col_stt_sessions(db).insert_one(record.model_dump(mode="json"))
            if orchestrator.config.recording_id and final_snapshot.feed_complete:
                await persist_user_stt_results(
                    db,
                    orchestrator.config.recording_id,
                    final_snapshot,
                )
                await persist_stt_accuracy_metrics(
                    db,
                    recording_id=orchestrator.config.recording_id,
                    user_id=user_id,
                    session_id=session_id,
                    snapshot=final_snapshot,
                )
        except Exception as exc:
            logger.warning("Failed to persist STT session %s: %s", session_id, exc)
        await session_manager.remove(session_id)
        try:
            await websocket.close()
        except Exception:
            pass
