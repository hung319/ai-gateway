import secrets
from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional

from app.database import get_session
from app.models import Provider, GatewayKey
from app.security import verify_admin

router = APIRouter(prefix="/api/admin", tags=["Admin"])

# --- PROVIDERS ---
@router.post("/providers", dependencies=[Depends(verify_admin)])
async def create_provider(p: Provider, s: Session = Depends(get_session)):
    s.merge(p); s.commit(); return {"status": "ok"}

@router.get("/providers", dependencies=[Depends(verify_admin)])
async def list_providers(s: Session = Depends(get_session)):
    return s.exec(select(Provider)).all()

@router.delete("/providers/{name}", dependencies=[Depends(verify_admin)])
async def delete_provider(name: str, s: Session = Depends(get_session)):
    p = s.get(Provider, name)
    if p: s.delete(p); s.commit()
    return {"status": "ok"}

# --- KEYS ---
class KeyRequest(BaseModel):
    name: str
    custom_key: Optional[str] = None

@router.post("/keys", dependencies=[Depends(verify_admin)])
async def create_key(d: KeyRequest, s: Session = Depends(get_session)):
    key_val = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(8)}"
    s.add(GatewayKey(key=key_val, name=d.name))
    s.commit()
    return {"key": key_val}

@router.get("/keys", dependencies=[Depends(verify_admin)])
async def list_keys(s: Session = Depends(get_session)):
    return s.exec(select(GatewayKey)).all()

@router.delete("/keys/{key}", dependencies=[Depends(verify_admin)])
async def delete_key(key: str, s: Session = Depends(get_session)):
    k = s.get(GatewayKey, key)
    if k and not k.is_hidden: s.delete(k); s.commit()
    return {"status": "ok"}
