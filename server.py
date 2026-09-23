from fastapi import FastAPI, APIRouter, HTTPException, Depends, Query, UploadFile, File
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
import os
import logging
from pathlib import Path
from datetime import datetime
import socketio
import base64
import uuid

from models import (
    UserCreate, UserLogin, UserResponse, UserInDB, UserUpdate,
    FriendRequestCreate, FriendRequestInDB, FriendRequestResponse,
    ContactCreate, ContactInDB, ContactResponse,
    MessageCreate, MessageInDB, MessageResponse,
    CallCreate, CallInDB,
    AuthResponse
)
from auth import (
    get_password_hash, verify_password, create_access_token,
    get_current_user_id, decode_token
)

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'gupshup')]

# Socket.IO setup with better config
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25
)

# Create FastAPI app
app = FastAPI(title="GupShup Chat API")
api_router = APIRouter(prefix="/api")

# Store active connections: {user_id: sid}
active_connections = {}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Helper function to format last seen
def format_last_seen(last_seen: datetime) -> str:
    now = datetime.utcnow()
    diff = now - last_seen
    
    if diff.total_seconds() < 60:
        return "just now"
    elif diff.total_seconds() < 3600:
        mins = int(diff.total_seconds() / 60)
        return f"{mins} min ago"
    elif diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.days == 1:
        return f"yesterday at {last_seen.strftime('%I:%M %p')}"
    else:
        return last_seen.strftime("%d/%m/%y %I:%M %p")


# ==================== AUTH ROUTES ====================

# Store OTPs temporarily (in production use Redis)
otp_store = {}

import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def generate_otp():
    return ''.join([str(random.randint(0, 9)) for _ in range(6)])

async def send_otp_email(email: str, otp: str):
    """Send OTP via email - in production use proper email service"""
    # For demo, we just store it. In production, integrate with email service
    logger.info(f"OTP for {email}: {otp}")
    return True


class OTPRequest(BaseModel):
    email: str

class OTPVerifySignup(BaseModel):
    email: str
    otp: str
    password: str
    username: str


@api_router.post("/auth/request-otp")
async def request_otp(data: OTPRequest):
    # Check if email already registered
    existing = await db.users.find_one({"email": data.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    otp = generate_otp()
    otp_store[data.email] = {
        "otp": otp,
        "expires": datetime.utcnow().timestamp() + 600  # 10 minutes
    }
    
    await send_otp_email(data.email, otp)
    
    # For demo purposes, return OTP in response (remove in production!)
    return {"message": f"OTP sent to {data.email}", "demo_otp": otp}


@api_router.post("/auth/verify-otp-signup", response_model=AuthResponse)
async def verify_otp_signup(data: OTPVerifySignup):
    # Verify OTP
    stored = otp_store.get(data.email)
    if not stored:
        raise HTTPException(status_code=400, detail="OTP expired or not found")
    
    if stored["expires"] < datetime.utcnow().timestamp():
        del otp_store[data.email]
        raise HTTPException(status_code=400, detail="OTP expired")
    
    if stored["otp"] != data.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    
    # OTP verified, create user
    del otp_store[data.email]
    
    existing_username = await db.users.find_one({"username": data.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    user = UserInDB(
        email=data.email,
        username=data.username,
        password_hash=get_password_hash(data.password),
        avatar=f"https://api.dicebear.com/7.x/avataaars/svg?seed={data.username}",
        status="online"
    )
    
    await db.users.insert_one(user.dict())
    token = create_access_token({"sub": user.id})
    
    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            avatar=user.avatar,
            status=user.status,
            status_text=user.status_text,
            last_seen=user.last_seen,
            created_at=user.created_at
        ),
        token=token
    )


@api_router.post("/auth/signup", response_model=AuthResponse)
async def signup(user_data: UserCreate):
    existing_email = await db.users.find_one({"email": user_data.email})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    existing_username = await db.users.find_one({"username": user_data.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    user = UserInDB(
        email=user_data.email,
        username=user_data.username,
        password_hash=get_password_hash(user_data.password),
        avatar=f"https://api.dicebear.com/7.x/avataaars/svg?seed={user_data.username}",
        status="online"
    )
    
    await db.users.insert_one(user.dict())
    token = create_access_token({"sub": user.id})
    
    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            avatar=user.avatar,
            status=user.status,
            status_text=user.status_text,
            last_seen=user.last_seen,
            created_at=user.created_at
        ),
        token=token
    )


@api_router.post("/auth/login", response_model=AuthResponse)
async def login(user_data: UserLogin):
    user = await db.users.find_one({"email": user_data.email})
    if not user or not verify_password(user_data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"status": "online", "last_seen": datetime.utcnow()}}
    )
    
    token = create_access_token({"sub": user["id"]})
    
    return AuthResponse(
        user=UserResponse(
            id=user["id"],
            email=user["email"],
            username=user["username"],
            avatar=user["avatar"],
            status="online",
            status_text=user.get("status_text"),
            last_seen=datetime.utcnow(),
            created_at=user["created_at"]
        ),
        token=token
    )


@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(user_id: str = Depends(get_current_user_id)):
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user["username"],
        avatar=user["avatar"],
        status=user["status"],
        status_text=user.get("status_text"),
        last_seen=user["last_seen"],
        created_at=user["created_at"],
        invisible_mode=user.get("invisible_mode", False),
        chat_theme=user.get("chat_theme", "default"),
        chat_wallpaper=user.get("chat_wallpaper")
    )


@api_router.put("/auth/profile")
async def update_profile(update_data: UserUpdate, user_id: str = Depends(get_current_user_id)):
    update_dict = {k: v for k, v in update_data.dict().items() if v is not None}
    if update_dict:
        await db.users.update_one({"id": user_id}, {"$set": update_dict})
    
    user = await db.users.find_one({"id": user_id})
    return UserResponse(
        id=user["id"],
        email=user["email"],
        username=user["username"],
        avatar=user["avatar"],
        status=user["status"],
        status_text=user.get("status_text"),
        last_seen=user["last_seen"],
        created_at=user["created_at"],
        invisible_mode=user.get("invisible_mode", False),
        chat_theme=user.get("chat_theme", "default"),
        chat_wallpaper=user.get("chat_wallpaper")
    )


@api_router.post("/auth/upload-avatar")
async def upload_avatar(file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    # Read file and convert to base64
    contents = await file.read()
    base64_image = base64.b64encode(contents).decode('utf-8')
    content_type = file.content_type or 'image/jpeg'
    avatar_url = f"data:{content_type};base64,{base64_image}"
    
    await db.users.update_one({"id": user_id}, {"$set": {"avatar": avatar_url}})
    
    return {"avatar": avatar_url}


@api_router.post("/auth/logout")
async def logout(user_id: str = Depends(get_current_user_id)):
    await db.users.update_one(
        {"id": user_id},
        {"$set": {"status": "offline", "last_seen": datetime.utcnow()}}
    )
    return {"message": "Logged out successfully"}


# ==================== USER ROUTES ====================

@api_router.get("/users/search")
async def search_users(q: str = Query(min_length=1), user_id: str = Depends(get_current_user_id)):
    users = await db.users.find({
        "username": {"$regex": q, "$options": "i"},
        "id": {"$ne": user_id}
    }).to_list(20)
    
    return [
        {
            "id": u["id"],
            "username": u["username"],
            "avatar": u["avatar"],
            "status": u["status"]
        }
        for u in users
    ]


# ==================== FRIEND REQUEST ROUTES ====================

@api_router.post("/friend-requests")
async def send_friend_request(request_data: FriendRequestCreate, user_id: str = Depends(get_current_user_id)):
    # Check if user exists
    receiver = await db.users.find_one({"id": request_data.receiver_id})
    if not receiver:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if request already exists
    existing = await db.friend_requests.find_one({
        "$or": [
            {"sender_id": user_id, "receiver_id": request_data.receiver_id},
            {"sender_id": request_data.receiver_id, "receiver_id": user_id}
        ],
        "status": {"$in": ["pending", "accepted"]}
    })
    if existing:
        if existing["status"] == "accepted":
            raise HTTPException(status_code=400, detail="Already friends")
        raise HTTPException(status_code=400, detail="Request already exists")
    
    # Create request
    friend_request = FriendRequestInDB(
        sender_id=user_id,
        receiver_id=request_data.receiver_id
    )
    await db.friend_requests.insert_one(friend_request.dict())
    
    # Get sender info
    sender = await db.users.find_one({"id": user_id})
    
    # Notify receiver via WebSocket
    if request_data.receiver_id in active_connections:
        await sio.emit('friend_request', {
            "id": friend_request.id,
            "sender_id": user_id,
            "sender_username": sender["username"],
            "sender_avatar": sender["avatar"],
            "status": "pending"
        }, to=active_connections[request_data.receiver_id])
    
    return {"message": "Friend request sent", "request_id": friend_request.id}


@api_router.get("/friend-requests")
async def get_friend_requests(user_id: str = Depends(get_current_user_id)):
    requests = await db.friend_requests.find({
        "receiver_id": user_id,
        "status": "pending"
    }).to_list(100)
    
    result = []
    for req in requests:
        sender = await db.users.find_one({"id": req["sender_id"]})
        if sender:
            result.append({
                "id": req["id"],
                "sender_id": req["sender_id"],
                "sender_username": sender["username"],
                "sender_avatar": sender["avatar"],
                "status": req["status"],
                "created_at": req["created_at"]
            })
    
    return result


@api_router.put("/friend-requests/{request_id}")
async def respond_to_friend_request(
    request_id: str,
    action: str = Query(..., regex="^(accept|reject)$"),
    user_id: str = Depends(get_current_user_id)
):
    request = await db.friend_requests.find_one({"id": request_id, "receiver_id": user_id})
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    new_status = "accepted" if action == "accept" else "rejected"
    await db.friend_requests.update_one(
        {"id": request_id},
        {"$set": {"status": new_status, "updated_at": datetime.utcnow()}}
    )
    
    if action == "accept":
        # Add as contacts (both ways)
        contact1 = ContactInDB(user_id=user_id, contact_user_id=request["sender_id"])
        contact2 = ContactInDB(user_id=request["sender_id"], contact_user_id=user_id)
        await db.contacts.insert_one(contact1.dict())
        await db.contacts.insert_one(contact2.dict())
        
        # Notify sender
        if request["sender_id"] in active_connections:
            receiver = await db.users.find_one({"id": user_id})
            await sio.emit('friend_request_accepted', {
                "request_id": request_id,
                "user_id": user_id,
                "username": receiver["username"],
                "avatar": receiver["avatar"]
            }, to=active_connections[request["sender_id"]])
    
    return {"message": f"Request {new_status}"}


# ==================== CONTACT ROUTES ====================

@api_router.get("/contacts")
async def get_contacts(user_id: str = Depends(get_current_user_id)):
    contacts = await db.contacts.find({"user_id": user_id}).to_list(100)
    
    result = []
    for contact in contacts:
        contact_user = await db.users.find_one({"id": contact["contact_user_id"]})
        if not contact_user:
            continue
        
        last_msg = await db.messages.find_one(
            {
                "$or": [
                    {"sender_id": user_id, "receiver_id": contact["contact_user_id"]},
                    {"sender_id": contact["contact_user_id"], "receiver_id": user_id}
                ]
            },
            sort=[("timestamp", -1)]
        )
        
        unread_count = await db.messages.count_documents({
            "sender_id": contact["contact_user_id"],
            "receiver_id": user_id,
            "read": False
        })
        
        last_message = None
        last_message_time = None
        if last_msg:
            if last_msg["message_type"] == "text":
                last_message = last_msg["text"]
            elif last_msg["message_type"] == "image":
                last_message = "📷 Photo"
            else:
                last_message = "🎥 Video"
            
            msg_time = last_msg["timestamp"]
            now = datetime.utcnow()
            if msg_time.date() == now.date():
                last_message_time = msg_time.strftime("%I:%M %p")
            elif (now - msg_time).days == 1:
                last_message_time = "Yesterday"
            else:
                last_message_time = msg_time.strftime("%d/%m/%y")
        
        # Check if contact has invisible mode on
        is_invisible = contact_user.get("invisible_mode", False)
        
        result.append({
            "id": contact["contact_user_id"],
            "username": contact_user["username"],
            "avatar": contact_user["avatar"],
            "status": "offline" if is_invisible else contact_user["status"],
            "status_text": contact_user.get("status_text"),
            "last_seen": contact_user["last_seen"],
            "last_seen_text": None if is_invisible else (format_last_seen(contact_user["last_seen"]) if contact_user["status"] == "offline" else None),
            "last_message": last_message,
            "last_message_time": last_message_time,
            "unread_count": unread_count,
            "invisible_mode": is_invisible
        })
    
    return result


# ==================== MESSAGE ROUTES ====================

@api_router.get("/messages/{contact_id}")
async def get_messages(contact_id: str, user_id: str = Depends(get_current_user_id)):
    messages = await db.messages.find({
        "$or": [
            {"sender_id": user_id, "receiver_id": contact_id},
            {"sender_id": contact_id, "receiver_id": user_id}
        ]
    }).sort("timestamp", 1).to_list(500)
    
    # Mark messages as read
    await db.messages.update_many(
        {"sender_id": contact_id, "receiver_id": user_id, "read": False},
        {"$set": {"read": True}}
    )
    
    return [
        {
            "id": msg["id"],
            "sender_id": msg["sender_id"],
            "receiver_id": msg["receiver_id"],
            "text": msg.get("text"),
            "message_type": msg.get("message_type", "text"),
            "media_url": msg.get("media_url"),
            "timestamp": msg["timestamp"].strftime("%I:%M %p"),
            "type": "sent" if msg["sender_id"] == user_id else "received",
            "read": msg.get("read", False),
            "reactions": msg.get("reactions", [])
        }
        for msg in messages
    ]


class ReactionCreate(BaseModel):
    reaction: str


@api_router.post("/messages/{message_id}/reaction")
async def add_reaction(message_id: str, data: ReactionCreate, user_id: str = Depends(get_current_user_id)):
    message = await db.messages.find_one({"id": message_id})
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    
    # Add reaction
    await db.messages.update_one(
        {"id": message_id},
        {"$push": {"reactions": {"reaction": data.reaction, "user_id": user_id}}}
    )
    
    # Notify the other user
    other_user = message["receiver_id"] if message["sender_id"] == user_id else message["sender_id"]
    if other_user in active_connections:
        await sio.emit('message_reaction', {
            "message_id": message_id,
            "reaction": data.reaction,
            "user_id": user_id
        }, to=active_connections[other_user])
    
    return {"success": True}


@api_router.post("/messages")
async def send_message(msg_data: MessageCreate, user_id: str = Depends(get_current_user_id)):
    # Verify they are contacts
    contact = await db.contacts.find_one({
        "user_id": user_id,
        "contact_user_id": msg_data.receiver_id
    })
    if not contact:
        raise HTTPException(status_code=403, detail="You can only message your contacts")
    
    message = MessageInDB(
        sender_id=user_id,
        receiver_id=msg_data.receiver_id,
        text=msg_data.text,
        message_type=msg_data.message_type,
        media_url=msg_data.media_url
    )
    
    await db.messages.insert_one(message.dict())
    
    msg_response = {
        "id": message.id,
        "sender_id": message.sender_id,
        "receiver_id": message.receiver_id,
        "text": message.text,
        "message_type": message.message_type,
        "media_url": message.media_url,
        "timestamp": message.timestamp.strftime("%I:%M %p"),
        "type": "sent"
    }
    
    # Send via WebSocket if receiver is online
    if msg_data.receiver_id in active_connections:
        sender = await db.users.find_one({"id": user_id})
        receiver_sid = active_connections[msg_data.receiver_id]
        await sio.emit('new_message', {
            **msg_response,
            "type": "received",
            "sender_username": sender["username"],
            "sender_avatar": sender["avatar"]
        }, to=receiver_sid)
    
    return msg_response


@api_router.post("/messages/media")
async def send_media_message(
    receiver_id: str,
    message_type: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id)
):
    # Verify they are contacts
    contact = await db.contacts.find_one({
        "user_id": user_id,
        "contact_user_id": receiver_id
    })
    if not contact:
        raise HTTPException(status_code=403, detail="You can only message your contacts")
    
    # Convert file to base64
    contents = await file.read()
    base64_data = base64.b64encode(contents).decode('utf-8')
    content_type = file.content_type or 'image/jpeg'
    media_url = f"data:{content_type};base64,{base64_data}"
    
    message = MessageInDB(
        sender_id=user_id,
        receiver_id=receiver_id,
        message_type=message_type,
        media_url=media_url
    )
    
    await db.messages.insert_one(message.dict())
    
    msg_response = {
        "id": message.id,
        "sender_id": message.sender_id,
        "receiver_id": message.receiver_id,
        "text": None,
        "message_type": message.message_type,
        "media_url": message.media_url,
        "timestamp": message.timestamp.strftime("%I:%M %p"),
        "type": "sent"
    }
    
    # Send via WebSocket
    if receiver_id in active_connections:
        sender = await db.users.find_one({"id": user_id})
        await sio.emit('new_message', {
            **msg_response,
            "type": "received",
            "sender_username": sender["username"],
            "sender_avatar": sender["avatar"]
        }, to=active_connections[receiver_id])
    
    return msg_response


# ==================== CALL ROUTES ====================

@api_router.post("/calls")
async def initiate_call(call_data: CallCreate, user_id: str = Depends(get_current_user_id)):
    # Verify they are contacts
    contact = await db.contacts.find_one({
        "user_id": user_id,
        "contact_user_id": call_data.receiver_id
    })
    if not contact:
        raise HTTPException(status_code=403, detail="You can only call your contacts")
    
    call = CallInDB(
        caller_id=user_id,
        receiver_id=call_data.receiver_id,
        call_type=call_data.call_type
    )
    
    await db.calls.insert_one(call.dict())
    
    caller = await db.users.find_one({"id": user_id})
    receiver = await db.users.find_one({"id": call_data.receiver_id})
    
    # Notify receiver via WebSocket
    if call_data.receiver_id in active_connections:
        await sio.emit('incoming_call', {
            "call_id": call.id,
            "caller_id": user_id,
            "caller_username": caller["username"],
            "caller_avatar": caller["avatar"],
            "call_type": call_data.call_type
        }, to=active_connections[call_data.receiver_id])
    
    return {"call_id": call.id, "status": "ringing"}


@api_router.get("/calls/history")
async def get_call_history(user_id: str = Depends(get_current_user_id)):
    calls = await db.calls.find({
        "$or": [
            {"caller_id": user_id},
            {"receiver_id": user_id}
        ]
    }).sort("started_at", -1).to_list(50)
    
    result = []
    for call in calls:
        is_caller = call["caller_id"] == user_id
        other_id = call["receiver_id"] if is_caller else call["caller_id"]
        other_user = await db.users.find_one({"id": other_id})
        
        if not other_user:
            continue
        
        call_type_str = "outgoing" if is_caller else "incoming"
        if call.get("status") == "missed" or (call.get("status") == "rejected" and not is_caller):
            call_type_str = "missed"
        
        result.append({
            "id": call["id"],
            "contact": {
                "id": other_id,
                "username": other_user["username"],
                "avatar": other_user["avatar"]
            },
            "type": call_type_str,
            "call_type": call["call_type"],
            "time": call["started_at"].strftime("%I:%M %p"),
            "date": call["started_at"].strftime("%d/%m/%y"),
            "status": call.get("status", "ended")
        })
    
    return result


@api_router.put("/calls/{call_id}")
async def respond_to_call(
    call_id: str,
    action: str = Query(..., regex="^(accept|reject|end)$"),
    user_id: str = Depends(get_current_user_id)
):
    call = await db.calls.find_one({"id": call_id})
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    if action == "accept":
        new_status = "ongoing"
    elif action == "reject":
        new_status = "rejected"
    else:
        new_status = "ended"
    
    update_data = {"status": new_status}
    if action in ["reject", "end"]:
        update_data["ended_at"] = datetime.utcnow()
    
    await db.calls.update_one({"id": call_id}, {"$set": update_data})
    
    # Notify the other party
    other_party = call["caller_id"] if user_id == call["receiver_id"] else call["receiver_id"]
    if other_party in active_connections:
        await sio.emit('call_status', {
            "call_id": call_id,
            "status": new_status
        }, to=active_connections[other_party])
    
    return {"status": new_status}


# ==================== STATUS ROUTES ====================

@api_router.post("/statuses")
async def add_status(file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    contents = await file.read()
    base64_data = base64.b64encode(contents).decode('utf-8')
    content_type = file.content_type or 'image/jpeg'
    media_url = f"data:{content_type};base64,{base64_data}"
    
    media_type = "video" if content_type.startswith("video/") else "image"
    
    # Fix the expires_at calculation - add 24 hours properly
    from datetime import timedelta
    expires_at = datetime.utcnow() + timedelta(hours=24)
    
    status = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "media_url": media_url,
        "media_type": media_type,
        "created_at": datetime.utcnow(),
        "expires_at": expires_at
    }
    
    # Remove old status if exists
    await db.statuses.delete_many({"user_id": user_id})
    await db.statuses.insert_one(status)
    
    # Get user info and notify contacts
    user = await db.users.find_one({"id": user_id})
    contacts = await db.contacts.find({"user_id": user_id}).to_list(100)
    
    for contact in contacts:
        if contact["contact_user_id"] in active_connections:
            await sio.emit('new_status', {
                "id": status["id"],
                "user_id": user_id,
                "username": user["username"],
                "user_avatar": user["avatar"],
                "media_url": media_url,
                "media_type": media_type,
                "time": "Just now"
            }, to=active_connections[contact["contact_user_id"]])
    
    return {"id": status["id"], "message": "Status added"}


@api_router.get("/statuses")
async def get_statuses(user_id: str = Depends(get_current_user_id)):
    # Get my status
    my_status = await db.statuses.find_one({"user_id": user_id})
    
    # Get contacts' statuses
    contacts = await db.contacts.find({"user_id": user_id}).to_list(100)
    contact_ids = [c["contact_user_id"] for c in contacts]
    
    statuses = await db.statuses.find({
        "user_id": {"$in": contact_ids},
        "expires_at": {"$gt": datetime.utcnow()}
    }).sort("created_at", -1).to_list(50)
    
    result = []
    for status in statuses:
        status_user = await db.users.find_one({"id": status["user_id"]})
        if status_user:
            time_diff = datetime.utcnow() - status["created_at"]
            if time_diff.total_seconds() < 3600:
                time_str = f"{int(time_diff.total_seconds() / 60)} min ago"
            else:
                time_str = f"{int(time_diff.total_seconds() / 3600)} hours ago"
            
            result.append({
                "id": status["id"],
                "user_id": status["user_id"],
                "username": status_user["username"],
                "user_avatar": status_user["avatar"],
                "media_url": status["media_url"],
                "media_type": status["media_type"],
                "time": time_str
            })
    
    my_status_data = None
    if my_status:
        # Get views for my status
        views = my_status.get("views", [])
        view_details = []
        for view_id in views:
            view_user = await db.users.find_one({"id": view_id})
            if view_user:
                view_details.append({
                    "user_id": view_id,
                    "username": view_user["username"],
                    "avatar": view_user["avatar"]
                })
        
        my_status_data = {
            "id": my_status["id"],
            "media_url": my_status["media_url"],
            "media_type": my_status["media_type"],
            "views": view_details,
            "view_count": len(views)
        }
    
    return {"my_status": my_status_data, "others": result}


@api_router.post("/statuses/{status_id}/view")
async def view_status(status_id: str, user_id: str = Depends(get_current_user_id)):
    """Record that a user viewed a status"""
    status = await db.statuses.find_one({"id": status_id})
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    
    # Don't record self views
    if status["user_id"] == user_id:
        return {"message": "View recorded"}
    
    # Add user to views if not already there
    await db.statuses.update_one(
        {"id": status_id},
        {"$addToSet": {"views": user_id}}
    )
    
    # Notify status owner
    if status["user_id"] in active_connections:
        viewer = await db.users.find_one({"id": user_id})
        await sio.emit('status_viewed', {
            "status_id": status_id,
            "viewer_id": user_id,
            "viewer_username": viewer["username"],
            "viewer_avatar": viewer["avatar"]
        }, to=active_connections[status["user_id"]])
    
    return {"message": "View recorded"}


@api_router.get("/statuses/{status_id}/views")
async def get_status_views(status_id: str, user_id: str = Depends(get_current_user_id)):
    """Get list of users who viewed a status"""
    status = await db.statuses.find_one({"id": status_id})
    if not status:
        raise HTTPException(status_code=404, detail="Status not found")
    
    # Only owner can see views
    if status["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    views = status.get("views", [])
    result = []
    for view_id in views:
        view_user = await db.users.find_one({"id": view_id})
        if view_user:
            result.append({
                "user_id": view_id,
                "username": view_user["username"],
                "avatar": view_user["avatar"]
            })
    
    return {"views": result, "count": len(result)}


@api_router.post("/auth/upload-wallpaper")
async def upload_wallpaper(file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    """Upload custom chat wallpaper"""
    contents = await file.read()
    base64_image = base64.b64encode(contents).decode('utf-8')
    content_type = file.content_type or 'image/jpeg'
    wallpaper_url = f"data:{content_type};base64,{base64_image}"
    
    await db.users.update_one({"id": user_id}, {"$set": {"chat_wallpaper": wallpaper_url}})
    
    return {"wallpaper": wallpaper_url}


# ==================== SOCKET.IO EVENTS ====================

@sio.event
async def connect(sid, environ, auth):
    if auth and 'token' in auth:
        user_id = decode_token(auth['token'])
        if user_id:
            active_connections[user_id] = sid
            await sio.save_session(sid, {'user_id': user_id})
            
            await db.users.update_one(
                {"id": user_id},
                {"$set": {"status": "online", "last_seen": datetime.utcnow()}}
            )
            
            # Check if user has invisible mode
            user = await db.users.find_one({"id": user_id})
            is_invisible = user.get("invisible_mode", False) if user else False
            
            # Broadcast online status to contacts (only if not invisible)
            if not is_invisible:
                contacts = await db.contacts.find({"user_id": user_id}).to_list(100)
                for contact in contacts:
                    if contact["contact_user_id"] in active_connections:
                        await sio.emit(
                            'user_status',
                            {"user_id": user_id, "status": "online"},
                            to=active_connections[contact["contact_user_id"]]
                        )
            
            logger.info(f"User {user_id} connected")
            return True
    return False


@sio.event
async def disconnect(sid):
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        user_id = session['user_id']
        if user_id in active_connections:
            del active_connections[user_id]
        
        await db.users.update_one(
            {"id": user_id},
            {"$set": {"status": "offline", "last_seen": datetime.utcnow()}}
        )
        
        # Check if user has invisible mode
        user = await db.users.find_one({"id": user_id})
        is_invisible = user.get("invisible_mode", False) if user else False
        
        # Only broadcast offline status if not invisible
        if not is_invisible:
            contacts = await db.contacts.find({"user_id": user_id}).to_list(100)
            for contact in contacts:
                if contact["contact_user_id"] in active_connections:
                    await sio.emit(
                        'user_status',
                        {"user_id": user_id, "status": "offline"},
                        to=active_connections[contact["contact_user_id"]]
                    )
        
        logger.info(f"User {user_id} disconnected")


@sio.event
async def typing(sid, data):
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        user_id = session['user_id']
        contact_id = data.get('contact_id')
        is_typing = data.get('typing', False)
        
        if contact_id in active_connections:
            await sio.emit(
                'typing',
                {"user_id": user_id, "typing": is_typing},
                to=active_connections[contact_id]
            )


@sio.event
async def mark_read(sid, data):
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        user_id = session['user_id']
        contact_id = data.get('contact_id')
        
        await db.messages.update_many(
            {"sender_id": contact_id, "receiver_id": user_id, "read": False},
            {"$set": {"read": True}}
        )
        
        # Notify sender that messages were read
        if contact_id in active_connections:
            await sio.emit(
                'messages_read',
                {"user_id": user_id},
                to=active_connections[contact_id]
            )


# ==================== WEBRTC SIGNALING EVENTS ====================

@sio.event
async def call_user(sid, data):
    """Initiate a call to another user"""
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        caller_id = session['user_id']
        receiver_id = data.get('receiver_id')
        call_type = data.get('call_type', 'voice')  # voice or video
        signal_data = data.get('signal_data')
        
        caller = await db.users.find_one({"id": caller_id})
        
        if receiver_id in active_connections:
            await sio.emit('incoming_call', {
                'caller_id': caller_id,
                'caller_username': caller['username'],
                'caller_avatar': caller['avatar'],
                'call_type': call_type,
                'signal_data': signal_data
            }, to=active_connections[receiver_id])
            
            logger.info(f"Call from {caller_id} to {receiver_id}")


@sio.event
async def answer_call(sid, data):
    """Answer an incoming call"""
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        answerer_id = session['user_id']
        caller_id = data.get('caller_id')
        signal_data = data.get('signal_data')
        
        if caller_id in active_connections:
            await sio.emit('call_answered', {
                'answerer_id': answerer_id,
                'signal_data': signal_data
            }, to=active_connections[caller_id])
            
            logger.info(f"Call answered by {answerer_id}")


@sio.event
async def end_call(sid, data):
    """End an ongoing call"""
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        user_id = session['user_id']
        other_user_id = data.get('other_user_id')
        
        if other_user_id in active_connections:
            await sio.emit('call_ended', {
                'ended_by': user_id
            }, to=active_connections[other_user_id])
            
            logger.info(f"Call ended by {user_id}")


@sio.event
async def reject_call(sid, data):
    """Reject an incoming call"""
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        user_id = session['user_id']
        caller_id = data.get('caller_id')
        
        if caller_id in active_connections:
            await sio.emit('call_rejected', {
                'rejected_by': user_id
            }, to=active_connections[caller_id])
            
            logger.info(f"Call rejected by {user_id}")


@sio.event
async def ice_candidate(sid, data):
    """Exchange ICE candidates for WebRTC"""
    session = await sio.get_session(sid)
    if session and 'user_id' in session:
        user_id = session['user_id']
        target_id = data.get('target_id')
        candidate = data.get('candidate')
        
        if target_id in active_connections:
            await sio.emit('ice_candidate', {
                'from_id': user_id,
                'candidate': candidate
            }, to=active_connections[target_id])


# Root endpoint
@api_router.get("/")
async def root():
    return {"message": "GupShup Chat API is running!"}


# About endpoint
@api_router.get("/about")
async def about():
    return {
        "app": "GupShup Chat",
        "tagline": "Real-time chat with friends",
        "version": "1.0.0",
        "developers": [
            {"name": "Rahman Ahmed", "role": "Developer"},
            {"name": "Ghulam Murtaza", "role": "Developer"}
        ]
    }


# Health check endpoint for Kubernetes
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


# Include router
app.include_router(api_router)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Socket.IO
socket_app = socketio.ASGIApp(sio, app)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(socket_app, host="0.0.0.0", port=8001)
