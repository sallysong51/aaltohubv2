"""
Telegram connection management routes.
Allows authenticated users to link/unlink multiple Telegram accounts.
Separate from /auth — does NOT create users or issue JWTs.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from app.auth import get_current_user
from app.models import UserResponse, SendCodeRequest, SendCodeResponse, VerifyCodeRequest, Verify2FARequest
from app.telegram_client import telegram_manager, TelegramAuthError
from app.database import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["Telegram Connections"])


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


def _mask_phone(phone: str | None) -> str | None:
    """Mask phone number: +358123456789 → +358***6789"""
    if not phone or len(phone) < 8:
        return phone
    return phone[:4] + "***" + phone[-4:]
