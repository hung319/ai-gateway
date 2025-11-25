import secrets
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional

from app.database import get_session
from app.models import Provider, GatewayKey
# --- SỬA DÒNG NÀY ---
from app.security import get_current_admin 

# --- SỬA DEPENDENCY ---
router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(get_current_admin)])

# --- PROVIDERS ---
@router.post("/providers")
async def create_provider(p: Provider, s: Session = Depends(get_session)):
    s.merge(p); s.commit(); return {"status": "ok"}

@router.get("/providers")
async def list_providers(s: Session = Depends(get_session)):
    return s.exec(select(Provider)).all()

@router.delete("/providers/{name}")
async def delete_provider(name: str, s: Session = Depends(get_session)):
    p = s.get(Provider, name)
    if p: s.delete(p); s.commit()
    return {"status": "ok"}

# --- KEYS ---
class KeyRequest(BaseModel):
    name: str
    custom_key: Optional[str] = None

@router.post("/keys")
async def create_key(d: KeyRequest, s: Session = Depends(get_session)):
    key_val = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(8)}"
    if s.get(GatewayKey, key_val): return {"error": "Key exists"}
    s.add(GatewayKey(key=key_val, name=d.name))
    s.commit()
    return {"key": key_val}

@router.get("/keys")
async def list_keys(s: Session = Depends(get_session)):
    return s.exec(select(GatewayKey)).all()

@router.delete("/keys/{key}")
async def delete_key(key: str, s: Session = Depends(get_session)):
    k = s.get(GatewayKey, key)
    if k and not k.is_hidden: s.delete(k); s.commit()
    return {"status": "ok"}
