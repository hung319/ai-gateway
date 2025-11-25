import secrets
import time
from typing import Optional
from fastapi import Security, HTTPException, Depends, Request, Response
from fastapi.security import APIKeyHeader
from sqlmodel import Session
from app.config import MASTER_KEY, MASTER_TRACKER_ID
from app.database import get_session
from app.models import GatewayKey, AdminSession

# Cấu hình Session: 7 ngày
SESSION_DURATION = 7 * 24 * 60 * 60 

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def create_session(session_db: Session) -> str:
    """Tạo session mới và lưu vào DB"""
    token = secrets.token_hex(32)
    new_session = AdminSession(
        session_id=token,
        expires_at=time.time() + SESSION_DURATION
    )
    session_db.add(new_session)
    session_db.commit()
    return token

async def get_current_admin(request: Request, session_db: Session = Depends(get_session)):
    """
    Logic xác thực Admin cho Panel:
    1. Check Cookie (HttpOnly) -> Bảo mật nhất.
    2. Check Header (Authorization) -> Dành cho script/curl.
    """
    # 1. Check Cookie
    session_token = request.cookies.get("gateway_session")
    if session_token:
        session_record = session_db.get(AdminSession, session_token)
        if session_record and session_record.expires_at > time.time():
            return "admin_via_cookie"
    
    # 2. Check Header (Fallback)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        if secrets.compare_digest(token, MASTER_KEY):
            return "admin_via_header"

    raise HTTPException(status_code=401, detail="Unauthorized")

async def verify_usage(request: Request, session_db: Session = Depends(get_session)):
    """Xác thực quyền gọi API Chat (Hỗ trợ cả Cookie Admin và Client Key)"""
    
    # 1. Nếu là Admin đang login (có cookie), cho phép dùng và tính vào Master Tracker
    session_token = request.cookies.get("gateway_session")
    if session_token:
        session_record = session_db.get(AdminSession, session_token)
        if session_record and session_record.expires_at > time.time():
            key_record = session_db.get(GatewayKey, MASTER_TRACKER_ID)
            key_record.usage_count += 1
            session_db.add(key_record)
            session_db.commit()
            return key_record

    # 2. Nếu không, check Bearer Token (Client Key hoặc Master Key)
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
