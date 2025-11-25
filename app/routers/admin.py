import secrets
from fastapi import APIRouter, Depends, Response, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import Optional
from app.database import get_session
from app.models import Provider, GatewayKey
from app.security import get_current_admin, create_session
from app.engine import ai_engine
from app.config import MASTER_KEY

router = APIRouter(prefix="/api", tags=["Admin"])

# Auth Routes
class LoginRequest(BaseModel): master_key: str
@router.post("/auth/login")
async def login(d: LoginRequest, resp: Response, s: Session = Depends(get_session)):
    if secrets.compare_digest(d.master_key, MASTER_KEY):
        t = create_session(s)
        resp.set_cookie("gateway_session", t, httponly=True, secure=False, samesite="lax", max_age=604800)
        return {"status": "ok"}
    raise HTTPException(401, "Invalid")

@router.post("/auth/logout")
async def logout(resp: Response): resp.delete_cookie("gateway_session"); return {"status": "ok"}

# Provider CRUD (Protected)
@router.post("/admin/providers", dependencies=[Depends(get_current_admin)])
async def cp(p: Provider, s: Session = Depends(get_session)):
    s.merge(p); s.commit(); await ai_engine.reload(s); return {"status": "ok"}

@router.get("/admin/providers", dependencies=[Depends(get_current_admin)])
async def lp(s: Session = Depends(get_session)): return s.exec(select(Provider)).all()

@router.delete("/admin/providers/{name}", dependencies=[Depends(get_current_admin)])
async def dp(name: str, s: Session = Depends(get_session)):
    p = s.get(Provider, name); 
    if p: s.delete(p); s.commit(); await ai_engine.reload(s)
    return {"status": "ok"}

# Key CRUD (Protected)
class KReq(BaseModel): name: str; custom_key: Optional[str]=None
@router.post("/admin/keys", dependencies=[Depends(get_current_admin)])
async def ck(d: KReq, s: Session = Depends(get_session)):
    k = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(8)}"
    if s.get(GatewayKey, k): raise HTTPException(400, "Exists")
    s.add(GatewayKey(key=k, name=d.name)); s.commit(); return {"key": k}

@router.get("/admin/keys", dependencies=[Depends(get_current_admin)])
async def lk(s: Session = Depends(get_session)): return s.exec(select(GatewayKey)).all()

@router.delete("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def dk(key: str, s: Session = Depends(get_session)):
    k = s.get(GatewayKey, key)
    if k and not k.is_hidden: s.delete(k); s.commit()
    return {"status": "ok"}
