"""
Async HTTP client for the API server to call the crawler process.

All methods return None or a default value on failure, so the API
server degrades gracefully when the crawler is unreachable.
"""
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

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


async def get_crawler_health() -> Optional[dict]:
    """Get crawler health. Returns None if unreachable."""
    try:
        resp = await _get_client().get("/health")
        return resp.json()
    except Exception as e:
        logger.debug("Crawler health unreachable: %s", e)
        return None


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


async def close():
    """Close the HTTP client (call at app shutdown)."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None
