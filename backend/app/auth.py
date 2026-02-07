"""
Authentication and JWT utilities
"""
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.database import db as database


security = HTTPBearer()

# In-memory TTL cache for non-revoked JTIs to avoid DB hit on every request.
# Key: jti string, Value: timestamp when cached.
# If a JTI is in this cache, it was verified as non-revoked within the TTL window.
_REVOCATION_CACHE_TTL = 30  # seconds — short enough to catch revocations promptly
_REVOCATION_CACHE_MAX = 5000
_revocation_cache: Dict[str, float] = {}


def _check_revocation_cache(jti: str) -> Optional[bool]:
    """Return True if known non-revoked, None if unknown (needs DB check)."""
    cached_at = _revocation_cache.get(jti)
    if cached_at is not None:
        if time.monotonic() - cached_at < _REVOCATION_CACHE_TTL:
            return True
        del _revocation_cache[jti]
    return None


def _mark_not_revoked(jti: str) -> None:
    """Cache a JTI as non-revoked."""
    if len(_revocation_cache) >= _REVOCATION_CACHE_MAX:
        # Evict oldest 20% entries
        cutoff = len(_revocation_cache) // 5
        sorted_keys = sorted(_revocation_cache, key=_revocation_cache.get)
        for k in sorted_keys[:cutoff]:
            del _revocation_cache[k]
    _revocation_cache[jti] = time.monotonic()


def invalidate_revocation_cache(jti: str) -> None:
    """Remove a JTI from the non-revoked cache (called on logout/revoke)."""
    _revocation_cache.pop(jti, None)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire, "type": "access", "jti": str(uuid.uuid4())})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """Create JWT refresh token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh", "jti": str(uuid.uuid4())})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Dict:
    """Decode and verify JWT token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰입니다")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> "UserResponse":
    """Get current authenticated user from JWT token"""
    from app.models import UserResponse, UserRole
    token = credentials.credentials
    payload = decode_token(token)

    # Check token type
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # Get user ID from payload
    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    # Check access token revocation (P0-1.7: logout must actually revoke)
    # Uses in-memory TTL cache to avoid DB round-trip on every request.
    jti = payload.get("jti")
    if jti:
        cached = _check_revocation_cache(jti)
        if cached is None:
            # Not in cache — must check DB
            try:
                revoked = await database.fetchrow(
                    "SELECT id FROM revoked_tokens WHERE jti = $1", jti
                )
                if revoked:
                    raise HTTPException(status_code=401, detail="Token has been revoked")
                _mark_not_revoked(jti)
            except HTTPException:
                raise
            except Exception:
                pass  # DB error should not block auth

    # Fetch user from database
    try:
        row = await database.fetchrow(
            "SELECT * FROM users WHERE id = $1", int(user_id)
        )
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        return UserResponse(**dict(row))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="사용자 정보 조회 중 오류가 발생했습니다")


async def is_admin_credential(phone: Optional[str] = None, username: Optional[str] = None) -> bool:
    """Check if phone or username exists in admin_credentials table.

    Used during login to determine if a user should be granted admin role.
    Returns True if the credentials match an admin_credentials entry.
    """
    if not phone and not username:
        return False

    try:
        result = await database.fetchval(
            """SELECT EXISTS(
                SELECT 1 FROM admin_credentials
                WHERE ($1::TEXT IS NOT NULL AND phone_number = $1)
                   OR ($2::TEXT IS NOT NULL AND username = $2)
            )""",
            phone,
            username,
        )
        return bool(result)
    except Exception as e:
        # If table doesn't exist yet (first startup) or DB error, return False
        # This allows graceful degradation until the table is created
        return False


async def get_current_admin_user(
    current_user = Depends(get_current_user)
) -> "UserResponse":
    """Verify that current user is an admin"""
    from app.models import UserRole
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def verify_refresh_token(refresh_token: str) -> Dict:
    """Verify refresh token and return payload. Checks revocation via asyncpg."""
    payload = decode_token(refresh_token)

    # Check token type
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # Check revocation
    jti = payload.get("jti")
    if jti:
        try:
            revoked = await database.fetchrow(
                "SELECT id FROM revoked_tokens WHERE jti = $1", jti
            )
            if revoked:
                raise HTTPException(status_code=401, detail="Token has been revoked")
        except HTTPException:
            raise
        except Exception:
            pass  # DB error should not block auth

    return payload
