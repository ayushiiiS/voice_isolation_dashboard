"""MongoDB connection and collection helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


def get_mongodb_uri() -> str:
    uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    db_name = os.getenv("MONGODB_DB", "voice_isolation")
    if "?" in uri:
        return uri
    return f"{uri}/{db_name}"


async def connect_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is not None:
        return _db

    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri or "USER:PASSWORD" in uri or uri.endswith("cluster.mongodb.net"):
        raise RuntimeError(
            "Invalid MONGODB_URI. Set a real Atlas connection string in .env, e.g.\n"
            "MONGODB_URI=mongodb+srv://<user>:<password>@main-as1.8sh5xu.mongodb.net"
        )

    db_name = os.getenv("MONGODB_DB", "voice_isolation")
    logger.info("Connecting to MongoDB database: %s", db_name)
    _client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
    _db = _client[db_name]
    await _ensure_indexes(_db)
    return _db


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


async def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        return await connect_db()
    return _db


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.users.create_index("email", unique=True)
    await db.jobs.create_index("user_id")
    await db.jobs.create_index("status")
    await db.jobs.create_index("created_at")
    await db.recordings.create_index("job_id")
    await db.analytics.create_index("recording_id", unique=True)
    await db.reports.create_index("recording_id")
    await db.stt_sessions.create_index("user_id")
    await db.stt_sessions.create_index("session_id", unique=True)
    await db.stt_sessions.create_index("started_at")


def col_users(db: AsyncIOMotorDatabase):
    return db.users


def col_jobs(db: AsyncIOMotorDatabase):
    return db.jobs


def col_recordings(db: AsyncIOMotorDatabase):
    return db.recordings


def col_analytics(db: AsyncIOMotorDatabase):
    return db.analytics


def col_reports(db: AsyncIOMotorDatabase):
    return db.reports


def col_stt_sessions(db: AsyncIOMotorDatabase):
    return db.stt_sessions


def col_stt_accuracy_metrics(db: AsyncIOMotorDatabase):
    return db.stt_accuracy_metrics
