"""
Telegram message crawler daemon
Runs 24/7 on AWS EC2 to collect messages from registered groups
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from supabase import create_client
from app.config import settings
from app.encryption import session_encryption
from app.models import UserRole


class MessageCrawler:
    """Telegram message crawler"""
    
    def __init__(self):
        self.client = None
        self.supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        self.group_id_map = {}  # telegram_id -> uuid mapping
        self.running = False
    
    async def initialize(self):
        """Initialize crawler with admin session"""
        print("Initializing crawler...")
        
        # Get admin user
        admin_response = self.supabase.table("users").select("*").eq("role", UserRole.ADMIN.value).execute()
        
        if not admin_response.data or len(admin_response.data) == 0:
            raise Exception("Admin user not found. Please login as admin first.")
        
        admin_user = admin_response.data[0]
        admin_id = admin_user["id"]
        
        print(f"Admin user: {admin_user['first_name']} (@{admin_user['username']})")
        
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
        """Load all public groups from database"""
        print("Loading registered groups...")

        groups_response = self.supabase.table("groups").select("*").eq("visibility", "public").eq("crawl_enabled", True).execute()

        if not groups_response.data:
            print("No public groups found.")
            return

        # groups.id IS the telegram group ID
        self.group_id_map = {
            group["id"]: group["id"]
            for group in groups_response.data
        }

        print(f"Loaded {len(self.group_id_map)} groups:")
        for group in groups_response.data:
            print(f"  - {group.get('title') or group.get('name', 'Unknown')} (ID: {group['id']})")
    
    async def crawl_historical_messages(self, group_telegram_id: int, days: int = 14):
        """Crawl historical messages from a group"""
        group_uuid = self.group_id_map.get(group_telegram_id)
        if not group_uuid:
            return
        
        print(f"Crawling historical messages for group {group_telegram_id}...")
        
        try:
            # Get group entity
            group = await self.client.get_entity(group_telegram_id)
            
            # Calculate date threshold
            date_threshold = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Get messages
            messages = []
            async for message in self.client.iter_messages(group, offset_date=date_threshold, reverse=True):
                if message.text or message.media:
                    messages.append(message)
            
            print(f"Found {len(messages)} messages")
            
            # Save messages to database
            for message in messages:
                await self.save_message(message, group_telegram_id, group_uuid)
            
            print(f"Saved {len(messages)} messages for group {group_telegram_id}")
        except Exception as e:
            print(f"Error crawling historical messages: {e}")
    
    async def save_message(self, message, group_telegram_id: int, group_uuid: str):
        """Save a message to database"""
        try:
            # Determine media type
            media_type = None  # DB enum: photo, video, document, audio, sticker, voice (NULL=text)
            media_url = None
            
            if message.media:
                if hasattr(message.media, 'photo'):
                    media_type = "photo"
                elif hasattr(message.media, 'document'):
                    if message.media.document.mime_type.startswith('video'):
                        media_type = "video"
                    elif message.media.document.mime_type.startswith('audio'):
                        media_type = "audio"
                    else:
                        media_type = "document"
                elif hasattr(message.media, 'webpage'):
                    media_type = None
            
            # Get sender info
            sender_id = message.sender_id
            sender_name = None
            sender_username = None
            
            if message.sender:
                sender_name = getattr(message.sender, 'first_name', None)
                sender_username = getattr(message.sender, 'username', None)
            
            # Prepare message data
            message_data = {
                "telegram_message_id": message.id,
                "group_id": group_uuid,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "content": message.text,
                "media_type": media_type,
                "media_url": media_url,
                "reply_to_message_id": message.reply_to_msg_id,
                "sent_at": message.date.isoformat()
            }
            
            # Upsert into database (ON CONFLICT DO NOTHING for duplicates)
            self.supabase.table("messages").upsert(
                message_data,
                on_conflict="telegram_message_id,group_id",
                ignore_duplicates=True,
            ).execute()
        except Exception as e:
            print(f"Error saving message {message.id}: {e}")
    
    async def start_realtime_crawler(self):
        """Start real-time message crawler"""
        print("Starting real-time crawler...")
        
        @self.client.on(events.NewMessage)
        async def handler(event):
            # Check if message is from a registered group
            chat_id = event.chat_id
            
            if chat_id not in self.group_id_map:
                return
            
            group_uuid = self.group_id_map[chat_id]
            
            print(f"New message in group {chat_id}: {event.text[:50] if event.text else '[media]'}")
            
            # Save message
            await self.save_message(event.message, chat_id, group_uuid)
        
        self.running = True
        print("Real-time crawler started. Listening for new messages...")
        
        # Keep running
        await self.client.run_until_disconnected()
    
    async def run(self):
        """Main crawler loop"""
        try:
            await self.initialize()
            
            # Crawl historical messages for all groups
            print("\n=== Crawling historical messages ===")
            for group_telegram_id in self.group_id_map.keys():
                await self.crawl_historical_messages(group_telegram_id, days=14)
            
            print("\n=== Historical crawling complete ===\n")
            
            # Start real-time crawler
            await self.start_realtime_crawler()
        except KeyboardInterrupt:
            print("\nCrawler stopped by user")
        except Exception as e:
            print(f"Crawler error: {e}")
            raise
        finally:
            if self.client:
                await self.client.disconnect()
    
    async def stop(self):
        """Stop crawler"""
        self.running = False
        if self.client:
            await self.client.disconnect()


async def main():
    """Main entry point"""
    import warnings
    import fcntl
    warnings.warn(
        "DEPRECATED: crawler.py is superseded by live_crawler.py (integrated into the FastAPI app). "
        "Running this standalone script alongside the API service will cause Telegram session conflicts. "
        "Use the API service instead: systemctl start aaltohub-api",
        DeprecationWarning,
        stacklevel=2,
    )
    print("WARNING: This crawler is DEPRECATED. Use the live_crawler integrated in the API service.")
    print("Continuing in 5 seconds... (Ctrl+C to abort)")
    await asyncio.sleep(5)

    # Acquire file lock (same path as live_crawler) to prevent session conflicts
    lock_dir = Path(__file__).resolve().parent.parent  # backend/
    lock_path = str(lock_dir / "aaltohub-crawler.lock")
    lock_file = open(lock_path, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        print(f"ERROR: Another crawler is already running (lock: {lock_path}). Aborting.")
        lock_file.close()
        return

    try:
        crawler = MessageCrawler()
        await crawler.run()
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    asyncio.run(main())
