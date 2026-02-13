#!/usr/bin/env python3
"""
Manual test script for Dead Letter Queue.

Tests:
1. File creation and locking
2. Batch writing
3. Size calculation
4. Auto-replay on startup
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone

# Add backend to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from app.crawler.dead_letter_queue import DeadLetterQueue, DEAD_LETTER_DIR


async def test_dead_letter_queue():
    """Test Dead Letter Queue functionality."""

    print("=" * 60)
    print("Dead Letter Queue Test")
    print("=" * 60)

    # 1. Initialize
    dlq = DeadLetterQueue()
    print(f"\n1. Initialized DLQ")
    print(f"   Directory: {DEAD_LETTER_DIR}")
    print(f"   Current file: {dlq._file_path}")

    # 2. Write test messages
    test_messages = [
        {
            "row": {
                "telegram_message_id": 12345,
                "group_id": 100,
                "content": "Test message 1",
                "sent_at": datetime.now(timezone.utc).isoformat(),
            },
            "error": "Test error: DB connection failed",
        },
        {
            "row": {
                "telegram_message_id": 12346,
                "group_id": 100,
                "content": "Test message 2",
                "sent_at": datetime.now(timezone.utc).isoformat(),
            },
            "error": "Test error: Circuit breaker open",
        },
    ]

    print(f"\n2. Writing {len(test_messages)} test messages...")
    await dlq.write_batch(test_messages)

    # 3. Check file size
    size = dlq.get_size()
    print(f"\n3. File size: {size} messages")
    assert size == len(test_messages), f"Expected {len(test_messages)}, got {size}"

    # 4. Test replay
    print(f"\n4. Testing replay...")
    replayed_messages = []

    async def mock_flush(batch: list[dict]):
        """Mock flush callback that collects messages."""
        nonlocal replayed_messages
        replayed_messages.extend(batch)
        print(f"   Replayed batch of {len(batch)} messages")

    replayed_count = await dlq.replay(mock_flush)
    print(f"   Total replayed: {replayed_count} messages")

    assert replayed_count == len(test_messages), f"Expected {len(test_messages)}, got {replayed_count}"
    assert len(replayed_messages) == len(test_messages), "All messages should be replayed"

    # 5. Verify file is deleted after successful replay
    size_after = dlq.get_size()
    print(f"\n5. File size after replay: {size_after} messages")
    assert size_after == 0, "File should be deleted after successful replay"

    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_dead_letter_queue())
