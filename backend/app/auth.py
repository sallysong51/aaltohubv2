"""
Authentication and JWT utilities
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict
from jose import JWTError, jwt
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import settings
from app.database import get_db
from app.models import UserResponse, UserRole


security = HTTPBearer()


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
    db = Depends(get_db)
) -> UserResponse:
    """Get current authenticated user from JWT token"""
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
    jti = payload.get("jti")
    if jti:
        try:
            revoked = await asyncio.to_thread(
                lambda: db.table("revoked_tokens").select("id").eq("jti", jti).execute()
            )
            if revoked.data:
                raise HTTPException(status_code=401, detail="Token has been revoked")
        except HTTPException:
            raise
        except Exception:
            pass  # DB error should not block auth

    # Fetch user from database
    try:
        response = await asyncio.to_thread(
            lambda: db.table("users").select("*").eq("id", user_id).execute()
        )
        if not response.data or len(response.data) == 0:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = response.data[0]
        return UserResponse(**user_data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="사용자 정보 조회 중 오류가 발생했습니다")


async def get_current_admin_user(
    current_user: UserResponse = Depends(get_current_user)
) -> UserResponse:
    """Verify that current user is an admin"""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def verify_refresh_token(refresh_token: str, db=None) -> Dict:
    """Verify refresh token and return payload. Checks revocation if db provided."""
    payload = decode_token(refresh_token)

    # Check token type
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")

    # Check revocation (P1-1.11: wrapped in asyncio.to_thread to avoid blocking)
    if db:
        jti = payload.get("jti")
        if jti:
            try:
                revoked = await asyncio.to_thread(
                    lambda: db.table("revoked_tokens").select("id").eq("jti", jti).execute()
                )
                if revoked.data:
                    raise HTTPException(status_code=401, detail="Token has been revoked")
            except HTTPException:
                raise
            except Exception:
                pass  # DB error should not block auth

    return payload
