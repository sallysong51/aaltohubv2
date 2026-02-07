"""
Authentication routes
"""
import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)
from app.models import (
    SendCodeRequest, SendCodeResponse,
    VerifyCodeRequest, Verify2FARequest,
    AuthResponse, RefreshTokenRequest,
    UserCreate, UserResponse, UserRole
)
from app.auth import create_access_token, create_refresh_token, decode_token, get_current_user, verify_refresh_token
from app.database import get_db
from app.telegram_client import telegram_manager
from app.config import settings

security = HTTPBearer()

# In-memory rate limiters
_send_code_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 3  # max attempts per window per key

_verify_code_attempts: dict[str, list[float]] = defaultdict(list)
_VERIFY_RATE_LIMIT_WINDOW = 300  # 5 minutes
_VERIFY_RATE_LIMIT_MAX = 5  # max attempts per 5 min per key

_RATE_LIMIT_CLEANUP_INTERVAL = 300  # cleanup stale entries every 5 min
_last_cleanup = 0.0


def _cleanup_stale_rate_limits():
    """Remove expired entries from rate limit dicts to prevent memory leak."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _RATE_LIMIT_CLEANUP_INTERVAL:
        return
    _last_cleanup = now
    for store, window in [(_send_code_attempts, _RATE_LIMIT_WINDOW), (_verify_code_attempts, _VERIFY_RATE_LIMIT_WINDOW)]:
        stale_keys = [k for k, v in store.items() if not v or now - v[-1] > window]
        for k in stale_keys:
            del store[k]


def _check_verify_rate_limit(key: str):
    """Rate limit check for verify-code and verify-2fa endpoints."""
    _cleanup_stale_rate_limits()
    now = time.time()
    _verify_code_attempts[key] = [
        t for t in _verify_code_attempts[key] if now - t < _VERIFY_RATE_LIMIT_WINDOW
    ]
    if len(_verify_code_attempts[key]) >= _VERIFY_RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please try again later.")
    _verify_code_attempts[key].append(now)

router = APIRouter(prefix="/auth", tags=["Authentication"])


async def _upsert_user_and_create_tokens(db, user_info: dict, session_string: str) -> tuple:
    """Shared logic: upsert user record, save Telethon session, return (AuthResponse fields).
    Returns (access_token, refresh_token, user).
    """
    # Determine role
    phone = user_info.get("phone_number")
    username = user_info.get("username")
    is_admin = settings.is_admin(phone=phone, username=username)
    role = UserRole.ADMIN if is_admin else UserRole.USER

    logger.info("User role check: telegram_id=%s, is_admin=%s, role=%s",
                user_info.get("telegram_id"), is_admin, role.value)

    # Check if user exists
    existing_user = await asyncio.to_thread(
        lambda: db.table("users").select("*").eq("telegram_id", user_info["telegram_id"]).execute()
    )

    if existing_user.data and len(existing_user.data) > 0:
        user_data = existing_user.data[0]
        user_id = user_data["id"]

        # Preserve existing role if manually changed (e.g. via admin panel)
        # Only upgrade to admin if settings say so; never downgrade an existing admin
        existing_role = user_data.get("role", "user")
        if is_admin:
            effective_role = UserRole.ADMIN.value
        else:
            effective_role = existing_role  # keep whatever role was set

        await asyncio.to_thread(lambda: db.table("users").update({
            "phone_number": user_info.get("phone_number"),
            "username": user_info.get("username"),
            "first_name": user_info.get("first_name"),
            "last_name": user_info.get("last_name"),
            "role": effective_role
        }).eq("id", user_id).execute())
    else:
        new_user = await asyncio.to_thread(lambda: db.table("users").insert({
            "telegram_id": user_info["telegram_id"],
            "phone_number": user_info.get("phone_number"),
            "username": user_info.get("username"),
            "first_name": user_info.get("first_name"),
            "last_name": user_info.get("last_name"),
            "role": role.value
        }).execute())

        user_id = new_user.data[0]["id"]

    # Get updated user data
    user_response = await asyncio.to_thread(
        lambda: db.table("users").select("*").eq("id", user_id).execute()
    )
    user = UserResponse(**user_response.data[0])

    # Create JWT tokens
    access_token = create_access_token({"sub": str(user_id)})
    refresh_token = create_refresh_token({"sub": str(user_id)})

    return access_token, refresh_token, user, user_id


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(request: SendCodeRequest, req: Request):
    """Send authentication code to Telegram"""
    # Rate limiting
    _cleanup_stale_rate_limits()
    client_ip = req.client.host if req.client else "unknown"
    rate_key = f"{client_ip}:{request.phone_or_username}"
    now = time.time()
    _send_code_attempts[rate_key] = [
        t for t in _send_code_attempts[rate_key] if now - t < _RATE_LIMIT_WINDOW
    ]
    if len(_send_code_attempts[rate_key]) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    _send_code_attempts[rate_key].append(now)

    try:
        result = await telegram_manager.send_code(request.phone_or_username)
        return SendCodeResponse(
            success=result["success"],
            message="Code sent successfully",
            phone_code_hash=result["phone_code_hash"],
            requires_2fa=result["requires_2fa"]
        )
    except Exception as e:
        # Telegram manager already raises user-friendly Korean messages
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verify-code", response_model=AuthResponse)
async def verify_code(request: VerifyCodeRequest, req: Request, db=Depends(get_db)):
    """Verify authentication code and sign in"""
    # Rate limit: 5 attempts per phone per 5 minutes
    client_ip = req.client.host if req.client else "unknown"
    _check_verify_rate_limit(f"{client_ip}:{request.phone_or_username}")
    try:
        result = await telegram_manager.verify_code(
            request.phone_or_username,
            request.code,
            request.phone_code_hash
        )

        if result.get("requires_2fa"):
            raise HTTPException(
                status_code=403,
                detail="Two-factor authentication required"
            )

        if not result["success"]:
            raise HTTPException(status_code=400, detail="Verification failed")

        access_token, refresh_token, user, user_id = await _upsert_user_and_create_tokens(
            db, result["user_info"], result["session_string"]
        )

        # Save Telethon session
        await telegram_manager.save_session(user_id, result["session_string"])

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("verify_code error: %s", e)
        raise HTTPException(status_code=500, detail="인증 코드 검증 중 오류가 발생했습니다")


@router.post("/verify-2fa", response_model=AuthResponse)
async def verify_2fa(request: Verify2FARequest, req: Request, db=Depends(get_db)):
    """Verify 2FA password and complete sign in"""
    # Rate limit: 5 attempts per phone per 5 minutes
    client_ip = req.client.host if req.client else "unknown"
    _check_verify_rate_limit(f"{client_ip}:{request.phone_or_username}")
    try:
        result = await telegram_manager.verify_2fa(
            request.phone_or_username,
            request.password
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail="2FA verification failed")

        access_token, refresh_token, user, user_id = await _upsert_user_and_create_tokens(
            db, result["user_info"], result["session_string"]
        )

        # Save Telethon session
        await telegram_manager.save_session(user_id, result["session_string"])

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("verify_2fa error: %s", e)
        raise HTTPException(status_code=500, detail="2FA 검증 중 오류가 발생했습니다")


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token(request: RefreshTokenRequest, db=Depends(get_db)):
    """Refresh access token using refresh token"""
    try:
        payload = await verify_refresh_token(request.refresh_token, db=db)
        user_id = payload.get("sub")

        user_response = await asyncio.to_thread(
            lambda: db.table("users").select("*").eq("id", user_id).execute()
        )
        if not user_response.data or len(user_response.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")

        user = UserResponse(**user_response.data[0])

        access_token = create_access_token({"sub": str(user_id)})
        new_refresh_token = create_refresh_token({"sub": str(user_id)})

        # Revoke old refresh token (single-use)
        old_jti = payload.get("jti")
        if old_jti:
            try:
                await asyncio.to_thread(lambda: db.table("revoked_tokens").insert({
                    "jti": old_jti,
                    "user_id": str(user_id),
                    "expires_at": datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc).isoformat(),
                }).execute())
            except Exception:
                pass  # Non-critical

        return AuthResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Token refresh error: %s", e)
        raise HTTPException(status_code=401, detail="Token refresh failed")


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserResponse = Depends(get_current_user)):
    """Get current user info"""
    return current_user


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Security(security),
    db=Depends(get_db),
):
    """Logout — revoke current token server-side"""
    try:
        token = credentials.credentials
        payload = decode_token(token)
        jti = payload.get("jti")
        if jti:
            await asyncio.to_thread(lambda: db.table("revoked_tokens").insert({
                "jti": jti,
                "user_id": payload.get("sub"),
                "expires_at": datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc).isoformat(),
            }).execute())
    except Exception:
        pass  # Best effort revocation
    return {"success": True, "message": "Logged out successfully"}
