"""
Async HTTP client for the API server to call the crawler process.

All methods return None or a default value on failure, so the API
server degrades gracefully when the crawler is unreachable.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CrawlerHealth:
    """Structured health status for the crawler process."""

    status: Literal["healthy", "degraded", "restarting", "unreachable", "stopped"]
    message: str
    details: Optional[dict] = None
    timestamp: float = field(default_factory=time.time)

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            base_url=settings.CRAWLER_API_URL,
            headers={
                "Authorization": f"Bearer {settings.crawler_api_secret}",
            },
            timeout=10.0,
        )
    return _client


async def get_crawler_status() -> Optional[dict]:
    """Get full crawler status. Returns None if unreachable."""
    try:
        resp = await _get_client().get("/status")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.debug("Crawler status unreachable: %s", e)
        return None


async def get_crawler_health() -> CrawlerHealth:
    """Get crawler health with retry logic and structured status.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) to handle
    transient network issues or brief restarts.

    Returns CrawlerHealth with one of 5 states:
    - healthy: All systems operational
    - degraded: Running but has issues (DB down, circuit breaker open)
    - restarting: Detected recent restart (< 30s uptime)
    - unreachable: Connection failed after retries
    - stopped: Process responded but running=False
    """
    for attempt in range(3):
        try:
            resp = await _get_client().get("/health", timeout=3.0)
            data = resp.json()

            # Check if crawler is stopped
            if data.get("running") is False:
                return CrawlerHealth(
                    status="stopped",
                    message="Crawler process is stopped",
                    details=data,
                )

            # Check for recent restart (< 30s uptime)
            uptime = data.get("uptime_seconds", float("inf"))
            if uptime < 30:
                return CrawlerHealth(
                    status="restarting",
                    message=f"Crawler recently restarted ({int(uptime)}s uptime)",
                    details=data,
                )

            # Check for degraded conditions
            circuit_breaker_state = data.get("circuit_breaker", {}).get("state")
            if circuit_breaker_state == "open":
                return CrawlerHealth(
                    status="degraded",
                    message="Circuit breaker is open (DB write failures)",
                    details=data,
                )

            if data.get("db_connected") is False:
                return CrawlerHealth(
                    status="degraded",
                    message="Database connection lost",
                    details=data,
                )

            # All checks passed - healthy
            return CrawlerHealth(
                status="healthy",
                message="All systems operational",
                details=data,
            )

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            # Retry on connection errors
            if attempt < 2:
                backoff = 2**attempt  # 1s, 2s, 4s
                logger.debug(
                    "Crawler health check failed (attempt %d/3), retrying in %ds: %s",
                    attempt + 1,
                    backoff,
                    type(e).__name__,
                )
                await asyncio.sleep(backoff)
                continue

            # All retries exhausted
            return CrawlerHealth(
                status="unreachable",
                message=f"Connection failed after 3 attempts: {type(e).__name__}",
            )

        except Exception as e:
            logger.error("Unexpected crawler health error: %s", e)
            return CrawlerHealth(
                status="unreachable",
                message=f"Unexpected error: {str(e)}",
            )

    # Should never reach here due to return in loop, but type checker needs it
    return CrawlerHealth(status="unreachable", message="Unknown error after retries")


async def restart_crawler() -> Optional[dict]:
    """Restart the crawler. Returns None if unreachable."""
    try:
        resp = await _get_client().post("/restart")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Crawler restart failed: %s", e)
        return None


async def trigger_historical_crawl(group_id: str) -> Optional[dict]:
    """Trigger historical crawl for a group. Returns None if unreachable."""
    try:
        resp = await _get_client().post(f"/groups/{group_id}/crawl")
        if resp.status_code == 404:
            return {"error": "not_found", "detail": "Group not found in crawler"}
        if resp.status_code == 400:
            return {"error": "not_running", "detail": "Crawler is not running"}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Crawler trigger crawl failed: %s", e)
        return None


async def trigger_batch_historical_crawl(group_ids: list[str]) -> Optional[dict]:
    """Trigger sequential historical crawl for multiple groups.

    Groups are crawled one at a time to avoid Telegram rate limits.
    Returns None if crawler is unreachable.
    """
    try:
        resp = await _get_client().post(
            "/groups/batch-crawl",
            json={"group_ids": group_ids},
            timeout=15.0,
        )
        if resp.status_code == 400:
            return {"error": "not_running", "detail": resp.json().get("detail", "Crawler not running")}
        if resp.status_code == 404:
            return {"error": "not_found", "detail": resp.json().get("detail", "No valid groups")}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Batch crawl trigger failed: %s", e)
        return None


async def close():
    """Close the HTTP client (call at app shutdown)."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
