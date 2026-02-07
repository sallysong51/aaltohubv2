"""
Unit tests for app.auth — JWT creation, decoding, and user retrieval.
"""
import asyncio
import time
from datetime import timedelta, datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.models import UserRole


# ------------------------------------------------------------------
# JWT creation & decoding
# ------------------------------------------------------------------

class TestCreateAccessToken:
    def test_creates_valid_jwt(self, mock_settings):
        token = create_access_token({"sub": "42"})
        assert isinstance(token, str)
        # Should be decodable with the same secret
        payload = pyjwt.decode(
            token,
            mock_settings.JWT_SECRET,
            algorithms=[mock_settings.JWT_ALGORITHM],
        )
        assert payload["sub"] == "42"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "jti" in payload

    def test_custom_expiry(self, mock_settings):
        token = create_access_token(
            {"sub": "1"},
            expires_delta=timedelta(minutes=5),
        )
        payload = pyjwt.decode(
            token,
            mock_settings.JWT_SECRET,
            algorithms=[mock_settings.JWT_ALGORITHM],
        )
        # The exp should be roughly 5 minutes from now
        exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        diff = exp_dt - datetime.now(timezone.utc)
        assert timedelta(minutes=4) < diff < timedelta(minutes=6)


class TestCreateRefreshToken:
    def test_creates_refresh_type(self, mock_settings):
        token = create_refresh_token({"sub": "7"})
        payload = pyjwt.decode(
            token,
            mock_settings.JWT_SECRET,
            algorithms=[mock_settings.JWT_ALGORITHM],
        )
        assert payload["type"] == "refresh"
        assert payload["sub"] == "7"


class TestDecodeToken:
    def test_decode_valid_token(self, mock_settings):
        token = create_access_token({"sub": "99"})
        payload = decode_token(token)
        assert payload["sub"] == "99"

    def test_expired_token_raises(self, mock_settings):
        """Tokens with an expiry in the past must raise HTTPException (wraps JWTError)."""
        token = create_access_token(
            {"sub": "1"},
            expires_delta=timedelta(seconds=-1),
        )
        with pytest.raises(HTTPException) as exc_info:
            decode_token(token)
        assert exc_info.value.status_code == 401

    def test_tampered_token_raises(self, mock_settings):
        token = create_access_token({"sub": "1"})
        tampered = token[:-4] + "XXXX"
        with pytest.raises(HTTPException) as exc_info:
            decode_token(tampered)
        assert exc_info.value.status_code == 401


# ------------------------------------------------------------------
# get_current_user
# ------------------------------------------------------------------

class TestGetCurrentUser:
    """Test the async get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_rejects_revoked_token(self, mock_settings, mock_db):
        """If the token's jti appears in revoked_tokens, access is denied."""
        token = create_access_token({"sub": "10"})
        payload = pyjwt.decode(
            token,
            mock_settings.JWT_SECRET,
            algorithms=[mock_settings.JWT_ALGORITHM],
        )
        jti = payload["jti"]

        # Make the DB return a revoked-token row
        revoked_result = MagicMock()
        revoked_result.data = [{"id": "abc"}]
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = revoked_result

        credentials = MagicMock()
        credentials.credentials = token

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)
        assert exc_info.value.status_code == 401
        assert "revoked" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_returns_user_on_valid_token(self, mock_settings, mock_db):
        """Happy path: valid token + user exists in DB -> returns UserResponse."""
        token = create_access_token({"sub": "10"})

        # revoked_tokens check returns empty
        revoked_result = MagicMock()
        revoked_result.data = []

        user_result = MagicMock()
        user_result.data = [
            {
                "id": 10,
                "telegram_id": 55555,
                "phone_number": "+358000000",
                "username": "testuser",
                "first_name": "Test",
                "last_name": "User",
                "role": "user",
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            }
        ]

        # The mock_db chain: first call is revoked_tokens, second is users
        call_count = 0

        def table_side_effect(table_name):
            nonlocal call_count
            call_count += 1
            chain = MagicMock()
            if table_name == "revoked_tokens":
                chain.select.return_value.eq.return_value.execute.return_value = revoked_result
            elif table_name == "users":
                chain.select.return_value.eq.return_value.execute.return_value = user_result
            return chain

        mock_db.table.side_effect = table_side_effect

        credentials = MagicMock()
        credentials.credentials = token

        user = await get_current_user(credentials=credentials, db=mock_db)
        assert user.id == 10
        assert user.username == "testuser"
        assert user.role == UserRole.USER

    @pytest.mark.asyncio
    async def test_rejects_refresh_token_type(self, mock_settings, mock_db):
        """get_current_user must reject tokens with type='refresh'."""
        token = create_refresh_token({"sub": "10"})

        credentials = MagicMock()
        credentials.credentials = token

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_rejects_token_without_sub(self, mock_settings, mock_db):
        """Tokens missing the 'sub' claim must be rejected."""
        # Manually craft a token with no sub
        payload = {
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "jti": "abc-123",
        }
        token = pyjwt.encode(
            payload,
            mock_settings.JWT_SECRET,
            algorithm=mock_settings.JWT_ALGORITHM,
        )

        # revoked_tokens returns empty
        revoked_result = MagicMock()
        revoked_result.data = []
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = revoked_result

        credentials = MagicMock()
        credentials.credentials = token

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(credentials=credentials, db=mock_db)
        assert exc_info.value.status_code == 401
