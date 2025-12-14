import secrets
import time
from fastapi import Security, HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession  # <--- Thay đổi import quan trọng
from app.config import MASTER_KEY, MASTER_TRACKER_ID, SESSION_DURATION
from app.database import get_session
from app.models import GatewayKey, AdminSession

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def create_session(session_db: AsyncSession) -> str:
    """
    Tạo session cho Admin Dashboard (Async)
    """
    token = secrets.token_hex(32)
    new_session = AdminSession(session_id=token, expires_at=time.time() + SESSION_DURATION)
    session_db.add(new_session)
    await session_db.commit()  # <--- Added await
    return token

async def get_current_admin(request: Request, session_db: AsyncSession = Depends(get_session)):
    """
    Verify Admin (Cookie hoặc Master Key)
    """
    # 1. Cookie
    token = request.cookies.get("gateway_session")
    if token:
        # DB Call -> Await
        s = await session_db.get(AdminSession, token)
        if s and s.expires_at > time.time(): 
            return "cookie"

    # 2. Header
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer ") and secrets.compare_digest(auth.split(" ")[1], MASTER_KEY): 
        return "header"
        
    raise HTTPException(401, "Unauthorized")

async def verify_usage(request: Request, session_db: AsyncSession = Depends(get_session)):
    """
    Middleware xác thực Client Key & Tracking Usage (Async)
    """
    # 1. Cookie (Admin test trực tiếp trên Panel)
    token = request.cookies.get("gateway_session")
    if token:
        s = await session_db.get(AdminSession, token)
        if s and s.expires_at > time.time():
            # Admin dùng Master Tracker ID để test
            k = await session_db.get(GatewayKey, MASTER_TRACKER_ID)
            if k:
                k.usage_count += 1
                session_db.add(k)
                await session_db.commit()
                return k

    # 2. API Key (Bearer Token)
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "): 
        raise HTTPException(401, "Missing Key")
    
    key = auth.split(" ")[1]
    
    # Check Master Key
    if secrets.compare_digest(key, MASTER_KEY): 
        k = await session_db.get(GatewayKey, MASTER_TRACKER_ID)
    else: 
        # Check Client Key
        k = await session_db.get(GatewayKey, key)
    
    if not k or not k.is_active: 
        raise HTTPException(401, "Invalid Key")
    
    # Update Usage (Async Write)
    k.usage_count += 1
    session_db.add(k)
    await session_db.commit()
    
    return k