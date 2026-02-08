"""Static utility functions extracted from LiveCrawlerService."""
import logging

logger = logging.getLogger(__name__)


def normalize_chat_id(chat_id: int) -> int:
    """Convert Telethon's negative chat_id to the bare positive ID stored in our DB."""
    if chat_id is None:
        return 0
    if chat_id < 0:
        s = str(chat_id)
        if s.startswith("-100"):
            return int(s[4:])
        return -chat_id
    return chat_id


def detect_media_type(message) -> str | None:
    """Detect media type from a Telethon message object.

    Returns: 'photo', 'video', 'audio', 'sticker', 'voice', 'document', or None.
    """
    from telethon.tl.types import (
        MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage,
    )

    if not message or not message.media:
        return None

    media = message.media

    if isinstance(media, MessageMediaPhoto):
        return "photo"

    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if not doc:
            return None

        for attr in (doc.attributes or []):
            attr_cls = type(attr).__name__
            if attr_cls == "DocumentAttributeSticker":
                return "sticker"
            if attr_cls == "DocumentAttributeVideo":
                return "video"
            if attr_cls == "DocumentAttributeAudio":
                if getattr(attr, "voice", False):
                    return "voice"
                return "audio"

        mime = getattr(doc, "mime_type", "") or ""
        if mime.startswith("image/"):
            return "photo"
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("audio/"):
            return "audio"

        return "document"

    if isinstance(media, MessageMediaWebPage):
        return None

    return None


def select_photo_size(photo):
    """Select optimal photo size (~800px) for bandwidth efficiency.

    Preference order: 'x' (800px) > 'y' (1280px) > 'm' (320px).
    Returns PhotoSize object or None.
    """
    if not photo or not hasattr(photo, "sizes") or not photo.sizes:
        return None

    sizes = photo.sizes
    # Filter to actual photo sizes (not stripped thumbnails)
    real_sizes = [s for s in sizes if hasattr(s, "type") and hasattr(s, "size")]
    if not real_sizes:
        return sizes[-1] if sizes else None

    # Prefer ~800px size ('x')
    preferred = ["x", "y", "m"]
    for p in preferred:
        for s in real_sizes:
            if s.type == p:
                return s

    # Fallback to largest available
    return max(real_sizes, key=lambda s: getattr(s, "size", 0))
