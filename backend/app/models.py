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
    id: int  # BIGSERIAL from Supabase
    role: UserRole
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# Auth Models
# ============================================================

class SendCodeRequest(BaseModel):
    phone_or_username: str = Field(..., description="Phone number (+358...) or username", max_length=64)


class SendCodeResponse(BaseModel):
    success: bool
    message: str
    phone_code_hash: Optional[str] = None
    requires_2fa: bool = False


class VerifyCodeRequest(BaseModel):
    phone_or_username: str = Field(..., max_length=64)
    code: str = Field(..., max_length=10)
    phone_code_hash: str = Field(..., max_length=256)


class Verify2FARequest(BaseModel):
    phone_or_username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=256)
    phone_code_hash: str = Field(..., max_length=256)


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
    username: Optional[str] = None  # from Telegram API (not stored in DB)
    member_count: Optional[int] = None
    group_type: Optional[GroupType] = None
    photo_url: Optional[str] = None


class TelegramGroupInfo(TelegramGroupBase):
    """Group info from Telegram API (not yet registered)"""
    is_registered: bool = False


class TelegramGroupCreate(TelegramGroupBase):
    visibility: GroupVisibility = GroupVisibility.PUBLIC
    registered_by: int


class TelegramGroupResponse(TelegramGroupBase):
    id: Optional[str] = None
    visibility: GroupVisibility
    invite_link: Optional[str] = None
    registered_by: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RegisterGroupItem(BaseModel):
    telegram_id: int
    title: str = Field(..., max_length=256)
    username: Optional[str] = Field(None, max_length=64)
    member_count: Optional[int] = None
    group_type: Optional[GroupType] = GroupType.GROUP
    visibility: Optional[GroupVisibility] = GroupVisibility.PUBLIC


class RegisterGroupsRequest(BaseModel):
    groups: List[RegisterGroupItem] = Field(..., description="List of groups to register")


class RegisterGroupsResponse(BaseModel):
    success: bool
    registered_groups: List[TelegramGroupResponse]


# ============================================================
# Message Models
# ============================================================

class MessageBase(BaseModel):
    telegram_message_id: int
    group_id: int  # telegram_group_id
    sender_id: Optional[int] = None
    sender_name: Optional[str] = None
    content: Optional[str] = None
    media_type: Optional[str] = None  # DB enum: photo, video, document, audio, sticker, voice (NULL=text)
    media_url: Optional[str] = None
    reply_to_message_id: Optional[int] = None
    topic_id: Optional[int] = None
    sent_at: datetime


class MessageCreate(MessageBase):
    pass


class MessageResponse(MessageBase):
    id: str  # UUID for messages
    is_deleted: bool = False
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
