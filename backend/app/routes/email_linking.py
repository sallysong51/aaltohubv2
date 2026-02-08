"""
Email linking routes for forced migration.

These endpoints handle the migration of existing Telegram-only users to
Supabase Auth by requiring them to link an email address on next login.
"""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from app.models import (
    EmailLinkingRequest,
    EmailLinkingStatusResponse,
    EmailLinkingResponse,
    UserResponse
)
from app.auth import get_current_user
from app.database import db
from app.supabase_auth import supabase_auth_manager
from app.encryption import session_encryption, ENCRYPTION_VERSION

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Email Linking"])


@router.get("/email-linking-status", response_model=EmailLinkingStatusResponse)
async def get_email_linking_status(
    current_user: UserResponse = Depends(get_current_user)
):
    """Check if current user needs to link email.

    Returns:
        EmailLinkingStatusResponse with:
            - email_link_required: bool
            - email: str | None (if already linked)
            - linked_at: datetime | None (if already linked)
    """
    user_row = await db.fetchrow(
        "SELECT * FROM users WHERE id = $1",
        current_user.id
    )

    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if auth.users entry exists
    auth_user_id = user_row.get("auth_user_id")
    email = None
    linked_at = user_row.get("email_linked_at")

    if auth_user_id:
        try:
            # Get email from Supabase Auth
            # Convert UUID object to string (asyncpg returns UUID objects, Supabase expects strings)
            auth_user = await supabase_auth_manager.client.auth.admin.get_user_by_id(str(auth_user_id))
            if auth_user and auth_user.user:
                email = auth_user.user.email
        except Exception as e:
            logger.warning(
                "Failed to get auth user %s: %s",
                str(auth_user_id), e
            )

    return EmailLinkingStatusResponse(
        email_link_required=user_row.get("email_link_required", False),
        email=email,
        linked_at=linked_at
    )


@router.post("/link-email", response_model=EmailLinkingResponse)
async def link_email(
    request: EmailLinkingRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """Link email to existing Telegram-only account (forced migration).

    This endpoint:
    1. Rate limits attempts (5 per 15 minutes per user)
    2. Creates a Supabase Auth user (email + password)
    3. Links the auth_user_id to the public users table
    4. Moves the Telegram session to telegram_connections table
    5. Marks email_link_required = FALSE

    Args:
        request: EmailLinkingRequest with email and password

    Returns:
        EmailLinkingResponse with success status and message

    Raises:
        HTTPException 400: Email already linked or already in use
        HTTPException 429: Too many attempts
        HTTPException 500: Supabase Auth error or database error
    """
    # Check if user already has auth_user_id
    user_row = await db.fetchrow(
        "SELECT * FROM users WHERE id = $1",
        current_user.id
    )

    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    if user_row.get("auth_user_id"):
        raise HTTPException(
            status_code=400,
            detail="이메일이 이미 등록되어 있습니다"
        )

    # Rate limiting: 5 attempts per user per 15 minutes
    recent_attempts = await db.fetchval(
        """SELECT COUNT(*) FROM email_linking_attempts
           WHERE user_id = $1 AND created_at > NOW() - INTERVAL '15 minutes'""",
        current_user.id
    )

    if recent_attempts and recent_attempts >= 5:
        raise HTTPException(
            status_code=429,
            detail="너무 많은 시도가 있었습니다. 15분 후 다시 시도해주세요"
        )

    # Check if email already exists in auth.users
    existing_auth_user = await supabase_auth_manager.get_user_by_email(request.email)
    if existing_auth_user:
        # Log attempt
        await db.execute(
            """INSERT INTO email_linking_attempts (user_id, email, attempt_count)
               VALUES ($1, $2, 1)
               ON CONFLICT (user_id) DO UPDATE
               SET attempt_count = email_linking_attempts.attempt_count + 1,
                   updated_at = NOW()""",
            current_user.id, request.email
        )
        raise HTTPException(
            status_code=400,
            detail="이메일이 이미 사용 중입니다. 다른 이메일을 선택해주세요"
        )

    # Create Supabase Auth user
    result = await supabase_auth_manager.create_user(
        email=request.email,
        password=request.password,
        metadata={
            "telegram_id": current_user.telegram_id,
            "migrated_from_telegram": True,
            "migration_date": datetime.now(timezone.utc).isoformat()
        }
    )

    if not result["success"]:
        # Log failed attempt
        await db.execute(
            """INSERT INTO email_linking_attempts (user_id, email, attempt_count)
               VALUES ($1, $2, 1)
               ON CONFLICT (user_id) DO UPDATE
               SET attempt_count = email_linking_attempts.attempt_count + 1,
                   updated_at = NOW()""",
            current_user.id, request.email
        )
        error_msg = result.get("error", "Unknown error")
        logger.error(
            "Supabase Auth user creation failed for user %s: %s",
            current_user.id, error_msg
        )
        raise HTTPException(
            status_code=400,
            detail=f"이메일 등록에 실패했습니다: {error_msg}"
        )

    auth_user_id = result["auth_user_id"]

    try:
        # Link auth_user_id to public users table
        await db.execute(
            """UPDATE users
               SET auth_user_id = $1,
                   email_link_required = FALSE,
                   email_linked_at = NOW()
               WHERE id = $2""",
            auth_user_id, current_user.id
        )

        # Move Telegram session to telegram_connections
        session_row = await db.fetchrow(
            "SELECT * FROM telethon_sessions WHERE user_id = $1",
            current_user.id
        )

        if session_row:
            # Mask phone number (last 4 digits only)
            phone_masked = None
            if current_user.phone_number:
                phone_masked = f"+{current_user.phone_number[:3]}****{current_user.phone_number[-4:]}"

            # Link session (already encrypted, just move it)
            # Convert auth_user_id to string for consistency
            linked = await supabase_auth_manager.link_telegram_to_auth_user(
                auth_user_id=str(auth_user_id),
                telegram_user_id=current_user.telegram_id,
                public_user_id=current_user.id,
                session_encrypted=session_row["session_data"],
                key_hash=session_row.get("key_hash", ENCRYPTION_VERSION),
                phone_masked=phone_masked,
                username=current_user.username,
                first_name=current_user.first_name,
                last_name=current_user.last_name
            )

            if not linked:
                logger.error(
                    "Failed to link Telegram session for user %s (telegram_id=%s, auth_user_id=%s)",
                    current_user.id, current_user.telegram_id, str(auth_user_id)
                )
                raise HTTPException(
                    status_code=500,
                    detail="이메일 등록 중 텔레그램 세션 연결에 실패했습니다. 다시 시도해주세요"
                )

            logger.info(
                "Successfully linked Telegram session: user_id=%s, telegram_id=%s, auth_user_id=%s",
                current_user.id, current_user.telegram_id, str(auth_user_id)
            )
        else:
            logger.warning(
                "No Telegram session found for user %s during email linking",
                current_user.id
            )

        logger.info(
            "User %s successfully linked email %s (auth_user_id=%s)",
            current_user.id, request.email, auth_user_id
        )

        return EmailLinkingResponse(
            success=True,
            message="이메일이 성공적으로 등록되었습니다. 다음 로그인부터는 이메일로 로그인할 수 있습니다",
            email=request.email
        )

    except Exception as e:
        logger.error(
            "Failed to link email for user %s: %s",
            current_user.id, e
        )
        raise HTTPException(
            status_code=500,
            detail="이메일 등록 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요"
        )
