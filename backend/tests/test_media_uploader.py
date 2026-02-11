"""Tests for app.media_uploader — MediaUploader class."""
import asyncio
import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.media_uploader import MediaUploader, MAX_MEDIA_BYTES, MEDIA_DOWNLOAD_TIMEOUT


@pytest.fixture
def uploader():
    return MediaUploader()


@pytest.fixture
def mock_message():
    msg = MagicMock()
    msg.id = 123
    msg.media = MagicMock()
    msg.media.photo = MagicMock()
    msg.media.document = None
    return msg


@pytest.fixture
def mock_client():
    client = AsyncMock()
    # download_media writes to buffer
    async def fake_download(msg_or_media, buffer, **kwargs):
        buffer.write(b'\xff\xd8\xff\xe0' + b'\x00' * 100)  # fake JPEG
    client.download_media = AsyncMock(side_effect=fake_download)
    return client


class TestMediaUploader:
    @pytest.mark.asyncio
    async def test_upload_media_photo_success(self, uploader, mock_message, mock_client):
        """Should download photo and upload to storage."""
        uploader._select_photo_size = MagicMock(return_value=MagicMock())
        mock_storage = MagicMock()
        mock_storage.storage.from_.return_value.upload.return_value = None
        mock_storage.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/photo.jpg"
        uploader._storage_client = mock_storage

        url, err = await uploader.upload_media(mock_message, "12345", "photo", mock_client)
        assert url == "https://cdn.example.com/photo.jpg"
        assert err is None

    @pytest.mark.asyncio
    async def test_upload_media_empty_buffer(self, uploader, mock_message, mock_client):
        """Should return None if download produces empty buffer."""
        uploader._select_photo_size = MagicMock(return_value=MagicMock())
        mock_client.download_media = AsyncMock()  # Doesn't write to buffer
        url, err = await uploader.upload_media(mock_message, "12345", "photo", mock_client)
        assert url is None

    @pytest.mark.asyncio
    async def test_upload_media_too_large(self, uploader, mock_message, mock_client):
        """Should skip media larger than MAX_MEDIA_BYTES."""
        uploader._select_photo_size = MagicMock(return_value=MagicMock())
        async def big_download(msg_or_media, buffer, **kwargs):
            buffer.write(b'\x00' * (MAX_MEDIA_BYTES + 1))
        mock_client.download_media = AsyncMock(side_effect=big_download)
        url, err = await uploader.upload_media(mock_message, "12345", "photo", mock_client)
        assert url is None

    @pytest.mark.asyncio
    async def test_upload_media_timeout(self, uploader, mock_message, mock_client):
        """Should handle download timeout gracefully."""
        uploader._select_photo_size = MagicMock(return_value=MagicMock())
        mock_client.download_media = AsyncMock(side_effect=asyncio.TimeoutError())
        url, err = await uploader.upload_media(mock_message, "12345", "photo", mock_client)
        assert url is None

    @pytest.mark.asyncio
    async def test_upload_media_non_photo_no_thumbs(self, uploader, mock_client):
        """Non-photo without thumbnails should return None."""
        msg = MagicMock()
        msg.id = 456
        msg.media = MagicMock()
        msg.media.document = MagicMock()
        msg.media.document.thumbs = None
        url, err = await uploader.upload_media(msg, "12345", "video", mock_client)
        assert url is None

    @pytest.mark.asyncio
    async def test_download_single_media_updates_db(self, uploader, mock_message, mock_client):
        """download_single_media should update DB on success."""
        uploader._select_photo_size = MagicMock(return_value=MagicMock())
        mock_storage = MagicMock()
        mock_storage.storage.from_.return_value.upload.return_value = None
        mock_storage.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/photo.jpg"
        uploader._storage_client = mock_storage

        with patch("app.media_uploader.db") as mock_db:
            mock_db.execute = AsyncMock()
            result = await uploader.download_single_media(mock_message, "photo", "12345", mock_client)
            assert result is True
            mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_download_media_parallel(self, uploader, mock_client):
        """Should process multiple media items and return count."""
        msg1 = MagicMock(); msg1.id = 1; msg1.media = MagicMock(); msg1.media.photo = MagicMock()
        msg2 = MagicMock(); msg2.id = 2; msg2.media = MagicMock(); msg2.media.photo = MagicMock()

        uploader._select_photo_size = MagicMock(return_value=MagicMock())
        mock_storage = MagicMock()
        mock_storage.storage.from_.return_value.upload.return_value = None
        mock_storage.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/photo.jpg"
        uploader._storage_client = mock_storage

        with patch("app.media_uploader.db") as mock_db:
            mock_db.execute = AsyncMock()
            count = await uploader.download_media_parallel(
                [(msg1, "photo"), (msg2, "photo")], "12345", mock_client
            )
            assert count == 2
