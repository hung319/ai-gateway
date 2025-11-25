import secrets
import time
from fastapi import Security, HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from sqlmodel import Session
from app.config import MASTER_KEY, MASTER_TRACKER_ID
from app.database import get_session
from app.models import GatewayKey, AdminSession

SESSION_DURATION = 7 * 24 * 60 * 60 
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def create_session(session_db: Session) -> str:
    """Tạo session mới"""
    token = secrets.token_hex(32)
    new_session = AdminSession(
        session_id=token,
        expires_at=time.time() + SESSION_DURATION
    )
    session_db.add(new_session)
    session_db.commit()
    return token

# --- HÀM QUAN TRỌNG: Dùng để bảo vệ router Admin ---
async def get_current_admin(request: Request, session_db: Session = Depends(get_session)):
    """
    Thay thế cho verify_admin cũ.
    Kiểm tra Cookie trước, nếu không có thì kiểm tra Header.
    """
    # 1. Check Cookie
    session_token = request.cookies.get("gateway_session")
    if session_token:
        session_record = session_db.get(AdminSession, session_token)
        if session_record and session_record.expires_at > time.time():
            return "admin_via_cookie"
    
    # 2. Check Header (Fallback cho Curl/Script)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        if secrets.compare_digest(token, MASTER_KEY):
            return "admin_via_header"

    raise HTTPException(status_code=401, detail="Unauthorized")

# --- HÀM QUAN TRỌNG: Dùng để bảo vệ router Gateway ---
async def verify_usage(request: Request, session_db: Session = Depends(get_session)):
    """Xác thực quyền gọi API Chat (Admin Cookie hoặc Client Key)"""
    
    # 1. Admin dùng Cookie (Test trên Panel)
    session_token = request.cookies.get("gateway_session")
    if session_token:
        session_record = session_db.get(AdminSession, session_token)
        if session_record and session_record.expires_at > time.time():
            key_record = session_db.get(GatewayKey, MASTER_TRACKER_ID)
            # Update usage
            key_record.usage_count += 1
            session_db.add(key_record)
            session_db.commit()
            return key_record

    # 2. Client dùng Bearer Token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing API Key")
    
    token = auth_header.split(" ")[1]
    
    if secrets.compare_digest(token, MASTER_KEY):
        key_record = session_db.get(GatewayKey, MASTER_TRACKER_ID)
    else:
        key_record = session_db.get(GatewayKey, token)
    
    if not key_record or not key_record.is_active:
        raise HTTPException(401, "Invalid API Key")
    
    key_record.usage_count += 1
    session_db.add(key_record)
    session_db.commit()
    return key_record
