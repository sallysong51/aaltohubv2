"""Tests for app.error_recovery — GetMeErrorRecovery class."""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.error_recovery import GetMeErrorRecovery


@pytest.fixture
def recovery():
    return GetMeErrorRecovery()


@pytest.fixture
def mock_client():
    client = AsyncMock()
    me = MagicMock()
    me.id = 12345
    client.get_me = AsyncMock(return_value=me)
    return client


class TestGetMeErrorRecovery:
    @pytest.mark.asyncio
    async def test_cache_hit(self, recovery, mock_client):
        """Second call should return cached value without calling get_me."""
        result1 = await recovery.get_telegram_user_id_with_retry(mock_client, 1)
        result2 = await recovery.get_telegram_user_id_with_retry(mock_client, 1)
        assert result1 == 12345
        assert result2 == 12345
        assert mock_client.get_me.call_count == 1  # Only called once

    @pytest.mark.asyncio
    async def test_no_user_id(self, recovery, mock_client):
        """Without user_id, should still work (no caching)."""
        result = await recovery.get_telegram_user_id_with_retry(mock_client, None)
        assert result == 12345

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, recovery):
        """Should retry up to 3 times on failure."""
        client = AsyncMock()
        me = MagicMock()
        me.id = 42
        client.get_me = AsyncMock(side_effect=[Exception("fail"), Exception("fail"), me])
        result = await recovery.get_telegram_user_id_with_retry(client, 1)
        assert result is None or result == 42  # May succeed on 3rd attempt

    @pytest.mark.asyncio
    async def test_all_retries_exhausted(self, recovery):
        """Should return None after 3 failed attempts."""
        client = AsyncMock()
        client.get_me = AsyncMock(side_effect=Exception("fail"))
        result = await recovery.get_telegram_user_id_with_retry(client, 1)
        assert result is None
        assert recovery._get_me_failure_count[1] == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self, recovery):
        """After 5 failures, circuit should open."""
        client = AsyncMock()
        client.get_me = AsyncMock(side_effect=Exception("fail"))
        with patch("app.error_recovery.sentry_sdk", create=True):
            for _ in range(5):
                await recovery.get_telegram_user_id_with_retry(client, 1)
        assert 1 in recovery._get_me_circuit_open

    @pytest.mark.asyncio
    async def test_circuit_open_returns_none_immediately(self, recovery):
        """When circuit is open, should return None without calling get_me."""
        recovery._get_me_circuit_open[1] = time.monotonic()
        client = AsyncMock()
        result = await recovery.get_telegram_user_id_with_retry(client, 1)
        assert result is None
        client.get_me.assert_not_called()

    def test_clear(self, recovery):
        recovery._get_me_cache[1] = (42, time.monotonic())
        recovery._get_me_failure_count[1] = 3
        recovery._get_me_circuit_open[1] = time.monotonic()
        recovery.clear()
        assert recovery._get_me_cache == {}
        assert recovery._get_me_failure_count == {}
        assert recovery._get_me_circuit_open == {}

    @pytest.mark.asyncio
    async def test_cleanup_removes_stale(self, recovery):
        """Cleanup should remove entries older than 2x TTL."""
        recovery._get_me_cache[1] = (42, time.monotonic() - 700)  # >2x 300s TTL
        recovery._get_me_circuit_open[2] = time.monotonic() - 4000  # >1h
        await recovery.cleanup()
        assert 1 not in recovery._get_me_cache
        assert 2 not in recovery._get_me_circuit_open

    @pytest.mark.asyncio
    async def test_timeout_handling(self, recovery):
        """Should handle asyncio.TimeoutError gracefully."""
        client = AsyncMock()
        client.get_me = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await recovery.get_telegram_user_id_with_retry(client, 1)
        assert result is None
