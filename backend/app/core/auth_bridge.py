"""Verify single-use assertions issued only by the trusted Auth.js server."""

import os
import time
from uuid import UUID

import jwt
from fastapi import HTTPException
from redis.asyncio import Redis

from app.core.config import settings


async def consume_assertion(jti: str) -> bool:
    # Shared across workers/restarts; a process-local replay cache is insufficient.
    url = os.environ.get("AUTH_REPLAY_REDIS_URL", "redis://127.0.0.1:6379/0")
    try:
        async with Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2) as client:
            return bool(await client.set(f"auth:assertion:{jti}", "1", nx=True, ex=90))
    except Exception:
        raise HTTPException(503, detail="Authentication temporarily unavailable") from None


async def verify_bridge_assertion(payload) -> dict:
    secret = settings.AUTH_BRIDGE_SECRET
    if not secret or len(secret) < 32:
        raise HTTPException(503, detail="Authentication temporarily unavailable")
    try:
        claims = jwt.decode(
            payload.bridge_assertion or "", secret, algorithms=["HS256"],
            audience="plasma-backend", issuer="plasma-authjs",
            options={"require": ["sub", "email", "email_verified", "iat", "exp", "jti", "iss", "aud"]},
        )
        if not isinstance(claims["jti"], str):
            raise ValueError("Invalid assertion")
        UUID(claims["jti"])
        if (claims["email_verified"] is not True
                or not isinstance(claims["sub"], str) or not claims["sub"].strip()
                or not isinstance(claims["email"], str) or "@" not in claims["email"]
                or claims["exp"] - claims["iat"] > 60
                or claims["iat"] < time.time() - 60
                or payload.google_id != claims["sub"]
                or payload.email.strip().lower() != claims["email"].strip().lower()
                or payload.name != claims.get("name")
                or payload.avatar_url != claims.get("avatar_url")):
            raise ValueError("Invalid assertion")
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, detail="Invalid authentication proof") from None
    if not await consume_assertion(claims["jti"]):
        raise HTTPException(401, detail="Invalid authentication proof")
    return claims
