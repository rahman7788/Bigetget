from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Literal
from datetime import datetime
import uuid


# User Models
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    username: str = Field(min_length=2, max_length=30)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    username: Optional[str] = None
    avatar: Optional[str] = None
    status_text: Optional[str] = None
    invisible_mode: Optional[bool] = None
    chat_theme: Optional[str] = None
    chat_wallpaper: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    avatar: str
    status: Literal["online", "offline", "away", "busy"] = "offline"
    status_text: Optional[str] = None
    last_seen: datetime
    created_at: datetime
    invisible_mode: bool = False
    chat_theme: str = "default"
    chat_wallpaper: Optional[str] = None


class UserInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    username: str
    password_hash: str
    avatar: str = ""
    status: Literal["online", "offline", "away", "busy"] = "offline"
    status_text: Optional[str] = None
    last_seen: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    invisible_mode: bool = False
    chat_theme: str = "default"
    chat_wallpaper: Optional[str] = None


# Friend Request Models
class FriendRequestCreate(BaseModel):
    receiver_id: str


class FriendRequestInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: str
    receiver_id: str
    status: Literal["pending", "accepted", "rejected"] = "pending"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FriendRequestResponse(BaseModel):
    id: str
    sender_id: str
    sender_username: str
    sender_avatar: str
    receiver_id: str
    status: str
    created_at: datetime


# Contact Models
class ContactCreate(BaseModel):
    contact_user_id: str


class ContactInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    contact_user_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContactResponse(BaseModel):
    id: str
    username: str
    avatar: str
    status: Literal["online", "offline", "away", "busy"]
    status_text: Optional[str] = None
    last_seen: Optional[datetime] = None
    last_seen_text: Optional[str] = None
    last_message: Optional[str] = None
    last_message_time: Optional[str] = None
    unread_count: int = 0
    invisible_mode: bool = False


# Message Models
class MessageCreate(BaseModel):
    receiver_id: str
    text: Optional[str] = None
    message_type: Literal["text", "image", "video", "voice"] = "text"
    media_url: Optional[str] = None


class MessageInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: str
    receiver_id: str
    text: Optional[str] = None
    message_type: Literal["text", "image", "video", "voice"] = "text"
    media_url: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    read: bool = False


class MessageResponse(BaseModel):
    id: str
    sender_id: str
    receiver_id: str
    text: Optional[str] = None
    message_type: str
    media_url: Optional[str] = None
    timestamp: str
    type: Literal["sent", "received"]


# Auth Response
class AuthResponse(BaseModel):
    user: UserResponse
    token: str


# Call Models
class CallCreate(BaseModel):
    receiver_id: str
    call_type: Literal["voice", "video"]


class CallInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    caller_id: str
    receiver_id: str
    call_type: Literal["voice", "video"]
    status: Literal["ringing", "ongoing", "ended", "missed", "rejected"] = "ringing"
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None


# Status Models
class StatusInDB(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    media_url: str
    media_type: Literal["image", "video"] = "image"
    caption: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime
    views: List[str] = []  # List of user IDs who viewed


class StatusViewResponse(BaseModel):
    user_id: str
    username: str
    avatar: str
    viewed_at: datetime


# Token Models
class TokenData(BaseModel):
    user_id: Optional[str] = None
