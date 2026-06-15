"""Authentication API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from src.auth.dependencies import get_current_user
from src.auth.jwt import create_access_token
from src.auth.password import hash_password, verify_password
from src.db.mongodb import col_users, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


def _serialize_user(user: dict) -> dict:
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
    }


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, db=Depends(get_db)) -> AuthResponse:
    existing = await col_users(db).find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    now = datetime.now(timezone.utc)
    doc = {
        "email": body.email.lower(),
        "password_hash": hash_password(body.password),
        "created_at": now,
        "last_login": None,
    }
    result = await col_users(db).insert_one(doc)
    user_id = str(result.inserted_id)
    token = create_access_token(user_id)

    return AuthResponse(
        access_token=token,
        user={
            "id": user_id,
            "email": doc["email"],
            "created_at": now.isoformat(),
            "last_login": None,
        },
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db=Depends(get_db)) -> AuthResponse:
    user = await col_users(db).find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    now = datetime.now(timezone.utc)
    await col_users(db).update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login": now}},
    )

    token = create_access_token(str(user["_id"]))
    return AuthResponse(
        access_token=token,
        user={
            "id": str(user["_id"]),
            "email": user["email"],
            "created_at": user.get("created_at").isoformat()
            if user.get("created_at")
            else None,
            "last_login": now.isoformat(),
        },
    )


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db=Depends(get_db)) -> dict:
    user = await col_users(db).find_one({"email": body.email.lower()})
    if user:
        return {
            "message": "If an account exists, password reset instructions have been sent.",
        }
    return {
        "message": "If an account exists, password reset instructions have been sent.",
    }


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)) -> dict:
    return _serialize_user(current_user)
