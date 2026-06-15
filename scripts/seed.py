#!/usr/bin/env python3
"""Seed database with a demo user and sample job metadata."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bson import ObjectId
from dotenv import load_dotenv

load_dotenv()

from src.auth.password import hash_password
from src.db.mongodb import col_jobs, col_users, connect_db, get_db


async def seed() -> None:
    await connect_db()
    db = await get_db()

    email = os.getenv("SEED_EMAIL", "demo@voiceisolation.app")
    password = os.getenv("SEED_PASSWORD", "demo12345")

    existing = await col_users(db).find_one({"email": email})
    if existing:
        print(f"User already exists: {email} (id={existing['_id']})")
        user_id = str(existing["_id"])
    else:
        now = datetime.now(timezone.utc)
        result = await col_users(db).insert_one(
            {
                "email": email,
                "password_hash": hash_password(password),
                "created_at": now,
                "last_login": None,
            }
        )
        user_id = str(result.inserted_id)
        print(f"Created demo user: {email} / {password} (id={user_id})")

    job_count = await col_jobs(db).count_documents({"user_id": user_id})
    if job_count == 0:
        now = datetime.now(timezone.utc)
        await col_jobs(db).insert_one(
            {
                "_id": ObjectId(),
                "user_id": user_id,
                "source": "seed",
                "file_name": "welcome_sample.csv",
                "status": "completed",
                "progress": 1.0,
                "total_recordings": 0,
                "completed_count": 0,
                "failed_count": 0,
                "created_at": now,
                "updated_at": now,
            }
        )
        print("Created sample job entry")

    print("\nSeed complete. Login with:")
    print(f"  Email:    {email}")
    print(f"  Password: {password}")


if __name__ == "__main__":
    asyncio.run(seed())
