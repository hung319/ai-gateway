import secrets
from fastapi import Security, HTTPException, Depends
from fastapi.security import APIKeyHeader
from sqlmodel import Session
from app.config import MASTER_KEY, MASTER_TRACKER_ID
from app.database import get_session
from app.models import GatewayKey

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def get_token(header: str) -> str:
    if not header: raise HTTPException(401, "Missing Authorization Header")
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer": raise HTTPException(401, "Invalid Format")
    return parts[1]

async def verify_admin(header: str = Security(api_key_header)):
    token = get_token(header)
    if not secrets.compare_digest(token, MASTER_KEY):
        raise HTTPException(403, "Invalid Master Key")
    return token

async def verify_usage(header: str = Security(api_key_header), session: Session = Depends(get_session)):
    token = get_token(header)
    
    # Check Master Key
    if secrets.compare_digest(token, MASTER_KEY):
        key_record = session.get(GatewayKey, MASTER_TRACKER_ID)
    else:
        key_record = session.get(GatewayKey, token)
    
    if not key_record or not key_record.is_active:
        raise HTTPException(401, "Invalid API Key")
    
    # Update usage
    key_record.usage_count += 1
    session.add(key_record)
    session.commit()
    session.refresh(key_record)
    return key_record
