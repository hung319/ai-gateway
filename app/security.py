import secrets
import time
from fastapi import Security, HTTPException, Depends, Request
from fastapi.security import APIKeyHeader
from sqlmodel import Session
from app.config import MASTER_KEY, MASTER_TRACKER_ID, SESSION_DURATION
from app.database import get_session
from app.models import GatewayKey, AdminSession

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def create_session(session_db: Session) -> str:
    token = secrets.token_hex(32)
    new_session = AdminSession(session_id=token, expires_at=time.time() + SESSION_DURATION)
    session_db.add(new_session); session_db.commit()
    return token

async def get_current_admin(request: Request, session_db: Session = Depends(get_session)):
    # 1. Cookie
    token = request.cookies.get("gateway_session")
    if token:
        s = session_db.get(AdminSession, token)
        if s and s.expires_at > time.time(): return "cookie"
    # 2. Header
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer ") and secrets.compare_digest(auth.split(" ")[1], MASTER_KEY): return "header"
    raise HTTPException(401, "Unauthorized")

async def verify_usage(request: Request, session_db: Session = Depends(get_session)):
    # 1. Cookie (Admin test)
    token = request.cookies.get("gateway_session")
    if token:
        s = session_db.get(AdminSession, token)
        if s and s.expires_at > time.time():
            k = session_db.get(GatewayKey, MASTER_TRACKER_ID)
            k.usage_count += 1; session_db.add(k); session_db.commit()
            return k
    # 2. API Key
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "): raise HTTPException(401, "Missing Key")
    key = auth.split(" ")[1]
    
    if secrets.compare_digest(key, MASTER_KEY): k = session_db.get(GatewayKey, MASTER_TRACKER_ID)
    else: k = session_db.get(GatewayKey, key)
    
    if not k or not k.is_active: raise HTTPException(401, "Invalid Key")
    k.usage_count += 1; session_db.add(k); session_db.commit()
    return k
