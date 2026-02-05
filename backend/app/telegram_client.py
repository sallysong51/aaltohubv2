"""
Telethon client manager for Telegram API interactions
"""
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.types import InputUser
from typing import Optional, List, Dict
from app.config import settings
from app.encryption import session_encryption
from app.database import get_db
from app.models import UserRole


class TelegramClientManager:
    """Manage Telethon clients for users"""
    
    def __init__(self):
        self.clients: Dict[str, TelegramClient] = {}
        self.admin_client: Optional[TelegramClient] = None
    
    async def create_client(self, phone_or_username: str) -> TelegramClient:
        """Create a new Telethon client for authentication"""
        client = TelegramClient(
            StringSession(),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH
        )
        await client.connect()
        return client
    
    async def send_code(self, phone_or_username: str) -> Dict:
        """Send authentication code to user"""
        client = await self.create_client(phone_or_username)
        
        try:
            # Send code request
            sent_code = await client.send_code_request(phone_or_username)
            
            # Store client temporarily (in production, use Redis or similar)
            self.clients[phone_or_username] = client
            
            return {
                "success": True,
                "phone_code_hash": sent_code.phone_code_hash,
                "requires_2fa": False
            }
        except Exception as e:
            await client.disconnect()
            raise Exception(f"Failed to send code: {str(e)}")
    
    async def verify_code(
        self,
        phone_or_username: str,
        code: str,
        phone_code_hash: str
    ) -> Dict:
        """Verify authentication code and sign in"""
        client = self.clients.get(phone_or_username)
        if not client:
            raise Exception("Client not found. Please request code again.")
        
        try:
            # Sign in with code
            await client.sign_in(phone_or_username, code, phone_code_hash=phone_code_hash)
            
            # Get user info
            me = await client.get_me()
            
            # Save session
            session_string = client.session.save()
            
            return {
                "success": True,
                "session_string": session_string,
                "user_info": {
                    "telegram_id": me.id,
                    "phone_number": me.phone,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name
                },
                "requires_2fa": False
            }
        except SessionPasswordNeededError:
            # 2FA is enabled
            return {
                "success": False,
                "requires_2fa": True,
                "message": "Two-factor authentication is enabled. Please provide your password."
            }
        except PhoneCodeInvalidError:
            await client.disconnect()
            del self.clients[phone_or_username]
            raise Exception("Invalid verification code")
        except Exception as e:
            await client.disconnect()
            if phone_or_username in self.clients:
                del self.clients[phone_or_username]
            raise Exception(f"Failed to verify code: {str(e)}")
    
    async def verify_2fa(
        self,
        phone_or_username: str,
        password: str
    ) -> Dict:
        """Verify 2FA password and complete sign in"""
        client = self.clients.get(phone_or_username)
        if not client:
            raise Exception("Client not found. Please request code again.")
        
        try:
            # Sign in with password
            await client.sign_in(password=password)
            
            # Get user info
            me = await client.get_me()
            
            # Save session
            session_string = client.session.save()
            
            return {
                "success": True,
                "session_string": session_string,
                "user_info": {
                    "telegram_id": me.id,
                    "phone_number": me.phone,
                    "username": me.username,
                    "first_name": me.first_name,
                    "last_name": me.last_name
                }
            }
        except Exception as e:
            await client.disconnect()
            if phone_or_username in self.clients:
                del self.clients[phone_or_username]
            raise Exception(f"Failed to verify 2FA: {str(e)}")
    
    async def save_session(self, user_id: str, session_string: str):
        """Encrypt and save Telethon session to database"""
        db = get_db()
        
        # Encrypt session
        encrypted_session = session_encryption.encrypt(session_string)
        key_hash = session_encryption.get_key_hash()
        
        # Save to database
        try:
            # Check if session exists
            existing = db.table("telethon_sessions").select("*").eq("user_id", user_id).execute()
            
            if existing.data and len(existing.data) > 0:
                # Update existing session
                db.table("telethon_sessions").update({
                    "session_data": encrypted_session,
                    "encryption_key_hash": key_hash,
                    "is_active": True,
                    "last_used_at": "now()"
                }).eq("user_id", user_id).execute()
            else:
                # Insert new session
                db.table("telethon_sessions").insert({
                    "user_id": user_id,
                    "session_data": encrypted_session,
                    "encryption_key_hash": key_hash,
                    "is_active": True
                }).execute()
        except Exception as e:
            raise Exception(f"Failed to save session: {str(e)}")
    
    async def load_session(self, user_id: str) -> Optional[str]:
        """Load and decrypt Telethon session from database"""
        db = get_db()
        
        try:
            response = db.table("telethon_sessions").select("*").eq("user_id", user_id).execute()
            
            if not response.data or len(response.data) == 0:
                return None
            
            session_data = response.data[0]
            encrypted_session = session_data["session_data"]
            
            # Decrypt session
            session_string = session_encryption.decrypt(encrypted_session)
            return session_string
        except Exception as e:
            raise Exception(f"Failed to load session: {str(e)}")
    
    async def get_user_client(self, user_id: str) -> TelegramClient:
        """Get or create Telethon client for user"""
        # Load session from database
        session_string = await self.load_session(user_id)
        if not session_string:
            raise Exception("Session not found for user")
        
        # Create client with saved session
        client = TelegramClient(
            StringSession(session_string),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH
        )
        await client.connect()
        
        return client
    
    async def get_admin_client(self) -> TelegramClient:
        """Get admin Telethon client (for inviting to groups)"""
        if self.admin_client and self.admin_client.is_connected():
            return self.admin_client
        
        # Find admin user
        db = get_db()
        admin_response = db.table("users").select("*").eq("role", UserRole.ADMIN.value).execute()
        
        if not admin_response.data or len(admin_response.data) == 0:
            raise Exception("Admin user not found")
        
        admin_user = admin_response.data[0]
        admin_id = admin_user["id"]
        
        # Load admin session
        session_string = await self.load_session(admin_id)
        if not session_string:
            raise Exception("Admin session not found")
        
        # Create admin client
        self.admin_client = TelegramClient(
            StringSession(session_string),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH
        )
        await self.admin_client.connect()
        
        return self.admin_client
    
    async def get_user_groups(self, user_id: str) -> List[Dict]:
        """Get all groups/channels user is member of"""
        client = await self.get_user_client(user_id)
        
        try:
            dialogs = await client.get_dialogs()
            groups = []
            
            for dialog in dialogs:
                entity = dialog.entity
                
                # Only include groups, supergroups, and channels
                if hasattr(entity, 'megagroup') or hasattr(entity, 'broadcast'):
                    group_info = {
                        "telegram_id": entity.id,
                        "title": entity.title,
                        "username": entity.username if hasattr(entity, 'username') else None,
                        "member_count": entity.participants_count if hasattr(entity, 'participants_count') else None,
                        "group_type": "supergroup" if hasattr(entity, 'megagroup') and entity.megagroup else (
                            "channel" if hasattr(entity, 'broadcast') and entity.broadcast else "group"
                        )
                    }
                    groups.append(group_info)
            
            return groups
        except Exception as e:
            raise Exception(f"Failed to get user groups: {str(e)}")
        finally:
            await client.disconnect()
    
    async def invite_admin_to_group(self, group_telegram_id: int) -> Dict:
        """Invite admin to a public group"""
        try:
            admin_client = await self.get_admin_client()
            
            # Get the group entity
            group = await admin_client.get_entity(group_telegram_id)
            
            # Check if admin is already a member
            try:
                participants = await admin_client.get_participants(group, limit=1)
                # If we can get participants, admin is already a member
                return {
                    "success": True,
                    "message": "Admin is already a member"
                }
            except:
                pass
            
            # Get admin user entity
            admin_user = await admin_client.get_me()
            
            # Invite admin to group
            await admin_client(InviteToChannelRequest(
                group,
                [InputUser(admin_user.id, admin_user.access_hash)]
            ))
            
            return {
                "success": True,
                "message": "Admin invited successfully"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global Telegram client manager
telegram_manager = TelegramClientManager()
