"""
Message entity parsing for links, mentions, and media metadata.

Extracts structured metadata from Telethon message entities:
- Links: URLs and text URLs (hyperlinks)
- Mentions: User mentions (@username) and channel mentions
- Media: Photo albums (grouped media detection)

Phase 34: Message Metadata Enhancement
Following Phase 32D modular design pattern.
"""

from typing import Optional, List, Dict, Any
from telethon.tl.types import (
    Message,
    MessageEntityUrl,
    MessageEntityTextUrl,
    MessageEntityMentionName,
    MessageEntityMention,
)
from telethon.helpers import add_surrogate


class MessageEntityParser:
    """Parse Telethon message entities into structured metadata."""

    @staticmethod
    def extract_links(message: Message) -> Optional[List[Dict[str, str]]]:
        """
        Extract URLs from message.entities.

        Parses both plain URLs and hyperlinks with display text.
        Uses Telethon's add_surrogate helper for correct text indexing
        (Telegram uses UTF-16 for entity offsets).

        Args:
            message: Telethon Message object with entities

        Returns:
            List of link objects: [{"url": "https://...", "text": "optional"}]
            or None if no links found

        Example:
            >>> links = MessageEntityParser.extract_links(message)
            >>> # [{"url": "https://example.com"}, {"url": "https://...", "text": "Click here"}]
        """
        if not message.entities:
            return None

        links = []
        text = add_surrogate(message.message or "")

        for entity in message.entities:
            if isinstance(entity, MessageEntityUrl):
                # Plain URL entity (e.g., https://example.com)
                url = text[entity.offset : entity.offset + entity.length]
                links.append({"url": url})

            elif isinstance(entity, MessageEntityTextUrl):
                # Hyperlink with display text (e.g., [Click here](https://...))
                display_text = text[entity.offset : entity.offset + entity.length]
                links.append({"url": entity.url, "text": display_text})

        return links if links else None

    @staticmethod
    def extract_mentions(message: Message) -> Optional[List[Dict[str, Any]]]:
        """
        Extract user/channel mentions from message.entities.

        Parses both user mentions (clickable) and channel/group mentions (@channel).

        Args:
            message: Telethon Message object with entities

        Returns:
            List of mention objects: [{"username": "@channel", "id": 123}]
            or None if no mentions found

        Example:
            >>> mentions = MessageEntityParser.extract_mentions(message)
            >>> # [{"username": "@user", "id": 123}, {"username": "@channel"}]
        """
        if not message.entities:
            return None

        mentions = []
        text = add_surrogate(message.message or "")

        for entity in message.entities:
            if isinstance(entity, MessageEntityMentionName):
                # User mention (clickable) - has user_id
                username = text[entity.offset : entity.offset + entity.length]
                mentions.append({"username": username, "id": entity.user_id})

            elif isinstance(entity, MessageEntityMention):
                # @channel or @username text (not clickable, may not resolve to user)
                username = text[entity.offset : entity.offset + entity.length]
                # Only include if it starts with @ (Telegram channel/group pattern)
                if username.startswith("@"):
                    mentions.append({"username": username})

        return mentions if mentions else None

    @staticmethod
    def get_photo_count(message: Message) -> Optional[int]:
        """
        Detect photo albums via grouped_id.

        Telegram groups related media (photo albums) using grouped_id.
        When multiple photos are sent together, they share the same grouped_id.

        Current implementation: Returns 2 as indicator of "multiple photos".
        Full implementation would require tracking all messages with same grouped_id
        to count exact number of photos in album.

        Args:
            message: Telethon Message object

        Returns:
            2+ if message is part of photo album (simplified indicator),
            None if single photo or no grouped media

        Example:
            >>> count = MessageEntityParser.get_photo_count(message)
            >>> if count and count > 1:
            ...     print(f"Part of photo album (2+ photos)")
        """
        # Check if message is part of grouped media (album)
        if hasattr(message, "grouped_id") and message.grouped_id:
            # Simplified: return 2 as indicator of "multiple photos"
            # Better implementation would maintain grouped_id → count mapping
            # and update all messages in group with exact count
            return 2

        return None
