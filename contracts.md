# HL Chat - Backend Contracts

## API Endpoints

### Authentication
| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| POST | /api/auth/signup | Register new user | `{email, password, username}` | `{user, token}` |
| POST | /api/auth/login | Login user | `{email, password}` | `{user, token}` |
| GET | /api/auth/me | Get current user | - | `{user}` |

### Users & Contacts
| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | /api/users/search?q= | Search users by username | - | `[users]` |
| GET | /api/contacts | Get user's contacts | - | `[contacts]` |
| POST | /api/contacts | Add contact | `{user_id}` | `{contact}` |

### Messages
| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | /api/messages/:contact_id | Get messages with contact | - | `[messages]` |
| POST | /api/messages | Send message | `{receiver_id, text}` | `{message}` |

### WebSocket (Real-time)
| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| connect | Client→Server | `{token}` | Authenticate connection |
| message | Client→Server | `{receiver_id, text}` | Send message |
| message | Server→Client | `{message}` | Receive message |
| online_status | Server→Client | `{user_id, status}` | User online/offline |
| typing | Client↔Server | `{contact_id, typing}` | Typing indicator |

## Database Models

### User
```python
{
    "id": str,
    "email": str (unique),
    "username": str (unique),
    "password_hash": str,
    "avatar": str,
    "status": "online" | "offline" | "away",
    "last_seen": datetime,
    "created_at": datetime
}
```

### Message
```python
{
    "id": str,
    "sender_id": str,
    "receiver_id": str,
    "text": str,
    "timestamp": datetime,
    "read": bool
}
```

### Contact
```python
{
    "id": str,
    "user_id": str,
    "contact_user_id": str,
    "created_at": datetime
}
```

## Mock Data to Replace
- `mockUsers` → MongoDB users collection
- `mockContacts` → MongoDB contacts collection  
- `mockMessages` → MongoDB messages collection
- `getMessages()` → GET /api/messages/:contact_id
- `addMessage()` → POST /api/messages + WebSocket

## Frontend Integration
1. Replace localStorage auth with JWT tokens
2. Connect to WebSocket on login
3. Replace mock data calls with API calls
4. Listen to WebSocket for real-time updates
