"""
Authentication routes
"""
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)
from app.models import (
    SendCodeRequest, SendCodeResponse,
    VerifyCodeRequest, Verify2FARequest,
    AuthResponse, RefreshTokenRequest,
    EmailLoginRequest, EmailSignupRequest,
    UserResponse, UserRole
)
from app.auth import create_access_token, create_refresh_token, decode_token, get_current_user, verify_refresh_token, invalidate_revocation_cache, is_admin_credential
from app.database import db
from app.telegram_client import telegram_manager, TelegramAuthError
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


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set refresh token as httpOnly cookie (prevents XSS theft)."""
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN or None,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Remove refresh token cookie on logout."""
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN or None,
        path="/api/auth",
    )


async def _upsert_user_and_create_tokens(user_info: dict, session_string: str) -> tuple:
    """Shared logic: upsert user record, save Telethon session, return (AuthResponse fields).
    Returns (access_token, refresh_token, user).
    """
    # Determine role (check admin_credentials table first, then fallback to env vars for backwards compatibility)
    phone = user_info.get("phone_number")
    username = user_info.get("username")
    is_admin = await is_admin_credential(phone=phone, username=username)
    # Fallback to env vars for backwards compatibility (during migration period)
    if not is_admin:
        is_admin = settings.is_admin(phone=phone, username=username)
    role = UserRole.ADMIN if is_admin else UserRole.USER

    logger.info("User role check: telegram_id=%s, is_admin=%s, role=%s",
                user_info.get("telegram_id"), is_admin, role.value)

    # Check if user exists
    existing_user = await db.fetchrow(
        "SELECT * FROM users WHERE telegram_id = $1",
        user_info["telegram_id"],
    )

    if existing_user:
        user_id = existing_user["id"]

        # Preserve existing role if manually changed (e.g. via admin panel)
        # Only upgrade to admin if settings say so; never downgrade an existing admin
        existing_role = existing_user.get("role", "user")
        if is_admin:
            effective_role = UserRole.ADMIN.value
        else:
            effective_role = existing_role  # keep whatever role was set

        await db.execute(
            """UPDATE users SET phone_number = $1, username = $2, first_name = $3,
               last_name = $4, role = $5 WHERE id = $6""",
            user_info.get("phone_number"),
            user_info.get("username"),
            user_info.get("first_name"),
            user_info.get("last_name"),
            effective_role,
            user_id,
        )
    else:
        row = await db.fetchrow(
            """INSERT INTO users (telegram_id, phone_number, username, first_name, last_name, role)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            user_info["telegram_id"],
            user_info.get("phone_number"),
            user_info.get("username"),
            user_info.get("first_name"),
            user_info.get("last_name"),
            role.value,
        )
        user_id = row["id"]

    # Get updated user data
    user_row = await db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    user = UserResponse(**dict(user_row))

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
    except TelegramAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.exception("send_code unexpected error")
        raise HTTPException(status_code=500, detail="인증 코드 전송에 실패했습니다. 잠시 후 다시 시도해 주세요.")


@router.post("/verify-code", response_model=AuthResponse)
async def verify_code(request: VerifyCodeRequest, req: Request, response: Response):
    """Verify authentication code and sign in"""
    # Point 4: DB health guard (defense in depth — middleware also blocks)
    if not db.is_connected:
        raise HTTPException(status_code=503, detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")

    # Rate limit: 5 attempts per phone per 5 minutes
    client_ip = req.client.host if req.client else "unknown"
    rate_key = f"{client_ip}:{request.phone_or_username}"
    _check_verify_rate_limit(rate_key)
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

        # Point 13: upsert is mandatory (503 on DB failure)
        access_token, refresh_token, user, user_id = await _upsert_user_and_create_tokens(
            result["user_info"], result["session_string"]
        )

        # Point 12: session save is best-effort (non-fatal)
        try:
            await telegram_manager.save_session(user_id, result["session_string"])
        except Exception as e:
            logger.error("Failed to save Telethon session for user %s: %s", user_id, e)

        _set_refresh_cookie(response, refresh_token)
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except TelegramAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except RuntimeError as e:
        # Point 9: DB pool errors → 503 (not 500) + rollback rate limit
        if "pool not initialized" in str(e):
            _verify_code_attempts.get(rate_key, []).pop() if _verify_code_attempts.get(rate_key) else None
            logger.error("verify_code DB unavailable for user=%s", request.phone_or_username)
            raise HTTPException(status_code=503, detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")
        logger.exception("verify_code unexpected error for user=%s", request.phone_or_username)
        raise HTTPException(status_code=500, detail="인증 코드 검증 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        # Point 5: no internal details leaked, Point 6: no print()
        logger.exception("verify_code unexpected error for user=%s", request.phone_or_username)
        raise HTTPException(status_code=500, detail="인증 코드 검증 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")


@router.post("/verify-2fa", response_model=AuthResponse)
async def verify_2fa(request: Verify2FARequest, req: Request, response: Response):
    """Verify 2FA password and complete sign in"""
    if not db.is_connected:
        raise HTTPException(status_code=503, detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")

    # Rate limit: 5 attempts per phone per 5 minutes
    client_ip = req.client.host if req.client else "unknown"
    rate_key = f"{client_ip}:{request.phone_or_username}"
    _check_verify_rate_limit(rate_key)
    try:
        result = await telegram_manager.verify_2fa(
            request.phone_or_username,
            request.password
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail="2FA verification failed")

        access_token, refresh_token, user, user_id = await _upsert_user_and_create_tokens(
            result["user_info"], result["session_string"]
        )

        try:
            await telegram_manager.save_session(user_id, result["session_string"])
        except Exception as e:
            logger.error("Failed to save Telethon session for user %s: %s", user_id, e)

        _set_refresh_cookie(response, refresh_token)
        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=user
        )
    except HTTPException:
        raise
    except TelegramAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except RuntimeError as e:
        if "pool not initialized" in str(e):
            _verify_code_attempts.get(rate_key, []).pop() if _verify_code_attempts.get(rate_key) else None
            logger.error("verify_2fa DB unavailable for user=%s", request.phone_or_username)
            raise HTTPException(status_code=503, detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")
        logger.exception("verify_2fa unexpected error")
        raise HTTPException(status_code=500, detail="2FA 검증 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception as e:
        logger.exception("verify_2fa unexpected error")
        raise HTTPException(status_code=500, detail="2FA 검증 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")


@router.post("/refresh", response_model=AuthResponse)
async def refresh_token_endpoint(
    req: Request,
    response: Response,
    request: RefreshTokenRequest = None,
):
    """Refresh access token using refresh token (from body or httpOnly cookie)."""
    if not db.is_connected:
        raise HTTPException(status_code=503, detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")
    try:
        # Accept refresh token from cookie (preferred) or body (legacy)
        token_value = req.cookies.get("refresh_token")
        if not token_value and request and request.refresh_token:
            token_value = request.refresh_token
        if not token_value:
            raise HTTPException(status_code=401, detail="Refresh token required")
        payload = await verify_refresh_token(token_value)
        user_id = payload.get("sub")

        user_row = await db.fetchrow(
            "SELECT * FROM users WHERE id = $1", int(user_id)
        )
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        user = UserResponse(**dict(user_row))

        # Revoke old refresh token BEFORE issuing new ones (single-use)
        old_jti = payload.get("jti")
        if old_jti:
            try:
                await db.execute(
                    """INSERT INTO revoked_tokens (jti, user_id, expires_at)
                       VALUES ($1, $2, $3) ON CONFLICT (jti) DO NOTHING""",
                    old_jti,
                    str(user_id),
                    datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc),
                )
                invalidate_revocation_cache(old_jti)
            except Exception as e:
                logger.error("Failed to revoke old refresh token jti=%s: %s", old_jti, e)
                raise HTTPException(status_code=500, detail="Token refresh failed")

        access_token = create_access_token({"sub": str(user_id)})
        new_refresh_token = create_refresh_token({"sub": str(user_id)})

        _set_refresh_cookie(response, new_refresh_token)
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
    response: Response,
    credentials: HTTPAuthorizationCredentials = Security(security),
):
    """Logout — revoke current token server-side (best-effort if DB down)"""
    try:
        token = credentials.credentials
        payload = decode_token(token)
        jti = payload.get("jti")
        if jti:
            await db.execute(
                """INSERT INTO revoked_tokens (jti, user_id, expires_at)
                   VALUES ($1, $2, $3) ON CONFLICT (jti) DO NOTHING""",
                jti,
                payload.get("sub"),
                datetime.fromtimestamp(payload.get("exp", 0), tz=timezone.utc),
            )
            invalidate_revocation_cache(jti)
    except Exception:
        pass  # Best effort revocation
    _clear_refresh_cookie(response)
    return {"success": True, "message": "Logged out successfully"}


@router.post("/signup-email", response_model=AuthResponse)
async def signup_email(request: EmailSignupRequest):
    """Sign up with email/password (no Telegram required).

    This endpoint creates a completely new user account with just email and password.
    No Telegram account is needed. User can optionally connect Telegram later.

    Args:
        request: EmailSignupRequest with email, password, first_name, last_name

    Returns:
        AuthResponse with access_token, refresh_token, and user

    Raises:
        HTTPException 400: Email already exists or validation error
        HTTPException 500: Database or Supabase error
    """
    from app.supabase_auth import supabase_auth_manager

    if not db.is_connected:
        raise HTTPException(
            status_code=503,
            detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요"
        )

    try:
        # Check if email already exists in Supabase Auth
        existing_auth_user = await supabase_auth_manager.get_user_by_email(request.email)
        if existing_auth_user:
            raise HTTPException(
                status_code=400,
                detail="이미 사용 중인 이메일입니다"
            )

        # Create Supabase Auth user
        auth_result = await supabase_auth_manager.create_user(
            email=request.email,
            password=request.password,
            metadata={
                "signup_method": "email",
                "first_name": request.first_name,
                "last_name": request.last_name,
            }
        )

        if not auth_result["success"]:
            error_msg = auth_result.get("error", "Unknown error")
            logger.error("Supabase Auth user creation failed: %s", error_msg)
            raise HTTPException(
                status_code=400,
                detail=f"회원가입에 실패했습니다: {error_msg}"
            )

        auth_user_id = auth_result["auth_user_id"]

        # Create public users entry (email-only user, no telegram_id)
        user_row = await db.fetchrow(
            """INSERT INTO users
               (telegram_id, first_name, last_name, role, auth_user_id, email_link_required, email_linked_at)
               VALUES (NULL, $1, $2, $3, $4, FALSE, NOW())
               RETURNING *""",
            request.first_name,
            request.last_name,
            UserRole.USER.value,
            auth_user_id
        )

        if not user_row:
            raise HTTPException(
                status_code=500,
                detail="사용자 생성에 실패했습니다"
            )

        user_id = user_row["id"]
        user = UserResponse(**dict(user_row))

        # Create custom JWT tokens
        access_token = create_access_token({"sub": str(user_id)})
        refresh_token_val = create_refresh_token({"sub": str(user_id)})

        logger.info(
            "New user signed up with email: user_id=%s, email=%s",
            user_id, request.email
        )

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token_val,
            user=user
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Email signup error for email=%s", request.email)
        raise HTTPException(
            status_code=500,
            detail="회원가입에 실패했습니다. 잠시 후 다시 시도해주세요"
        )


@router.post("/login-email", response_model=AuthResponse)
async def login_email(request: EmailLoginRequest):
    """Login with email/password via Supabase Auth.

    This endpoint authenticates users who have linked their email via
    Supabase Auth. It:
    1. Authenticates with Supabase (email + password)
    2. Looks up public user by auth_user_id
    3. Creates custom JWT tokens for API access
    4. Returns tokens + user info

    Args:
        request: EmailLoginRequest with email and password

    Returns:
        AuthResponse with access_token, refresh_token, and user

    Raises:
        HTTPException 401: Invalid credentials
        HTTPException 404: Account not found (email not linked)
        HTTPException 500: Database or Supabase error
    """
    from app.supabase_auth import supabase_auth_manager

    if not db.is_connected:
        raise HTTPException(
            status_code=503,
            detail="서비스가 일시적으로 사용할 수 없습니다. 잠시 후 다시 시도해주세요"
        )

    try:
        # Authenticate with Supabase Auth
        auth_result = await supabase_auth_manager.sign_in_with_password(
            email=request.email,
            password=request.password
        )

        if not auth_result["success"]:
            raise HTTPException(
                status_code=401,
                detail="이메일 또는 비밀번호가 올바르지 않습니다"
            )

        auth_user = auth_result["user"]
        auth_user_id = auth_user["id"]

        # Look up public user by auth_user_id
        user_row = await db.fetchrow(
            "SELECT * FROM users WHERE auth_user_id = $1",
            auth_user_id
        )

        if not user_row:
            logger.warning(
                "Email login failed: no user found with auth_user_id=%s, email=%s",
                auth_user_id, request.email
            )
            raise HTTPException(
                status_code=404,
                detail="계정을 찾을 수 없습니다. 먼저 텔레그램 계정을 연결해주세요"
            )

        user_id = user_row["id"]
        user = UserResponse(**dict(user_row))

        # Create custom JWT tokens (we still use JWT for API auth during transition)
        access_token = create_access_token({"sub": str(user_id)})
        refresh_token_val = create_refresh_token({"sub": str(user_id)})

        # Log diagnostic info about Telegram session status
        telegram_session_status = "unknown"
        try:
            tc_exists = await db.fetchval(
                "SELECT COUNT(*) FROM telegram_connections WHERE user_id = $1",
                user_id
            )
            ts_exists = await db.fetchval(
                "SELECT COUNT(*) FROM telethon_sessions WHERE user_id = $1",
                user_id
            )
            telegram_session_status = f"telegram_connections={tc_exists}, telethon_sessions={ts_exists}"
        except Exception as e:
            logger.warning("Failed to query session status: %s", e)

        logger.info(
            "User %s logged in via email: %s (session_status: %s)",
            user_id, request.email, telegram_session_status
        )

        return AuthResponse(
            access_token=access_token,
            refresh_token=refresh_token_val,
            user=user
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Email login error for email=%s", request.email)
        raise HTTPException(
            status_code=500,
            detail="로그인에 실패했습니다. 잠시 후 다시 시도해주세요"
        )
