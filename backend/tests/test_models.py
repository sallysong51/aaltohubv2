"""
Unit tests for app.models — Pydantic model validation.
"""
import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from app.models import (
    UserRole,
    GroupType,
    GroupVisibility,
    CrawlerStatus,
    UserCreate,
    UserResponse,
    SendCodeRequest,
    VerifyCodeRequest,
    Verify2FARequest,
    RegisterGroupItem,
    MessageBase,
)


# ------------------------------------------------------------------
# Enum validation
# ------------------------------------------------------------------

class TestEnums:
    def test_user_role_values(self):
        assert UserRole.ADMIN == "admin"
        assert UserRole.USER == "user"

    def test_user_role_rejects_invalid(self):
        with pytest.raises(ValueError):
            UserRole("superuser")

    def test_group_type_values(self):
        assert GroupType.GROUP == "group"
        assert GroupType.SUPERGROUP == "supergroup"
        assert GroupType.CHANNEL == "channel"

    def test_group_type_rejects_invalid(self):
        with pytest.raises(ValueError):
            GroupType("dm")

    def test_group_visibility_values(self):
        assert GroupVisibility.PUBLIC == "public"
        assert GroupVisibility.PRIVATE == "private"

    def test_crawler_status_values(self):
        assert CrawlerStatus.ACTIVE == "active"
        assert CrawlerStatus.INACTIVE == "inactive"
        assert CrawlerStatus.ERROR == "error"
        assert CrawlerStatus.INITIALIZING == "initializing"


# ------------------------------------------------------------------
# User models
# ------------------------------------------------------------------

class TestUserCreate:
    def test_minimal_valid(self):
        user = UserCreate(telegram_id=12345)
        assert user.telegram_id == 12345
        assert user.role == UserRole.USER
        assert user.phone_number is None

    def test_admin_role(self):
        user = UserCreate(telegram_id=1, role=UserRole.ADMIN)
        assert user.role == UserRole.ADMIN

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError):
            UserCreate(telegram_id=1, role="superuser")


class TestUserResponse:
    def test_full_response(self):
        now = datetime.now(timezone.utc).isoformat()
        user = UserResponse(
            id=1,
            telegram_id=99999,
            role="user",
            created_at=now,
            updated_at=now,
        )
        assert user.id == 1
        assert user.role == UserRole.USER

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            # Missing 'role', 'created_at', 'updated_at'
            UserResponse(id=1, telegram_id=99999)


# ------------------------------------------------------------------
# Auth models — max_length constraints
# ------------------------------------------------------------------

class TestSendCodeRequest:
    def test_valid(self):
        req = SendCodeRequest(phone_or_username="+358401234567")
        assert req.phone_or_username == "+358401234567"

    def test_max_length_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            SendCodeRequest(phone_or_username="x" * 65)
        # Pydantic v2 includes max_length in the error
        assert "max_length" in str(exc_info.value).lower() or "string_too_long" in str(exc_info.value).lower()


class TestVerifyCodeRequest:
    def test_code_max_length_rejected(self):
        with pytest.raises(ValidationError):
            VerifyCodeRequest(
                phone_or_username="+358401234567",
                code="1" * 11,  # max_length=10
                phone_code_hash="abc",
            )


class TestVerify2FARequest:
    def test_password_max_length_rejected(self):
        with pytest.raises(ValidationError):
            Verify2FARequest(
                phone_or_username="+358401234567",
                password="p" * 257,  # max_length=256
                phone_code_hash="abc",
            )


# ------------------------------------------------------------------
# Group models
# ------------------------------------------------------------------

class TestRegisterGroupItem:
    def test_valid_minimal(self):
        item = RegisterGroupItem(telegram_id=100, title="Test Group")
        assert item.visibility == GroupVisibility.PUBLIC
        assert item.group_type == GroupType.GROUP

    def test_title_max_length_rejected(self):
        with pytest.raises(ValidationError):
            RegisterGroupItem(telegram_id=100, title="T" * 257)  # max_length=256

    def test_username_max_length_rejected(self):
        with pytest.raises(ValidationError):
            RegisterGroupItem(
                telegram_id=100,
                title="Ok",
                username="u" * 65,  # max_length=64
            )


# ------------------------------------------------------------------
# Message models
# ------------------------------------------------------------------

class TestMessageBase:
    def test_valid_text_message(self):
        msg = MessageBase(
            telegram_message_id=1,
            group_id=42,
            sender_name="Alice",
            content="Hello world",
            sent_at=datetime.now(timezone.utc),
        )
        assert msg.content == "Hello world"
        assert msg.media_type is None

    def test_media_message(self):
        msg = MessageBase(
            telegram_message_id=2,
            group_id=42,
            content=None,
            media_type="photo",
            media_url="https://example.com/photo.jpg",
            sent_at=datetime.now(timezone.utc),
        )
        assert msg.media_type == "photo"
        assert msg.content is None

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            # Missing group_id and sent_at
            MessageBase(telegram_message_id=1)
