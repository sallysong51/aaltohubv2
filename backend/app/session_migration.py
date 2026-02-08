"""
Background task to migrate Telegram sessions from telethon_sessions to telegram_connections.

This task runs on application startup and migrates sessions for users who have
already linked their email (auth_user_id IS NOT NULL) but don't have a
telegram_connections entry yet.
"""
import asyncio
import logging
from typing import List, Dict
from app.database import db

logger = logging.getLogger(__name__)


async def migrate_linked_user_sessions() -> Dict[str, int]:
    """
    Migrate sessions for users who have linked email (auth_user_id IS NOT NULL).

    This is a one-time background task that runs on startup to move sessions from
    the legacy telethon_sessions table to the new telegram_connections table.

    Returns:
        Dict with migration statistics:
            - total: total users needing migration
            - migrated: successfully migrated
            - errors: failed migrations
            - skipped: already migrated
    """
    logger.info("[SESSION MIGRATION] Starting session migration task...")

    stats = {
        "total": 0,
        "migrated": 0,
        "errors": 0,
        "skipped": 0,
    }

    try:
        # Find users with auth_user_id but no telegram_connections entry
        rows = await db.fetch(
            """SELECT
                   u.id,
                   u.auth_user_id,
                   u.telegram_id,
                   u.phone_number,
                   u.username,
                   u.first_name,
                   u.last_name,
                   ts.session_data,
                   ts.key_hash
               FROM users u
               INNER JOIN telethon_sessions ts ON u.id = ts.user_id
               WHERE u.auth_user_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM telegram_connections tc
                   WHERE tc.auth_user_id = u.auth_user_id
               )"""
        )

        stats["total"] = len(rows)

        if stats["total"] == 0:
            logger.info("[SESSION MIGRATION] No sessions need migration")
            return stats

        logger.info("[SESSION MIGRATION] Found %d sessions to migrate", stats["total"])

        for row in rows:
            try:
                # Mask phone number (last 4 digits only)
                phone_masked = None
                if row["phone_number"]:
                    phone_number = row["phone_number"]
                    if len(phone_number) >= 4:
                        # Format: +358****1234
                        phone_masked = f"+{phone_number[:3]}****{phone_number[-4:]}"
                    else:
                        phone_masked = f"+***{phone_number}"

                # Insert into telegram_connections (session already encrypted)
                await db.execute(
                    """INSERT INTO telegram_connections
                       (user_id, auth_user_id, telegram_user_id, session_encrypted, key_hash,
                        phone_masked, username, first_name, last_name)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                       ON CONFLICT (telegram_user_id) DO NOTHING""",
                    row["id"],
                    row["auth_user_id"],
                    row["telegram_id"],
                    row["session_data"],
                    row["key_hash"],
                    phone_masked,
                    row["username"],
                    row["first_name"],
                    row["last_name"]
                )

                stats["migrated"] += 1

                if stats["migrated"] % 10 == 0:
                    logger.info(
                        "[SESSION MIGRATION] Progress: %d/%d migrated",
                        stats["migrated"], stats["total"]
                    )

            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "[SESSION MIGRATION] Failed to migrate session for user %s: %s",
                    row["id"], e
                )

        logger.info(
            "[SESSION MIGRATION] Complete: %d migrated, %d errors out of %d total",
            stats["migrated"], stats["errors"], stats["total"]
        )

        return stats

    except Exception as e:
        logger.error("[SESSION MIGRATION] Fatal error: %s", e)
        return stats


async def cleanup_orphaned_sessions() -> int:
    """
    Clean up telethon_sessions entries that have been migrated to telegram_connections.

    IMPORTANT: This should only be called manually after confirming all sessions
    are working correctly. This is NOT called automatically during migration.

    Returns:
        Number of orphaned sessions deleted
    """
    logger.info("[SESSION CLEANUP] Starting cleanup of orphaned sessions...")

    try:
        # Find telethon_sessions that exist in telegram_connections
        result = await db.execute(
            """DELETE FROM telethon_sessions ts
               WHERE EXISTS (
                   SELECT 1 FROM telegram_connections tc
                   WHERE tc.user_id = ts.user_id
               )"""
        )

        # Parse result (format: "DELETE N")
        count = int(result.split()[-1]) if result and result.split() else 0

        logger.info("[SESSION CLEANUP] Deleted %d orphaned sessions", count)
        return count

    except Exception as e:
        logger.error("[SESSION CLEANUP] Failed: %s", e)
        return 0


async def verify_migration_integrity() -> Dict[str, any]:
    """
    Verify that all users with auth_user_id have their sessions migrated.

    Returns:
        Dict with verification results:
            - total_linked_users: users with auth_user_id
            - users_with_tc: users with telegram_connections
            - missing_tc: users missing telegram_connections (should be 0)
            - orphaned_sessions: telethon_sessions that can be cleaned up
    """
    logger.info("[MIGRATION VERIFY] Checking migration integrity...")

    try:
        # Count users with auth_user_id
        total_linked = await db.fetchval(
            "SELECT COUNT(*) FROM users WHERE auth_user_id IS NOT NULL"
        )

        # Count users with telegram_connections
        users_with_tc = await db.fetchval(
            "SELECT COUNT(DISTINCT auth_user_id) FROM telegram_connections"
        )

        # Find users with auth_user_id but no telegram_connections
        missing_tc = await db.fetch(
            """SELECT u.id, u.telegram_id, u.username, u.phone_number
               FROM users u
               WHERE u.auth_user_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM telegram_connections tc
                   WHERE tc.auth_user_id = u.auth_user_id
               )"""
        )

        # Count orphaned sessions (can be cleaned up)
        orphaned = await db.fetchval(
            """SELECT COUNT(*) FROM telethon_sessions ts
               WHERE EXISTS (
                   SELECT 1 FROM telegram_connections tc
                   WHERE tc.user_id = ts.user_id
               )"""
        )

        results = {
            "total_linked_users": total_linked or 0,
            "users_with_tc": users_with_tc or 0,
            "missing_tc": len(missing_tc),
            "missing_tc_details": [dict(row) for row in missing_tc] if missing_tc else [],
            "orphaned_sessions": orphaned or 0,
        }

        logger.info(
            "[MIGRATION VERIFY] Results: %d linked users, %d with TC, %d missing, %d orphaned",
            results["total_linked_users"],
            results["users_with_tc"],
            results["missing_tc"],
            results["orphaned_sessions"]
        )

        if results["missing_tc"] > 0:
            logger.warning(
                "[MIGRATION VERIFY] ⚠️  %d users are missing telegram_connections!",
                results["missing_tc"]
            )
        else:
            logger.info("[MIGRATION VERIFY] ✓ All users have telegram_connections")

        return results

    except Exception as e:
        logger.error("[MIGRATION VERIFY] Failed: %s", e)
        return {
            "total_linked_users": 0,
            "users_with_tc": 0,
            "missing_tc": -1,
            "missing_tc_details": [],
            "orphaned_sessions": 0,
            "error": str(e),
        }
