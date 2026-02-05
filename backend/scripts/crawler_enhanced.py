"""
Telegram message crawler daemon - Enhanced Version
Runs 24/7 on AWS EC2 to collect messages from registered groups
Features:
- Initial 30-day message load with progress tracking
- Real-time message collection (NewMessage, MessageEdited, MessageDeleted)
- Topic/Forum support
- Rate limit handling (FloodWaitError)
- Crawler status tracking
- Error logging
"""
import asyncio
import sys
import os
from datetime import datetime, timedelta
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
        """Load all public groups from database"""
        print("Loading registered groups...")
        
        groups_response = self.supabase.table("telegram_groups").select("*").eq("visibility", "public").eq("admin_invited", True).execute()
        
        if not groups_response.data:
            print("No public groups found.")
            return
        
        for group in groups_response.data:
            self.group_id_map[group["telegram_id"]] = group["id"]
            self.group_info_map[group["telegram_id"]] = group
        
        print(f"Loaded {len(self.group_id_map)} groups:")
        for group in groups_response.data:
            print(f"  - {group['title']} (ID: {group['telegram_id']})")
            
            # Initialize or get crawler status
            await self.init_crawler_status(group["id"], group["telegram_id"])
    
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
                    "updated_at": datetime.utcnow().isoformat()
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
                "updated_at": datetime.utcnow().isoformat()
            }
            
            if error:
                update_data["last_error"] = error
                update_data["error_count"] = self.supabase.rpc("increment", {"x": 1, "row_id": self.crawler_status_map.get(group_uuid)}).execute()
            
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
                "created_at": datetime.utcnow().isoformat()
            }
            self.supabase.table("crawler_error_logs").insert(error_data).execute()
        except Exception as e:
            print(f"Error logging error: {e}")
    
    async def crawl_historical_messages(self, group_telegram_id: int, days: int = 30):
        """Crawl historical messages from a group with progress tracking"""
        group_uuid = self.group_id_map.get(group_telegram_id)
        if not group_uuid:
            return
        
        group_info = self.group_info_map.get(group_telegram_id, {})
        group_title = group_info.get("title", str(group_telegram_id))
        
        print(f"\n=== Crawling historical messages for: {group_title} ===")
        
        try:
            # Update status to initializing
            await self.update_crawler_status(group_uuid, "initializing")
            
            # Get group entity
            group = await self.client.get_entity(group_telegram_id)
            
            # Calculate date threshold
            date_threshold = datetime.utcnow() - timedelta(days=days)
            
            # First pass: count total messages
            print(f"Counting messages...")
            total_messages = 0
            async for _ in self.client.iter_messages(group, offset_date=date_threshold):
                total_messages += 1
            
            print(f"Found {total_messages} messages to crawl")
            await self.update_crawler_status(group_uuid, "initializing", total=total_messages)
            
            # Second pass: collect and save messages
            saved_count = 0
            batch = []
            batch_size = 100
            
            async for message in self.client.iter_messages(group, offset_date=date_threshold, reverse=True):
                try:
                    if message.text or message.media:
                        await self.save_message(message, group_telegram_id, group_uuid)
                        saved_count += 1
                        
                        # Update progress every 10 messages
                        if saved_count % 10 == 0:
                            await self.update_crawler_status(group_uuid, "initializing", progress=saved_count)
                            print(f"Progress: {saved_count}/{total_messages} ({int(saved_count/total_messages*100)}%)")
                        
                        # Rate limiting: delay every batch_size messages
                        if saved_count % batch_size == 0:
                            await asyncio.sleep(1.5)
                except FloodWaitError as e:
                    wait_seconds = e.seconds
                    print(f"FloodWaitError: Waiting {wait_seconds} seconds...")
                    await self.update_crawler_status(group_uuid, "error", f"FloodWait: {wait_seconds}s")
                    await asyncio.sleep(wait_seconds)
                except Exception as e:
                    print(f"Error processing message {message.id}: {e}")
                    await self.log_error(group_uuid, "MESSAGE_PROCESS_ERROR", str(e), {"message_id": message.id})
            
            # Update final status
            await self.update_crawler_status(group_uuid, "active", progress=saved_count, total=total_messages)
            await self.supabase.table("crawler_status").update({
                "last_message_at": datetime.utcnow().isoformat()
            }).eq("group_id", group_uuid).execute()
            
            print(f"✓ Completed: Saved {saved_count}/{total_messages} messages for {group_title}\n")
        except FloodWaitError as e:
            wait_seconds = e.seconds
            error_msg = f"FloodWait: {wait_seconds}s"
            print(f"FloodWaitError: {error_msg}")
            await self.update_crawler_status(group_uuid, "error", error_msg)
            await self.log_error(group_uuid, "FLOOD_WAIT", error_msg, {"wait_seconds": wait_seconds})
            await asyncio.sleep(wait_seconds)
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
    
    async def save_message(self, message, group_telegram_id: int, group_uuid: str, is_edit: bool = False):
        """Save or update a message to database"""
        try:
            # Determine media type
            media_type = "text"
            media_url = None
            media_thumbnail_url = None
            
            if message.media:
                if isinstance(message.media, MessageMediaPhoto):
                    media_type = "photo"
                    # TODO: Download and upload to S3
                elif isinstance(message.media, MessageMediaDocument):
                    doc = message.media.document
                    if doc.mime_type:
                        if doc.mime_type.startswith('video'):
                            media_type = "video"
                        elif doc.mime_type.startswith('audio'):
                            media_type = "audio"
                        elif 'sticker' in doc.mime_type:
                            media_type = "sticker"
                        elif 'voice' in doc.mime_type:
                            media_type = "voice"
                        else:
                            media_type = "document"
                elif isinstance(message.media, MessageMediaWebPage):
                    media_type = "text"  # Treat webpage previews as text
            
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
                    topic_id = message.reply_to.reply_to_top_id
            
            # Prepare message data
            message_data = {
                "telegram_message_id": message.id,
                "group_id": group_uuid,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "sender_username": sender_username,
                "content": message.text,
                "media_type": media_type,
                "media_url": media_url,
                "media_thumbnail_url": media_thumbnail_url,
                "reply_to_message_id": message.reply_to_msg_id,
                "topic_id": topic_id,
                "is_deleted": False,
                "edit_count": 1 if is_edit else 0,
                "sent_at": message.date.isoformat()
            }
            
            if is_edit:
                message_data["edited_at"] = datetime.utcnow().isoformat()
            
            # Check if message exists
            existing = self.supabase.table("messages").select("id, edit_count").eq("telegram_message_id", message.id).eq("group_id", group_uuid).execute()
            
            if existing.data and len(existing.data) > 0:
                # Update existing message
                if is_edit:
                    message_data["edit_count"] = existing.data[0].get("edit_count", 0) + 1
                self.supabase.table("messages").update(message_data).eq("id", existing.data[0]["id"]).execute()
            else:
                # Insert new message
                self.supabase.table("messages").insert(message_data).execute()
            
            # Update crawler status last_message_at
            self.supabase.table("crawler_status").update({
                "last_message_at": datetime.utcnow().isoformat()
            }).eq("group_id", group_uuid).execute()
            
        except Exception as e:
            print(f"Error saving message {message.id}: {e}")
            await self.log_error(group_uuid, "MESSAGE_SAVE_ERROR", str(e), {"message_id": message.id})
    
    async def start_realtime_crawler(self):
        """Start real-time message crawler with event handlers"""
        print("\n=== Starting real-time crawler ===")
        
        # Handler for new messages
        @self.client.on(events.NewMessage)
        async def new_message_handler(event):
            try:
                chat_id = event.chat_id
                
                if chat_id not in self.group_id_map:
                    return
                
                group_uuid = self.group_id_map[chat_id]
                group_title = self.group_info_map.get(chat_id, {}).get("title", str(chat_id))
                
                # Check if crawler is enabled for this group
                status = self.supabase.table("crawler_status").select("is_enabled").eq("group_id", group_uuid).execute()
                if not status.data or not status.data[0].get("is_enabled", True):
                    return
                
                print(f"[NEW] {group_title}: {event.text[:50] if event.text else '[media]'}")
                
                await self.save_message(event.message, chat_id, group_uuid)
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
                        "edited_at": datetime.utcnow().isoformat()
                    }).eq("telegram_message_id", msg_id).eq("group_id", group_uuid).execute()
            except Exception as e:
                print(f"Error handling deleted message: {e}")
                await self.log_error(group_uuid if 'group_uuid' in locals() else None, "DELETE_MESSAGE_ERROR", str(e))
        
        self.running = True
        print("✓ Real-time crawler started. Listening for events...")
        print("  - NewMessage")
        print("  - MessageEdited")
        print("  - MessageDeleted\n")
        
        # Keep running
        await self.client.run_until_disconnected()
    
    async def run(self):
        """Main crawler loop"""
        try:
            await self.initialize()
            
            # Crawl historical messages for all groups
            print("\n" + "="*60)
            print("PHASE 1: Historical Message Collection (30 days)")
            print("="*60)
            
            for group_telegram_id in self.group_id_map.keys():
                await self.crawl_historical_messages(group_telegram_id, days=30)
            
            print("\n" + "="*60)
            print("PHASE 1 COMPLETE: Historical crawling finished")
            print("="*60 + "\n")
            
            # Start real-time crawler
            print("="*60)
            print("PHASE 2: Real-time Message Monitoring")
            print("="*60)
            await self.start_realtime_crawler()
            
        except KeyboardInterrupt:
            print("\n\nCrawler stopped by user")
        except Exception as e:
            print(f"\n\nCrawler error: {e}")
            print(traceback.format_exc())
            await self.log_error(None, "CRAWLER_FATAL_ERROR", str(e), {"traceback": traceback.format_exc()})
            raise
        finally:
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
