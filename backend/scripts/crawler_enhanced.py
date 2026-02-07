"""
Telegram message crawler daemon - Enhanced Version
Runs 24/7 on AWS EC2 to collect messages from registered groups
Features:
- Initial 14-day message load with progress tracking
- Real-time message collection (NewMessage, MessageEdited, MessageDeleted)
- Periodic new group detection (every 5 minutes)
- Automatic 14-day message retention cleanup (every 1 hour)
- Topic/Forum support
- Rate limit handling (FloodWaitError)
- Crawler status tracking
- Error logging
"""
import asyncio
import io
import sys
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import traceback

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, ChannelPrivateError, ChatAdminRequiredError
from telethon.tl.types import Channel, MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from supabase import create_client
from app.config import settings
from app.encryption import session_encryption
from app.models import UserRole


class EnhancedMessageCrawler:
    """Enhanced Telegram message crawler with full features"""
    
    def __init__(self):
        self.client = None
        self.supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        self.group_id_map = {}  # telegram_id -> uuid mapping
        self.group_info_map = {}  # telegram_id -> group info
        self.running = False
        self.crawler_status_map = {}  # group_id -> crawler_status_id
    
    async def initialize(self):
        """Initialize crawler with admin session"""
        print("Initializing enhanced crawler...")
        
        # Get admin user
        admin_response = self.supabase.table("users").select("*").eq("role", UserRole.ADMIN.value).execute()
        
        if not admin_response.data or len(admin_response.data) == 0:
            raise Exception("Admin user not found. Please login as admin first.")
        
        admin_user = admin_response.data[0]
        admin_id = admin_user["id"]
        
        print(f"Admin user: {admin_user['first_name']} (@{admin_user.get('username', 'N/A')})")
        
        # Load admin session
        session_response = self.supabase.table("telethon_sessions").select("*").eq("user_id", admin_id).execute()
        
        if not session_response.data or len(session_response.data) == 0:
            raise Exception("Admin session not found. Please login as admin first.")
        
        session_data = session_response.data[0]
        encrypted_session = session_data["session_data"]
        
        # Decrypt session
        session_string = session_encryption.decrypt(encrypted_session)
        
        # Create Telethon client
        self.client = TelegramClient(
            StringSession(session_string),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH
        )
        
        await self.client.connect()
        
        # Verify connection
        me = await self.client.get_me()
        print(f"Connected as: {me.first_name} (@{me.username})")
        
        # Load registered groups
        await self.load_groups()
    
    async def load_groups(self):
        """Load all crawl-enabled groups from database (public + private)"""
        print("Loading registered groups...")

        groups_response = self.supabase.table("groups").select("*").eq("crawl_enabled", True).execute()

        if not groups_response.data:
            print("No crawl-enabled groups found.")
            return
        
        for group in groups_response.data:
            self.group_id_map[group["id"]] = group["id"]  # groups.id IS telegram_id
            self.group_info_map[group["id"]] = group

        print(f"Loaded {len(self.group_id_map)} groups:")
        for group in groups_response.data:
            print(f"  - {group.get('title') or group.get('name', 'Unknown')} (ID: {group['id']})")

            # Initialize or get crawler status
            await self.init_crawler_status(group["id"], group["id"])  # groups.id IS telegram_id
    
    async def init_crawler_status(self, group_uuid: str, group_telegram_id: int):
        """Initialize or get crawler status for a group"""
        try:
            # Check if status exists
            status_response = self.supabase.table("crawler_status").select("*").eq("group_id", group_uuid).execute()
            
            if status_response.data and len(status_response.data) > 0:
                status_id = status_response.data[0]["id"]
                self.crawler_status_map[group_uuid] = status_id
                
                # Update status to active
                self.supabase.table("crawler_status").update({
                    "status": "active",
                    "is_enabled": True,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", status_id).execute()
            else:
                # Create new status
                status_data = {
                    "group_id": group_uuid,
                    "status": "active",
                    "is_enabled": True,
                    "error_count": 0,
                    "initial_crawl_progress": 0,
                    "initial_crawl_total": 0
                }
                result = self.supabase.table("crawler_status").insert(status_data).execute()
                if result.data:
                    self.crawler_status_map[group_uuid] = result.data[0]["id"]
        except Exception as e:
            print(f"Error initializing crawler status: {e}")
            await self.log_error(group_uuid, "INIT_ERROR", str(e))
    
    async def update_crawler_status(self, group_uuid: str, status: str, error: str = None,
                                   progress: int = None, total: int = None):
        """Update crawler status"""
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }

            if error:
                update_data["last_error"] = error
                # Read current error_count and increment manually
                try:
                    current = self.supabase.table("crawler_status").select("error_count").eq("group_id", group_uuid).execute()
                    current_count = current.data[0].get("error_count", 0) if current.data else 0
                    update_data["error_count"] = current_count + 1
                except Exception:
                    pass  # skip increment if read fails

            if progress is not None:
                update_data["initial_crawl_progress"] = progress

            if total is not None:
                update_data["initial_crawl_total"] = total

            self.supabase.table("crawler_status").update(update_data).eq("group_id", group_uuid).execute()
        except Exception as e:
            print(f"Error updating crawler status: {e}")
    
    async def log_error(self, group_uuid: str = None, error_type: str = "UNKNOWN", error_message: str = "", error_details: dict = None):
        """Log error to database"""
        try:
            error_data = {
                "group_id": group_uuid,
                "error_type": error_type,
                "error_message": error_message,
                "error_details": error_details or {},
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            self.supabase.table("crawler_error_logs").insert(error_data).execute()
        except Exception as e:
            print(f"Error logging error: {e}")
    
    async def crawl_historical_messages(self, group_telegram_id: int, days: int = 14):
        """Crawl historical messages from a group (single-pass, no pre-counting)"""
        group_uuid = self.group_id_map.get(group_telegram_id)
        if not group_uuid:
            return

        group_info = self.group_info_map.get(group_telegram_id, {})
        group_title = group_info.get("title") or group_info.get("name", str(group_telegram_id))

        print(f"\n=== Crawling historical messages for: {group_title} ===")

        try:
            await self.update_crawler_status(group_uuid, "initializing")

            group = await self.client.get_entity(group_telegram_id)
            date_threshold = datetime.now(timezone.utc) - timedelta(days=days)

            # Single pass: collect and save messages (no wasteful pre-counting)
            saved_count = 0
            batch_size = 100

            async for message in self.client.iter_messages(group, offset_date=date_threshold, reverse=True):
                try:
                    if message.text or message.media:
                        await self.save_message(message, group_telegram_id, group_uuid)
                        saved_count += 1

                        # Update progress every 50 messages (batched, not every 10)
                        if saved_count % 50 == 0:
                            await self.update_crawler_status(
                                group_uuid, "initializing", progress=saved_count, total=saved_count
                            )
                            print(f"Progress: {saved_count} messages saved...")

                        # Rate limiting: delay every batch_size messages
                        if saved_count % batch_size == 0:
                            await asyncio.sleep(1.5)
                except FloodWaitError as e:
                    print(f"FloodWaitError: Waiting {e.seconds} seconds...")
                    await self.update_crawler_status(group_uuid, "error", f"FloodWait: {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"Error processing message {message.id}: {e}")
                    await self.log_error(group_uuid, "MESSAGE_PROCESS_ERROR", str(e), {"message_id": message.id})

            # Update final status + last_message_at (single call)
            self.supabase.table("crawler_status").update({
                "status": "active",
                "initial_crawl_progress": saved_count,
                "initial_crawl_total": saved_count,
                "last_message_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("group_id", group_uuid).execute()

            print(f"Completed: Saved {saved_count} messages for {group_title}\n")
        except FloodWaitError as e:
            error_msg = f"FloodWait: {e.seconds}s"
            print(f"FloodWaitError: {error_msg}")
            await self.update_crawler_status(group_uuid, "error", error_msg)
            await self.log_error(group_uuid, "FLOOD_WAIT", error_msg, {"wait_seconds": e.seconds})
            await asyncio.sleep(e.seconds)
        except (ChannelPrivateError, ChatAdminRequiredError) as e:
            error_msg = f"Access denied: {str(e)}"
            print(f"Access error: {error_msg}")
            await self.update_crawler_status(group_uuid, "error", error_msg)
            await self.log_error(group_uuid, "ACCESS_ERROR", error_msg)
        except Exception as e:
            error_msg = str(e)
            print(f"Error crawling historical messages: {error_msg}")
            print(traceback.format_exc())
            await self.update_crawler_status(group_uuid, "error", error_msg)
            await self.log_error(group_uuid, "CRAWL_ERROR", error_msg, {"traceback": traceback.format_exc()})
    
    async def upload_media(self, message, group_uuid: str, media_type: str) -> tuple:
        """Download media from Telegram and upload to Supabase Storage.
        Returns (media_url, thumbnail_url). Falls back to (None, None) on error."""
        try:
            buffer = io.BytesIO()
            # For photos, download the photo directly; for docs, download thumbnail only
            if media_type == "photo":
                await self.client.download_media(message, buffer)
                content_type = "image/jpeg"
            else:
                # Try to download thumbnail for non-photo media
                if hasattr(message.media, 'document') and message.media.document:
                    thumbs = message.media.document.thumbs
                    if thumbs:
                        await self.client.download_media(message, buffer, thumb=0)
                        content_type = "image/jpeg"
                    else:
                        return None, None
                else:
                    return None, None

            buffer.seek(0)
            file_bytes = buffer.read()
            if not file_bytes:
                return None, None

            file_ext = "jpg" if "jpeg" in content_type or "jpg" in content_type else "bin"
            file_path = f"{group_uuid}/{message.id}.{file_ext}"

            self.supabase.storage.from_("message-media").upload(
                file_path, file_bytes, {"content-type": content_type}
            )
            public_url = self.supabase.storage.from_("message-media").get_public_url(file_path)

            if media_type == "photo":
                return public_url, None
            else:
                return None, public_url  # thumbnail
        except Exception as e:
            # Storage not configured or upload failed — graceful degradation
            if "not found" not in str(e).lower() and "bucket" not in str(e).lower():
                print(f"Media upload failed for message {message.id}: {e}")
            return None, None

    async def save_message(self, message, group_telegram_id: int, group_uuid: str,
                           is_edit: bool = False, download_media: bool = False):
        """Save or update a message to database"""
        try:
            # Determine media type
            media_type = None  # DB enum: photo, video, document, audio, sticker, voice (NULL=text)
            media_url = None

            if message.media:
                if isinstance(message.media, MessageMediaPhoto):
                    media_type = "photo"
                elif isinstance(message.media, MessageMediaDocument):
                    doc = message.media.document
                    if doc.mime_type:
                        if doc.mime_type.startswith('video'):
                            media_type = "video"
                        elif doc.mime_type.startswith('audio'):
                            media_type = "audio"
                        elif 'sticker' in doc.mime_type or 'webp' in doc.mime_type or 'tgsticker' in doc.mime_type:
                            media_type = "sticker"
                        elif 'ogg' in doc.mime_type and hasattr(doc, 'attributes'):
                            # voice messages are audio/ogg with voice attribute
                            media_type = "voice"
                        else:
                            media_type = "document"
                    # Check attributes for round video (video_note)
                    if hasattr(doc, 'attributes'):
                        for attr in doc.attributes:
                            attr_name = type(attr).__name__
                            if attr_name == 'DocumentAttributeVideo' and getattr(attr, 'round_message', False):
                                media_type = "video"  # DB enum has no video_note
                            elif attr_name == 'DocumentAttributeAudio' and getattr(attr, 'voice', False):
                                media_type = "voice"
                            elif attr_name == 'DocumentAttributeSticker':
                                media_type = "sticker"
                elif isinstance(message.media, MessageMediaWebPage):
                    media_type = None  # Treat webpage previews as text (NULL)

            # Download & upload media (only for real-time messages, not historical batch)
            if download_media and media_type is not None:
                media_url, _ = await self.upload_media(message, group_uuid, media_type)

            # Get sender info
            sender_id = message.sender_id
            sender_name = None
            sender_username = None

            if message.sender:
                sender_name = getattr(message.sender, 'first_name', None)
                if hasattr(message.sender, 'last_name') and message.sender.last_name:
                    sender_name = f"{sender_name} {message.sender.last_name}"
                sender_username = getattr(message.sender, 'username', None)

            # Get topic info (for forum/supergroup topics)
            topic_id = None
            if hasattr(message, 'reply_to') and message.reply_to:
                if hasattr(message.reply_to, 'forum_topic') and message.reply_to.forum_topic:
                    topic_id = getattr(message.reply_to, 'reply_to_top_id', None) or getattr(message.reply_to, 'reply_to_msg_id', None)

            # Prepare message data (columns matching actual DB schema)
            message_data = {
                "telegram_message_id": message.id,
                "group_id": group_uuid,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "content": message.text,
                "media_type": media_type,
                "media_url": media_url,
                "reply_to_message_id": message.reply_to_msg_id,
                "topic_id": topic_id,
                "is_deleted": False,
                "sent_at": message.date.isoformat()
            }

            # Upsert: insert new or update existing (atomic, no race condition)
            if not message_data.get("media_url"):
                message_data.pop("media_url", None)
            self.supabase.table("messages").upsert(
                message_data,
                on_conflict="telegram_message_id,group_id",
            ).execute()

            # NOTE: crawler_status.last_message_at is updated in batch by the caller
            # (crawl_historical_messages or realtime handler), NOT per-message.

        except Exception as e:
            print(f"Error saving message {message.id}: {e}")
            await self.log_error(group_uuid, "MESSAGE_SAVE_ERROR", str(e), {"message_id": message.id})
    
    async def periodic_group_refresh(self, interval_minutes: int = 5):
        """Periodically check for newly registered groups and crawl them"""
        while self.running:
            await asyncio.sleep(interval_minutes * 60)
            try:
                old_group_ids = set(self.group_id_map.keys())
                await self.load_groups()
                new_group_ids = set(self.group_id_map.keys()) - old_group_ids

                for group_id in new_group_ids:
                    group_title = self.group_info_map.get(group_id, {}).get("title", str(group_id))
                    print(f"\n[NEW GROUP] Detected: {group_title} — starting 14-day historical crawl")
                    await self.crawl_historical_messages(group_id, days=14)
            except Exception as e:
                print(f"[GROUP REFRESH] Error: {e}")
                await self.log_error(None, "GROUP_REFRESH_ERROR", str(e))

    async def periodic_message_cleanup(self, interval_hours: int = 1):
        """Delete messages older than 14 days (retention policy)"""
        while self.running:
            await asyncio.sleep(interval_hours * 3600)
            try:
                threshold = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
                result = self.supabase.table("messages").delete().lt("sent_at", threshold).execute()
                deleted_count = len(result.data) if result.data else 0
                if deleted_count > 0:
                    print(f"[CLEANUP] Deleted {deleted_count} messages older than 14 days")
            except Exception as e:
                print(f"[CLEANUP] Error: {e}")
                await self.log_error(None, "CLEANUP_ERROR", str(e))

    async def start_realtime_crawler(self):
        """Start real-time message crawler with event handlers"""
        print("\n=== Starting real-time crawler ===")

        # Cache is_enabled per group to avoid DB query per message
        self._enabled_cache: dict = {}  # group_uuid -> (is_enabled, cached_at_monotonic)
        CACHE_TTL = 60  # seconds

        async def is_group_enabled(group_uuid: str) -> bool:
            """Check if crawler is enabled for a group (cached)"""
            now = time.monotonic()
            cached = self._enabled_cache.get(group_uuid)
            if cached and (now - cached[1]) < CACHE_TTL:
                return cached[0]
            try:
                status = self.supabase.table("crawler_status").select("is_enabled").eq("group_id", group_uuid).execute()
                enabled = status.data[0].get("is_enabled", True) if status.data else True
                self._enabled_cache[group_uuid] = (enabled, now)
                return enabled
            except Exception:
                return True

        # Handler for new messages
        @self.client.on(events.NewMessage)
        async def new_message_handler(event):
            try:
                chat_id = event.chat_id

                if chat_id not in self.group_id_map:
                    return

                group_uuid = self.group_id_map[chat_id]
                group_title = self.group_info_map.get(chat_id, {}).get("title", str(chat_id))

                if not await is_group_enabled(group_uuid):
                    return

                print(f"[NEW] {group_title}: {event.text[:50] if event.text else '[media]'}")

                await self.save_message(event.message, chat_id, group_uuid, download_media=True)

                # Update last_message_at for real-time messages (per-event, not per-save)
                self.supabase.table("crawler_status").update({
                    "last_message_at": datetime.now(timezone.utc).isoformat()
                }).eq("group_id", group_uuid).execute()
            except Exception as e:
                print(f"Error handling new message: {e}")
                await self.log_error(group_uuid if 'group_uuid' in locals() else None, "NEW_MESSAGE_ERROR", str(e))

        # Handler for edited messages
        @self.client.on(events.MessageEdited)
        async def edited_message_handler(event):
            try:
                chat_id = event.chat_id

                if chat_id not in self.group_id_map:
                    return

                group_uuid = self.group_id_map[chat_id]
                group_title = self.group_info_map.get(chat_id, {}).get("title", str(chat_id))

                print(f"[EDIT] {group_title}: Message {event.message.id}")

                await self.save_message(event.message, chat_id, group_uuid, is_edit=True)
            except Exception as e:
                print(f"Error handling edited message: {e}")
                await self.log_error(group_uuid if 'group_uuid' in locals() else None, "EDIT_MESSAGE_ERROR", str(e))

        # Handler for deleted messages
        @self.client.on(events.MessageDeleted)
        async def deleted_message_handler(event):
            try:
                chat_id = event.chat_id

                if chat_id not in self.group_id_map:
                    return

                group_uuid = self.group_id_map[chat_id]
                group_title = self.group_info_map.get(chat_id, {}).get("title", str(chat_id))

                print(f"[DELETE] {group_title}: {len(event.deleted_ids)} messages")

                # Mark messages as deleted
                for msg_id in event.deleted_ids:
                    self.supabase.table("messages").update({
                        "is_deleted": True,
                    }).eq("telegram_message_id", msg_id).eq("group_id", group_uuid).execute()
            except Exception as e:
                print(f"Error handling deleted message: {e}")
                await self.log_error(group_uuid if 'group_uuid' in locals() else None, "DELETE_MESSAGE_ERROR", str(e))

        self.running = True
        print("Real-time crawler started. Listening for events...")
        print("  - NewMessage")
        print("  - MessageEdited")
        print("  - MessageDeleted\n")

        # Keep running
        await self.client.run_until_disconnected()
    
    async def run(self):
        """Main crawler loop"""
        try:
            await self.initialize()

            # Phase 1: Crawl historical messages (14 days) for all groups
            print("\n" + "="*60)
            print("PHASE 1: Historical Message Collection (14 days)")
            print("="*60)

            for group_telegram_id in self.group_id_map.keys():
                await self.crawl_historical_messages(group_telegram_id, days=14)

            print("\n" + "="*60)
            print("PHASE 1 COMPLETE: Historical crawling finished")
            print("="*60 + "\n")

            # Phase 2: Start concurrent background tasks
            print("="*60)
            print("PHASE 2: Real-time Monitoring + Background Tasks")
            print("="*60)

            self.running = True

            # Start background tasks concurrently with real-time crawler
            group_refresh_task = asyncio.create_task(self.periodic_group_refresh(interval_minutes=5))
            cleanup_task = asyncio.create_task(self.periodic_message_cleanup(interval_hours=1))

            print("  Background tasks started:")
            print("    - Group refresh: every 5 minutes")
            print("    - Message cleanup (>14 days): every 1 hour\n")

            try:
                await self.start_realtime_crawler()
            finally:
                group_refresh_task.cancel()
                cleanup_task.cancel()

        except KeyboardInterrupt:
            print("\n\nCrawler stopped by user")
        except Exception as e:
            print(f"\n\nCrawler error: {e}")
            print(traceback.format_exc())
            await self.log_error(None, "CRAWLER_FATAL_ERROR", str(e), {"traceback": traceback.format_exc()})
            raise
        finally:
            self.running = False
            if self.client:
                await self.client.disconnect()
    
    async def stop(self):
        """Stop crawler"""
        self.running = False
        
        # Update all crawler statuses to inactive
        for group_uuid in self.crawler_status_map.keys():
            await self.update_crawler_status(group_uuid, "inactive")
        
        if self.client:
            await self.client.disconnect()


async def main():
    """Main entry point"""
    print("="*60)
    print("AaltoHub v2 - Enhanced Message Crawler")
    print("="*60 + "\n")
    
    crawler = EnhancedMessageCrawler()
    await crawler.run()


if __name__ == "__main__":
    asyncio.run(main())
