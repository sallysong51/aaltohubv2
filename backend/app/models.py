"""
Pydantic models for request/response validation
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ============================================================
# Enums
# ============================================================

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"


class GroupType(str, Enum):
    GROUP = "group"
    SUPERGROUP = "supergroup"
    CHANNEL = "channel"


class GroupVisibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"


class MediaType(str, Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    AUDIO = "audio"
    STICKER = "sticker"
    VOICE = "voice"
    VIDEO_NOTE = "video_note"


class CrawlerStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    INITIALIZING = "initializing"


# ============================================================
# User Models
# ============================================================

class UserBase(BaseModel):
    telegram_id: int
    phone_number: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class UserCreate(UserBase):
    role: UserRole = UserRole.USER


class UserResponse(UserBase):
    role: UserRole
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================
# Auth Models
# ============================================================

class SendCodeRequest(BaseModel):
    phone_or_username: str = Field(..., description="Phone number (+358...) or username")


class SendCodeResponse(BaseModel):
    success: bool
    message: str
    phone_code_hash: Optional[str] = None
    requires_2fa: bool = False


class VerifyCodeRequest(BaseModel):
    phone_or_username: str
    code: str
    phone_code_hash: str


class Verify2FARequest(BaseModel):
    phone_or_username: str
    password: str
    phone_code_hash: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ============================================================
# Telegram Group Models
# ============================================================

class TelegramGroupBase(BaseModel):
    telegram_id: int
    title: str
    username: Optional[str] = None
    member_count: Optional[int] = None
    group_type: Optional[GroupType] = None


class TelegramGroupInfo(TelegramGroupBase):
    """Group info from Telegram API (not yet registered)"""
    is_registered: bool = False


class TelegramGroupCreate(TelegramGroupBase):
    visibility: GroupVisibility = GroupVisibility.PUBLIC
    registered_by: int  # telegram_id of the user


class TelegramGroupResponse(TelegramGroupBase):
    visibility: GroupVisibility
    invite_link: Optional[str] = None
    registered_by: Optional[int] = None  # telegram_id
    admin_invited: bool = False
    admin_invite_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class RegisterGroupsRequest(BaseModel):
    groups: List[dict] = Field(..., description="List of groups to register")
    # Each group: { telegram_id, title, username, member_count, group_type, visibility }


class RegisterGroupsResponse(BaseModel):
    success: bool
    registered_groups: List[TelegramGroupResponse]
    failed_invites: List[dict] = []


# ============================================================
# Message Models
# ============================================================

class MessageBase(BaseModel):
    telegram_message_id: int
    group_id: int  # telegram_group_id
    sender_id: Optional[int] = None
    sender_name: Optional[str] = None
    sender_username: Optional[str] = None
    content: Optional[str] = None
    media_type: MediaType = MediaType.TEXT
    media_url: Optional[str] = None
    media_thumbnail_url: Optional[str] = None
    reply_to_message_id: Optional[int] = None
    topic_id: Optional[int] = None
    topic_title: Optional[str] = None
    sent_at: datetime


class MessageCreate(MessageBase):
    pass


class MessageResponse(MessageBase):
    id: str  # UUID for messages
    is_deleted: bool = False
    edited_at: Optional[datetime] = None
    edit_count: int = 0
    created_at: datetime
    
    class Config:
        from_attributes = True


class MessagesListResponse(BaseModel):
    messages: List[MessageResponse]
    total: int
    page: int
    page_size: int
    has_more: bool


# ============================================================
# Crawler Models
# ============================================================

class CrawlerStatusResponse(BaseModel):
    group_id: str
    is_active: bool
    last_message_id: Optional[int] = None
    last_crawled_at: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None


class StartCrawlerRequest(BaseModel):
    group_ids: Optional[List[str]] = None  # None = all public groups


class StopCrawlerRequest(BaseModel):
    group_ids: Optional[List[str]] = None  # None = all groups


# ============================================================
# Private Group Invite Models
# ============================================================

class CreateInviteRequest(BaseModel):
    group_id: str
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None


class InviteResponse(BaseModel):
    id: str
    group_id: str
    invite_code: str
    invite_url: str
    created_by: str
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None
    current_uses: int = 0
    is_active: bool = True
    created_at: datetime


# ============================================================
# Crawler Status Models
# ============================================================

class CrawlerStatusResponse(BaseModel):
    id: str
    group_id: str
    status: CrawlerStatus
    last_message_at: Optional[datetime] = None
    last_error: Optional[str] = None
    error_count: int = 0
    is_enabled: bool = True
    initial_crawl_progress: int = 0
    initial_crawl_total: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class CrawlerStatusUpdate(BaseModel):
    is_enabled: Optional[bool] = None
    status: Optional[CrawlerStatus] = None


class CrawlerErrorLogResponse(BaseModel):
    id: str
    group_id: Optional[str] = None
    error_type: str
    error_message: str
    error_details: Optional[dict] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============================================================
# Private Group Invite Models
# ============================================================

class PrivateGroupInviteCreate(BaseModel):
    group_id: str
    expires_at: Optional[datetime] = None
    max_uses: Optional[int] = None


class PrivateGroupInviteResponse(BaseModel):
    id: str
    group_id: str
    token: str
    created_by: str
    expires_at: Optional[datetime] = None
    is_revoked: bool = False
    revoked_at: Optional[datetime] = None
    used_count: int = 0
    max_uses: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class InviteAcceptRequest(BaseModel):
    token: str


# ============================================================
# Group Settings Update Models
# ============================================================

class GroupVisibilityUpdate(BaseModel):
    visibility: GroupVisibility


# ============================================================
# Admin Statistics Models
# ============================================================

class AdminStatsResponse(BaseModel):
    total_users: int
    total_groups: int
    total_public_groups: int
    total_messages: int
    messages_last_24h: int


class UserActivityResponse(BaseModel):
    user_id: str
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    role: UserRole
    registered_groups_count: int
    joined_at: datetime
