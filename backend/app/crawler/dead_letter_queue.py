"""
Dead Letter Queue - Persistent file-based message backup for failed DB writes.

Architecture:
- Date-based file rotation (dlq_YYYYMMDD.jsonl)
- File locking (fcntl) for concurrent write safety
- Auto-replay on crawler startup
- Sentry alerting on accumulation (>100 messages)
- 50MB size limit per file

Usage:
    dlq = DeadLetterQueue()
    await dlq.write_batch([{"data": {...}, "error": "..."}])
    replayed = await dlq.replay(db_manager)
"""
import asyncio
import fcntl
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Dead Letter Queue directory (persistent, not /tmp)
DEAD_LETTER_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "dead_letter"
DEAD_LETTER_DIR.mkdir(parents=True, exist_ok=True)

# File size limit (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Sentry alert threshold (100 messages accumulated)
SENTRY_ALERT_THRESHOLD = 100


class DeadLetterQueue:
    """File-based dead letter queue with auto-replay and file locking."""

    def __init__(self):
        """Initialize dead letter queue with date-based file path."""
        self._file_path = self._get_current_file_path()
        self._count = 0
        self._sentry_alerted = False

    def _get_current_file_path(self) -> Path:
        """Get file path for current date (dlq_YYYYMMDD.jsonl)."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        return DEAD_LETTER_DIR / f"dlq_{date_str}.jsonl"

    async def write_batch(self, batch: list[dict]) -> None:
        """
        Write a batch of failed messages to file with locking.

        Args:
            batch: List of message dicts with 'row' and 'error' keys

        File format (JSONL):
            {"row": {...}, "error": "...", "_dlq_timestamp": "2024-..."}
        """
        if not batch:
            return

        # Ensure file path is current (handle day rollover)
        current_path = self._get_current_file_path()
        if current_path != self._file_path:
            self._file_path = current_path
            self._count = 0
            self._sentry_alerted = False

        # Check file size before writing
        if self._file_path.exists() and self._file_path.stat().st_size > MAX_FILE_SIZE:
            logger.error(
                "[DLQ] File exceeds %d MB — DROPPING %d messages",
                MAX_FILE_SIZE // (1024 * 1024),
                len(batch),
            )
            await self._alert_sentry_file_full()
            return

        # Write with file locking (Unix fcntl)
        try:
            await asyncio.to_thread(self._write_with_lock, batch)
            self._count += len(batch)
            logger.info("[DLQ] Wrote %d messages to %s (total: %d)", len(batch), self._file_path.name, self._count)

            # Alert Sentry if accumulated count exceeds threshold
            if self._count >= SENTRY_ALERT_THRESHOLD and not self._sentry_alerted:
                await self._alert_sentry_accumulation()
                self._sentry_alerted = True

        except Exception as e:
            logger.error("[DLQ] Write failed: %s", e, exc_info=True)

    def _write_with_lock(self, batch: list[dict]) -> None:
        """Synchronous write with fcntl file locking (called via to_thread)."""
        with open(self._file_path, "a") as f:
            # Acquire exclusive lock (blocks until available)
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                for msg in batch:
                    msg["_dlq_timestamp"] = datetime.now(timezone.utc).isoformat()
                    f.write(json.dumps(msg, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            finally:
                # Release lock
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    async def replay(self, flush_callback: Callable[[list[dict]], Any]) -> int:
        """
        Replay all dead letter files in order (auto-recovery on startup).

        Args:
            flush_callback: Async function to persist messages (e.g., db._flush_batch)

        Returns:
            Total number of messages successfully replayed

        Behavior:
            - Processes files in chronological order (dlq_20240101.jsonl, dlq_20240102.jsonl, ...)
            - Batches messages in chunks of 50
            - Deletes file after successful replay
            - Stops on first batch failure (preserves remaining messages)
        """
        replayed = 0
        dlq_files = sorted(DEAD_LETTER_DIR.glob("dlq_*.jsonl"))

        if not dlq_files:
            return 0

        logger.info("[DLQ] Found %d dead letter files to replay", len(dlq_files))

        for dlq_file in dlq_files:
            try:
                batch = []
                with open(dlq_file, "r") as f:
                    for line in f:
                        try:
                            msg = json.loads(line)
                            batch.append(msg)

                            # Flush in batches of 50
                            if len(batch) >= 50:
                                await flush_callback(batch)
                                replayed += len(batch)
                                batch = []
                        except json.JSONDecodeError as e:
                            logger.warning("[DLQ] Skipping malformed line in %s: %s", dlq_file.name, e)
                            continue

                # Flush remaining messages
                if batch:
                    await flush_callback(batch)
                    replayed += len(batch)

                # Delete file after successful replay
                dlq_file.unlink()
                logger.info("[DLQ] Successfully replayed and deleted %s", dlq_file.name)

            except Exception as e:
                logger.error("[DLQ] Replay failed for %s: %s — stopping replay", dlq_file.name, e, exc_info=True)
                return replayed  # Stop on first failure (preserve remaining files)

        logger.info("[DLQ] Replay complete: %d messages restored", replayed)
        return replayed

    def get_size(self) -> int:
        """
        Get total number of messages in all dead letter files.

        Returns line count across all dlq_*.jsonl files.
        """
        total = 0
        for dlq_file in DEAD_LETTER_DIR.glob("dlq_*.jsonl"):
            try:
                with open(dlq_file, "r") as f:
                    total += sum(1 for _ in f)
            except Exception as e:
                logger.warning("[DLQ] Error counting %s: %s", dlq_file.name, e)
        return total

    async def _alert_sentry_accumulation(self) -> None:
        """Alert Sentry when dead letter queue accumulates >100 messages."""
        try:
            import sentry_sdk
            if sentry_sdk.is_initialized():
                sentry_sdk.capture_message(
                    f"Dead letter queue accumulated {self._count} messages in {self._file_path.name}",
                    level="warning",
                )
        except Exception as e:
            logger.warning("[DLQ] Sentry alert failed: %s", e)

    async def _alert_sentry_file_full(self) -> None:
        """Alert Sentry when dead letter file exceeds size limit."""
        try:
            import sentry_sdk
            if sentry_sdk.is_initialized():
                sentry_sdk.capture_message(
                    f"Dead letter file {self._file_path.name} full — messages being DROPPED",
                    level="error",
                )
        except Exception as e:
            logger.warning("[DLQ] Sentry alert failed: %s", e)
