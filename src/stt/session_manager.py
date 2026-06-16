"""In-memory STT session registry."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from src.stt.models import SttSessionRecord, SttSessionSnapshot
from src.stt.orchestrator import MultiProviderOrchestrator


class SessionManager:
    """Track active streaming sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, MultiProviderOrchestrator] = {}
        self._lock = asyncio.Lock()

    async def create(self, orchestrator: MultiProviderOrchestrator) -> MultiProviderOrchestrator:
        async with self._lock:
            self._sessions[orchestrator.session_id] = orchestrator
        return orchestrator

    async def get(self, session_id: str) -> Optional[MultiProviderOrchestrator]:
        return self._sessions.get(session_id)

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def stop(self, session_id: str) -> None:
        orchestrator = self._sessions.get(session_id)
        if orchestrator:
            await orchestrator.stop()
            await self.remove(session_id)

    def active_count(self) -> int:
        return len(self._sessions)


session_manager = SessionManager()


def build_session_record(
    user_id: str,
    orchestrator: MultiProviderOrchestrator,
    started_at: datetime,
    ended_at: Optional[datetime] = None,
) -> SttSessionRecord:
    return SttSessionRecord(
        session_id=orchestrator.session_id,
        user_id=user_id,
        started_at=started_at,
        ended_at=ended_at,
        config=orchestrator.config,
        final_snapshot=orchestrator.current_snapshot(),
        provider_metrics=orchestrator.provider_metrics(),
    )
