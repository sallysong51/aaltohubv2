"""
Media download and upload service — extracted from LiveCrawlerService.

Handles downloading media from Telegram and uploading to Supabase Storage.
Supports concurrent downloads with semaphore control and optimized photo sizes.
"""
import asyncio
import io
import logging

from telethon import TelegramClient

from app.database import db, get_storage_client
from app.crawler.utils import select_photo_size

logger = logging.getLogger(__name__)

MAX_MEDIA_BYTES = 10 * 1024 * 1024  # 10 MB
MEDIA_DOWNLOAD_TIMEOUT = 30  # seconds
MEDIA_CONCURRENCY = 5
MEDIA_DOWNLOAD_BATCH = 50


class MediaUploader:
    """Handles media download from Telegram and upload to Supabase Storage."""

    def __init__(self) -> None:
        self._media_semaphore = asyncio.Semaphore(MEDIA_CONCURRENCY)
        self._storage_client = None
        self._select_photo_size = select_photo_size

    async def upload_media(
        self,
        message,
        group_uuid: str,
        media_type: str,
        client: TelegramClient,
    ) -> tuple[str | None, str | None]:
        """Download media from Telegram and upload to Supabase Storage.

        Returns (media_url, None). For photos, downloads an optimized size (800px)
        instead of full resolution. Uses x-upsert for idempotent re-crawl.
        """
        try:
            buffer = io.BytesIO()
            if media_type == "photo":
                thumb = self._select_photo_size(message.media.photo) if hasattr(message.media, 'photo') else None
                if thumb:
                    await asyncio.wait_for(
                        client.download_media(message.media, buffer, thumb=thumb),
                        timeout=MEDIA_DOWNLOAD_TIMEOUT,
                    )
                else:
                    await asyncio.wait_for(
                        client.download_media(message, buffer),
                        timeout=MEDIA_DOWNLOAD_TIMEOUT,
                    )
                content_type = "image/jpeg"
            else:
                if hasattr(message.media, "document") and message.media.document:
                    thumbs = message.media.document.thumbs
                    if thumbs:
                        await asyncio.wait_for(
                            client.download_media(message, buffer, thumb=0),
                            timeout=MEDIA_DOWNLOAD_TIMEOUT,
                        )
                        content_type = "image/jpeg"
                    else:
                        return None, None
                else:
                    return None, None

            buffer.seek(0)
            file_bytes = buffer.read()
            if not file_bytes:
                return None, None

            if len(file_bytes) > MAX_MEDIA_BYTES:
                logger.info("Media for msg %d too large (%d bytes), skipping", message.id, len(file_bytes))
                return None, None

            file_ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "bin"
            file_path = f"{group_uuid}/{message.id}.{file_ext}"

            storage = self._storage_client or get_storage_client()
            await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: storage.storage.from_("message-media").upload(
                        file_path, file_bytes, {"content-type": content_type, "x-upsert": "true"}
                    )
                ),
                timeout=30.0,
            )
            public_url = storage.storage.from_("message-media").get_public_url(file_path)
            return public_url, None
        except asyncio.TimeoutError:
            logger.warning("Media download/upload timeout for msg %d", message.id)
            return None, None
        except Exception as e:
            err_str = str(e).lower()
            if "already exists" in err_str or "duplicate" in err_str:
                try:
                    storage = self._storage_client or get_storage_client()
                    file_path = f"{group_uuid}/{message.id}.jpg"
                    public_url = storage.storage.from_("message-media").get_public_url(file_path)
                    return public_url, None
                except Exception:
                    pass
            if "not found" not in err_str and "bucket" not in err_str:
                logger.warning("Media upload failed for msg %d: %s", message.id, e)
            return None, None

    async def download_single_media(
        self,
        message,
        media_type: str,
        group_uuid: str,
        client: TelegramClient,
    ) -> bool:
        """Download a single media file with semaphore control, then UPDATE DB."""
        async with self._media_semaphore:
            media_url, _ = await self.upload_media(message, group_uuid, media_type, client)
            if media_url:
                try:
                    await db.execute(
                        'UPDATE messages SET media_url = $1 WHERE telegram_message_id = $2 AND group_id = $3',
                        media_url, message.id, int(group_uuid),
                    )
                    return True
                except Exception as e:
                    logger.warning("Failed to update media_url for msg %d: %s", message.id, e)
            return False

    async def download_media_parallel(
        self,
        media_items: list[tuple],
        group_uuid: str,
        client: TelegramClient,
        running_check: callable = None,
    ) -> int:
        """Download and upload media for multiple messages concurrently.

        Processes in chunks of MEDIA_DOWNLOAD_BATCH for progress tracking.
        """
        total = len(media_items)
        downloaded = 0

        for i in range(0, total, MEDIA_DOWNLOAD_BATCH):
            chunk = media_items[i:i + MEDIA_DOWNLOAD_BATCH]
            if running_check and not running_check():
                break

            results = await asyncio.gather(
                *[self.download_single_media(msg, mtype, group_uuid, client) for msg, mtype in chunk],
                return_exceptions=True,
            )
            downloaded += sum(1 for r in results if r is True)

            if i + MEDIA_DOWNLOAD_BATCH < total:
                logger.info("  Media progress: %d/%d downloaded (%d successful)", i + len(chunk), total, downloaded)

        return downloaded
