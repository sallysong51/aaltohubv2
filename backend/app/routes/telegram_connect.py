"""
Telegram connection management routes.
Allows authenticated users to link/unlink multiple Telegram accounts.
Separate from /auth — does NOT create users or issue JWTs.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Literal

from app.auth import get_current_user
from app.models import UserResponse, SendCodeRequest, SendCodeResponse, VerifyCodeRequest, Verify2FARequest
from app.telegram_client import telegram_manager, TelegramAuthError
from app.database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["Telegram Connections"])

# Health check cache: {user_id: ({connections: [...], checked_at: ...}, timestamp)}
_health_cache: Dict[str, tuple[dict, float]] = {}
_HEALTH_CACHE_TTL = 600.0  # 10 minutes (increased from 5min for less frequent checks)


class TelegramConnectionResponse(BaseModel):
    id: str
    telegram_user_id: int
    phone_masked: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    connected_at: Optional[str] = None
    last_used_at: Optional[str] = None


class ConnectVerifyResponse(BaseModel):
    success: bool
    connection: TelegramConnectionResponse


class ConnectionHealthStatus(BaseModel):
    connection_id: str
    status: Literal["healthy", "expired", "invalid", "unreachable"]
    telegram_user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_masked: Optional[str] = None
    last_checked_at: str
    error_message: Optional[str] = None


class ConnectionsHealthResponse(BaseModel):
    connections: List[ConnectionHealthStatus]
    checked_at: str


@router.post("/send-code", response_model=SendCodeResponse)
async def connect_send_code(
    request: SendCodeRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Send Telegram verification code (for linking, not login)."""
    try:
        result = await telegram_manager.send_code(request.phone_or_username)
        return SendCodeResponse(
            success=result["success"],
            phone_code_hash=result.get("phone_code_hash"),
            message=result.get("message"),
            requires_2fa=result.get("requires_2fa", False),
        )
    except TelegramAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.exception("connect_send_code error for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="인증 코드 전송에 실패했습니다.")


@router.post("/verify-code", response_model=ConnectVerifyResponse)
async def connect_verify_code(
    request: VerifyCodeRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Verify code and link Telegram account to current user.
    Does NOT create a new user or issue new JWT tokens."""
    try:
        result = await telegram_manager.verify_code(
            request.phone_or_username,
            request.code,
            request.phone_code_hash,
        )

        if result.get("requires_2fa"):
            raise HTTPException(status_code=403, detail="Two-factor authentication required")

        if not result["success"]:
            raise HTTPException(status_code=400, detail="Verification failed")

        user_info = result["user_info"]
        session_string = result["session_string"]

        # Save connection to telegram_connections (encrypted with current user's ID as AAD)
        connection_id = await telegram_manager.save_connection(
            user_id=str(current_user.id),
            telegram_user_id=user_info["telegram_id"],
            session_string=session_string,
            phone_masked=_mask_phone(user_info.get("phone_number")),
            username=user_info.get("username"),
            first_name=user_info.get("first_name"),
            last_name=user_info.get("last_name"),
        )

        return ConnectVerifyResponse(
            success=True,
            connection=TelegramConnectionResponse(
                id=connection_id,
                telegram_user_id=user_info["telegram_id"],
                phone_masked=_mask_phone(user_info.get("phone_number")),
                username=user_info.get("username"),
                first_name=user_info.get("first_name"),
                last_name=user_info.get("last_name"),
            ),
        )
    except HTTPException:
        raise
    except TelegramAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.exception("connect_verify_code error for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="텔레그램 연결에 실패했습니다.")


@router.post("/verify-2fa", response_model=ConnectVerifyResponse)
async def connect_verify_2fa(
    request: Verify2FARequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Verify 2FA and link Telegram account to current user."""
    try:
        result = await telegram_manager.verify_2fa(
            request.phone_or_username,
            request.password,
            request.phone_code_hash,
        )

        if not result["success"]:
            raise HTTPException(status_code=400, detail="2FA verification failed")

        user_info = result["user_info"]
        session_string = result["session_string"]

        connection_id = await telegram_manager.save_connection(
            user_id=str(current_user.id),
            telegram_user_id=user_info["telegram_id"],
            session_string=session_string,
            phone_masked=_mask_phone(user_info.get("phone_number")),
            username=user_info.get("username"),
            first_name=user_info.get("first_name"),
            last_name=user_info.get("last_name"),
        )

        return ConnectVerifyResponse(
            success=True,
            connection=TelegramConnectionResponse(
                id=connection_id,
                telegram_user_id=user_info["telegram_id"],
                phone_masked=_mask_phone(user_info.get("phone_number")),
                username=user_info.get("username"),
                first_name=user_info.get("first_name"),
                last_name=user_info.get("last_name"),
            ),
        )
    except HTTPException:
        raise
    except TelegramAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.exception("connect_verify_2fa error for user %s", current_user.id)
        raise HTTPException(status_code=500, detail="텔레그램 2FA 인증에 실패했습니다.")


@router.get("/connections", response_model=List[TelegramConnectionResponse])
async def list_connections(
    current_user: UserResponse = Depends(get_current_user),
):
    """List all Telegram accounts linked to current user."""
    connections = await telegram_manager.get_connections(str(current_user.id))
    return [
        TelegramConnectionResponse(
            id=str(c["id"]),
            telegram_user_id=c["telegram_user_id"],
            phone_masked=c.get("phone_masked"),
            username=c.get("username"),
            first_name=c.get("first_name"),
            last_name=c.get("last_name"),
            connected_at=str(c["connected_at"]) if c.get("connected_at") else None,
            last_used_at=str(c["last_used_at"]) if c.get("last_used_at") else None,
        )
        for c in connections
    ]


@router.delete("/connections/{connection_id}")
async def remove_connection(
    connection_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """Unlink a Telegram account from current user."""
    deleted = await telegram_manager.delete_connection(connection_id, str(current_user.id))
    if not deleted:
        raise HTTPException(status_code=404, detail="연결을 찾을 수 없습니다.")
    return {"success": True, "message": "텔레그램 연결이 해제되었습니다."}


@router.get("/connections/health", response_model=ConnectionsHealthResponse)
async def get_connections_health(
    current_user: UserResponse = Depends(get_current_user),
):
    """Check health status of all Telegram connections for current user.
    Validates each session by calling get_me() on Telegram API.
    Results are cached for 10 minutes to avoid excessive API calls.

    Performance optimizations:
    - 3s per-connection timeout for fast failure
    - 2s get_me() timeout (down from 5s)
    - 3s connect() timeout (down from 10s)
    - Max 5 concurrent validations (up from 3)
    """
    user_id = str(current_user.id)
    now = time.time()

    # Check cache first
    if user_id in _health_cache:
        cached_data, timestamp = _health_cache[user_id]
        if now - timestamp < _HEALTH_CACHE_TTL:
            return ConnectionsHealthResponse(**cached_data)

    try:
        # Fetch all connections for user
        connections = await telegram_manager.get_connections(user_id)

        if not connections:
            result = {
                "connections": [],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            _health_cache[user_id] = (result, now)
            return ConnectionsHealthResponse(**result)

        # Validate connections in parallel with semaphore limit (max 5 concurrent, up from 3)
        semaphore = asyncio.Semaphore(5)
        tasks = [
            _validate_single_connection(semaphore, connection)
            for connection in connections
        ]
        health_statuses = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions from gather
        validated = []
        for i, status in enumerate(health_statuses):
            if isinstance(status, Exception):
                logger.exception(
                    "Exception validating connection %s for user %s",
                    connections[i]["id"],
                    user_id,
                )
                # Fallback: mark as unreachable on unexpected error
                validated.append(
                    ConnectionHealthStatus(
                        connection_id=str(connections[i]["id"]),
                        status="unreachable",
                        telegram_user_id=connections[i]["telegram_user_id"],
                        username=connections[i].get("username"),
                        first_name=connections[i].get("first_name"),
                        last_name=connections[i].get("last_name"),
                        phone_masked=connections[i].get("phone_masked"),
                        last_checked_at=datetime.now(timezone.utc).isoformat(),
                        error_message="예기치 않은 오류",
                    )
                )
            else:
                validated.append(status)

        checked_at = datetime.now(timezone.utc).isoformat()
        result = {
            "connections": [c.model_dump() for c in validated],
            "checked_at": checked_at,
        }

        # Cache result
        _health_cache[user_id] = (result, now)

        # Cleanup old cache entries if too many (keep max 100)
        if len(_health_cache) > 100:
            oldest_key = min(
                _health_cache.keys(), key=lambda k: _health_cache[k][1]
            )
            del _health_cache[oldest_key]

        return ConnectionsHealthResponse(**result)

    except Exception as e:
        logger.exception("get_connections_health error for user %s", user_id)
        raise HTTPException(
            status_code=500, detail="텔레그램 세션 상태를 확인할 수 없습니다."
        )


def _mask_phone(phone: str | None) -> str | None:
    """Mask phone number: +358123456789 → +358***6789"""
    if not phone or len(phone) < 8:
        return phone
    return phone[:4] + "***" + phone[-4:]


async def _validate_single_connection(
    semaphore: asyncio.Semaphore, connection: dict
) -> ConnectionHealthStatus:
    """Validate a single Telegram connection by calling get_me().
    Returns health status: healthy, expired, invalid, or unreachable.

    Performance: 3s total timeout per connection (was unlimited).
    - Connect: 3s max (down from 10s in get_user_client_by_connection)
    - get_me(): 2s max (down from 5s)
    """
    async with semaphore:
        connection_id = str(connection["id"])
        user_id = str(connection["user_id"])
        telegram_user_id = connection["telegram_user_id"]
        username = connection.get("username")
        first_name = connection.get("first_name")
        last_name = connection.get("last_name")
        phone_masked = connection.get("phone_masked")
        now_iso = datetime.now(timezone.utc).isoformat()

        client = None
        try:
            # Entire validation wrapped in 3s timeout (fast failure)
            async def _do_validation():
                nonlocal client
                # Get client via custom fast path (3s connect timeout instead of 10s)
                client = await telegram_manager.get_user_client_by_connection_fast(
                    connection_id, user_id
                )
                # Verify session is valid by calling get_me() with 2s timeout (down from 5s)
                await asyncio.wait_for(client.get_me(), timeout=2.0)

            await asyncio.wait_for(_do_validation(), timeout=3.0)

            return ConnectionHealthStatus(
                connection_id=connection_id,
                status="healthy",
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                phone_masked=phone_masked,
                last_checked_at=now_iso,
                error_message=None,
            )

        except asyncio.TimeoutError:
            return ConnectionHealthStatus(
                connection_id=connection_id,
                status="unreachable",
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                phone_masked=phone_masked,
                last_checked_at=now_iso,
                error_message="텔레그램 서버 연결 시간 초과",
            )
        except TelegramAuthError as e:
            # Map TelegramAuthError to health status
            error_str = str(e.detail).lower()
            if "만료" in error_str or "session revoked" in error_str.lower():
                status = "expired"
            elif "auth" in error_str or "unauthorized" in error_str:
                status = "expired"
            else:
                status = "invalid"

            logger.debug(
                "Connection %s validation failed: %s", connection_id, e.detail
            )

            return ConnectionHealthStatus(
                connection_id=connection_id,
                status=status,
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                phone_masked=phone_masked,
                last_checked_at=now_iso,
                error_message=e.detail,
            )
        except Exception as e:
            error_str = str(e).lower()

            # Detect expired/invalid session based on error message
            if "auth key" in error_str or "unauthorized" in error_str:
                status = "expired"
                error_msg = "세션 만료됨"
            elif "session" in error_str:
                status = "invalid"
                error_msg = "세션 오류"
            else:
                status = "unreachable"
                error_msg = f"연결 오류: {type(e).__name__}"

            logger.debug(
                "Connection %s validation failed: %s", connection_id, error_str
            )

            return ConnectionHealthStatus(
                connection_id=connection_id,
                status=status,
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                phone_masked=phone_masked,
                last_checked_at=now_iso,
                error_message=error_msg,
            )
        finally:
            # Always disconnect client
            if client and client.is_connected():
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.debug("Error disconnecting client: %s", e)
