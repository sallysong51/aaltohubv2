"""
Admin AI Management Routes

API endpoints for AI classification, prompt management, and data operations.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, List, Optional
from datetime import datetime
import logging
import json

from app.database import db
from app.auth import require_admin
from app.models import User

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# AI Classification Metrics
# ============================================================================

@router.get("/ai/metrics")
async def get_ai_metrics(current_user: User = Depends(require_admin)) -> Dict:
    """
    Get AI classification metrics.

    Returns:
        - queue_size: Current classification queue size
        - cache_hit_rate: Cache effectiveness
        - circuit_breaker_status: Open/closed status
        - cost_today: Today's API cost in USD
        - messages_today: Messages classified today
    """
    try:
        async with db.pool.acquire() as conn:
            # Get today's stats
            today_stats = await conn.fetchrow("""
                SELECT
                    messages_processed,
                    total_cost_usd,
                    avg_confidence,
                    category_breakdown
                FROM classification_stats
                WHERE date = CURRENT_DATE
                ORDER BY date DESC
                LIMIT 1
            """)

            # Get queue size
            queue_size = await conn.fetchval("""
                SELECT COUNT(*) FROM classification_queue
                WHERE status = 'pending'
            """)

            # Get cache stats (estimate hit rate)
            cache_hits = await conn.fetchval("""
                SELECT SUM(hit_count - 1) FROM ai_cache
                WHERE created_at > NOW() - INTERVAL '24 hours'
            """) or 0

            total_classified = (today_stats["messages_processed"] if today_stats else 0) + cache_hits

            return {
                "queue_size": queue_size,
                "cache_hit_rate": round(cache_hits / total_classified * 100, 1) if total_classified > 0 else 0,
                "circuit_open": False,  # Would come from live service
                "cost_today": float(today_stats["total_cost_usd"]) if today_stats else 0.0,
                "messages_today": today_stats["messages_processed"] if today_stats else 0,
                "avg_confidence": float(today_stats["avg_confidence"]) if today_stats else 0.0,
                "category_breakdown": today_stats["category_breakdown"] if today_stats else {}
            }

    except Exception as e:
        logger.error(f"Error fetching AI metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch AI metrics")


# ============================================================================
# Prompt Management
# ============================================================================

@router.get("/ai/prompts")
async def list_prompts(
    prompt_type: Optional[str] = None,
    current_user: User = Depends(require_admin)
) -> List[Dict]:
    """List all prompts, optionally filtered by type."""
    try:
        async with db.pool.acquire() as conn:
            if prompt_type:
                rows = await conn.fetch("""
                    SELECT id, name, type, version, is_active, created_at,
                           LENGTH(content) as content_length
                    FROM prompts
                    WHERE type = $1
                    ORDER BY version DESC
                """, prompt_type)
            else:
                rows = await conn.fetch("""
                    SELECT id, name, type, version, is_active, created_at,
                           LENGTH(content) as content_length
                    FROM prompts
                    ORDER BY type, version DESC
                """)

            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error listing prompts: {e}")
        raise HTTPException(status_code=500, detail="Failed to list prompts")


@router.post("/ai/prompts")
async def create_prompt(
    payload: Dict,
    current_user: User = Depends(require_admin)
) -> Dict:
    """
    Create new prompt version.

    Payload:
        - name: Prompt name
        - type: classification|extraction|hidden_cost
        - content: Prompt text
    """
    try:
        name = payload.get("name")
        prompt_type = payload.get("type")
        content = payload.get("content")

        if not all([name, prompt_type, content]):
            raise HTTPException(status_code=400, detail="Missing required fields")

        if prompt_type not in ["classification", "extraction", "hidden_cost"]:
            raise HTTPException(status_code=400, detail="Invalid prompt type")

        async with db.pool.acquire() as conn:
            # Get next version number
            max_version = await conn.fetchval("""
                SELECT COALESCE(MAX(version), 0) FROM prompts
                WHERE name = $1
            """, name)

            new_version = max_version + 1

            # Insert new prompt
            prompt_id = await conn.fetchval("""
                INSERT INTO prompts (name, type, version, content, created_by)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """, name, prompt_type, new_version, content, current_user.id)

            return {
                "id": prompt_id,
                "name": name,
                "type": prompt_type,
                "version": new_version,
                "is_active": False
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating prompt: {e}")
        raise HTTPException(status_code=500, detail="Failed to create prompt")


@router.put("/ai/prompts/{prompt_id}/activate")
async def activate_prompt(
    prompt_id: str,
    current_user: User = Depends(require_admin)
) -> Dict:
    """Activate prompt version (deactivates others of same type)."""
    try:
        async with db.pool.acquire() as conn:
            # Get prompt type
            row = await conn.fetchrow("""
                SELECT type FROM prompts WHERE id = $1
            """, prompt_id)

            if not row:
                raise HTTPException(status_code=404, detail="Prompt not found")

            prompt_type = row["type"]

            # Deactivate all prompts of this type
            await conn.execute("""
                UPDATE prompts
                SET is_active = FALSE
                WHERE type = $1
            """, prompt_type)

            # Activate this prompt
            await conn.execute("""
                UPDATE prompts
                SET is_active = TRUE
                WHERE id = $1
            """, prompt_id)

            return {"success": True, "activated_id": prompt_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating prompt: {e}")
        raise HTTPException(status_code=500, detail="Failed to activate prompt")


@router.post("/ai/test")
async def test_prompt(
    payload: Dict,
    current_user: User = Depends(require_admin)
) -> Dict:
    """
    Test prompt on sample message (mock implementation).

    Payload:
        - prompt_content: Prompt text
        - test_message: Sample message text

    Returns:
        Mock classification result
    """
    # TODO: Implement actual AI API call
    return {
        "category": "event",
        "confidence": 0.92,
        "extracted_data": {
            "event_date": "2026-03-15",
            "event_location": "Helsinki"
        }
    }


@router.get("/ai/stats")
async def get_classification_stats(
    days: int = 30,
    current_user: User = Depends(require_admin)
) -> List[Dict]:
    """Get classification statistics for last N days."""
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT date, messages_processed, total_cost_usd,
                       avg_confidence, category_breakdown
                FROM classification_stats
                WHERE date > CURRENT_DATE - $1
                ORDER BY date DESC
            """, days)

            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error fetching classification stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")


# ============================================================================
# External References Metrics
# ============================================================================

@router.get("/references/metrics")
async def get_references_metrics(current_user: User = Depends(require_admin)) -> Dict:
    """Get external references crawling metrics."""
    try:
        async with db.pool.acquire() as conn:
            # Scraping queue stats
            scraping_pending = await conn.fetchval("""
                SELECT COUNT(*) FROM scraping_queue WHERE status = 'pending'
            """)
            scraping_processing = await conn.fetchval("""
                SELECT COUNT(*) FROM scraping_queue WHERE status = 'processing'
            """)
            scraping_failed = await conn.fetchval("""
                SELECT COUNT(*) FROM scraping_queue WHERE status = 'failed'
            """)

            # Join queue stats
            join_pending = await conn.fetchval("""
                SELECT COUNT(*) FROM telegram_join_queue WHERE status = 'pending'
            """)
            join_processing = await conn.fetchval("""
                SELECT COUNT(*) FROM telegram_join_queue WHERE status = 'processing'
            """)
            join_failed = await conn.fetchval("""
                SELECT COUNT(*) FROM telegram_join_queue WHERE status = 'failed'
            """)

            return {
                "scraping_queue": scraping_pending,
                "scraping_processing": scraping_processing,
                "scraping_failed": scraping_failed,
                "join_queue": join_pending,
                "join_processing": join_processing,
                "join_failed": join_failed
            }

    except Exception as e:
        logger.error(f"Error fetching references metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")


# ============================================================================
# Blacklist Management
# ============================================================================

@router.get("/blacklist")
async def list_blacklist(current_user: User = Depends(require_admin)) -> List[Dict]:
    """List all blacklist entries."""
    try:
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, pattern, reason, added_at
                FROM crawl_blacklist
                ORDER BY added_at DESC
            """)

            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error listing blacklist: {e}")
        raise HTTPException(status_code=500, detail="Failed to list blacklist")


@router.post("/blacklist")
async def add_blacklist(
    payload: Dict,
    current_user: User = Depends(require_admin)
) -> Dict:
    """Add URL pattern to blacklist."""
    try:
        pattern = payload.get("pattern")
        reason = payload.get("reason", "Admin blacklisted")

        if not pattern:
            raise HTTPException(status_code=400, detail="Pattern required")

        async with db.pool.acquire() as conn:
            blacklist_id = await conn.fetchval("""
                INSERT INTO crawl_blacklist (pattern, reason, added_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (pattern) DO NOTHING
                RETURNING id
            """, pattern, reason, current_user.id)

            if not blacklist_id:
                raise HTTPException(status_code=409, detail="Pattern already exists")

            return {"id": blacklist_id, "pattern": pattern}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding blacklist: {e}")
        raise HTTPException(status_code=500, detail="Failed to add blacklist")


@router.delete("/blacklist/{blacklist_id}")
async def remove_blacklist(
    blacklist_id: str,
    current_user: User = Depends(require_admin)
) -> Dict:
    """Remove entry from blacklist."""
    try:
        async with db.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM crawl_blacklist
                WHERE id = $1
            """, blacklist_id)

            if result == "DELETE 0":
                raise HTTPException(status_code=404, detail="Blacklist entry not found")

            return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing blacklist: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove blacklist")


# ============================================================================
# Bulk Operations
# ============================================================================

@router.post("/bulk-retry")
async def bulk_retry_classification(
    payload: Dict,
    current_user: User = Depends(require_admin)
) -> Dict:
    """
    Bulk retry classification for low-confidence messages.

    Payload:
        - confidence_threshold: Retry messages below this confidence (default 0.7)
    """
    try:
        threshold = payload.get("confidence_threshold", 0.7)

        async with db.pool.acquire() as conn:
            # Find low-confidence messages
            rows = await conn.fetch("""
                SELECT id FROM messages
                WHERE ai_confidence < $1
                  AND ai_classified_at > NOW() - INTERVAL '7 days'
            """, threshold)

            # Enqueue for re-classification
            for row in rows:
                await conn.execute("""
                    INSERT INTO classification_queue (message_id, status)
                    VALUES ($1, 'pending')
                    ON CONFLICT (message_id) DO NOTHING
                """, row["id"])

            return {"requeued_count": len(rows)}

    except Exception as e:
        logger.error(f"Error bulk retrying classification: {e}")
        raise HTTPException(status_code=500, detail="Failed to retry classification")


@router.post("/export")
async def export_data(
    payload: Dict,
    current_user: User = Depends(require_admin)
) -> Dict:
    """
    Export data (mock implementation).

    Payload:
        - format: csv|json
    """
    # TODO: Implement actual export logic
    return {"message": "Export feature not yet implemented"}


@router.post("/cleanup")
async def cleanup_data(
    payload: Dict,
    current_user: User = Depends(require_admin)
) -> Dict:
    """
    Database cleanup operations.

    Payload:
        - action: delete_old_messages|clear_failed_queues|vacuum
    """
    try:
        action = payload.get("action")

        async with db.pool.acquire() as conn:
            if action == "delete_old_messages":
                result = await conn.execute("""
                    DELETE FROM messages
                    WHERE created_at < NOW() - INTERVAL '90 days'
                """)
                return {"action": action, "deleted": result.split()[-1]}

            elif action == "clear_failed_queues":
                deleted_scraping = await conn.execute("""
                    DELETE FROM scraping_queue
                    WHERE status = 'failed' AND created_at < NOW() - INTERVAL '30 days'
                """)
                deleted_join = await conn.execute("""
                    DELETE FROM telegram_join_queue
                    WHERE status = 'failed' AND created_at < NOW() - INTERVAL '30 days'
                """)
                return {
                    "action": action,
                    "deleted_scraping": deleted_scraping.split()[-1],
                    "deleted_join": deleted_join.split()[-1]
                }

            elif action == "vacuum":
                # Note: VACUUM cannot run inside transaction
                return {"action": action, "message": "Use psql for VACUUM"}

            else:
                raise HTTPException(status_code=400, detail="Invalid action")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cleaning up data: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup data")
