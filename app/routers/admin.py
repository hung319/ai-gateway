import secrets
from fastapi import APIRouter, Depends, Response, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from pydantic import BaseModel
from typing import Optional

# Import DB & Models
from app.database import get_session
from app.models import Provider, GatewayKey, ModelMap
from app.security import get_current_admin, create_session
from app.engine import ai_engine
from app.config import MASTER_KEY

router = APIRouter(prefix="/api", tags=["Admin"])

# --- AUTH ROUTES ---
class LoginRequest(BaseModel): 
    master_key: str

@router.post("/auth/login")
async def login(d: LoginRequest, resp: Response, s: AsyncSession = Depends(get_session)):
    if secrets.compare_digest(d.master_key, MASTER_KEY):
        # create_session giờ là async
        t = await create_session(s)
        resp.set_cookie("gateway_session", t, httponly=True, secure=False, samesite="lax", max_age=604800)
        return {"status": "ok"}
    raise HTTPException(401, "Invalid Master Key")

@router.post("/auth/logout")
async def logout(resp: Response): 
    resp.delete_cookie("gateway_session")
    return {"status": "ok"}

# --- PROVIDER CRUD (Async) ---
@router.post("/admin/providers", dependencies=[Depends(get_current_admin)])
async def cp(p: Provider, s: AsyncSession = Depends(get_session)):
    # Merge object vào session
    await s.merge(p) 
    await s.commit()
    # Reload Engine (Async)
    await ai_engine.reload(s)
    return {"status": "ok"}

@router.get("/admin/providers", dependencies=[Depends(get_current_admin)])
async def lp(s: AsyncSession = Depends(get_session)):
    # SỬA: .exec() -> .execute() và thêm .scalars().all()
    result = await s.execute(select(Provider))
    return result.scalars().all()

@router.delete("/admin/providers/{name}", dependencies=[Depends(get_current_admin)])
async def dp(name: str, s: AsyncSession = Depends(get_session)):
    p = await s.get(Provider, name)
    if p: 
        await s.delete(p)
        await s.commit()
        await ai_engine.reload(s)
    return {"status": "ok"}

# --- KEY CRUD (Async + Limits) ---
class KReq(BaseModel): 
    name: str
    custom_key: Optional[str] = None
    # Thêm fields cho Limit
    rate_limit: Optional[int] = None
    usage_limit: Optional[int] = None

@router.post("/admin/keys", dependencies=[Depends(get_current_admin)])
async def ck(d: KReq, s: AsyncSession = Depends(get_session)):
    k_str = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(8)}"
    
    # Check exist
    existing = await s.get(GatewayKey, k_str)
    if existing: 
        raise HTTPException(400, "Key already exists")
    
    new_key = GatewayKey(
        key=k_str, 
        name=d.name,
        rate_limit=d.rate_limit,
        usage_limit=d.usage_limit
    )
    s.add(new_key)
    await s.commit()
    return {"key": k_str}

@router.get("/admin/keys", dependencies=[Depends(get_current_admin)])
async def lk(s: AsyncSession = Depends(get_session)):
    # SỬA: .exec() -> .execute() và thêm .scalars().all()
    result = await s.execute(select(GatewayKey))
    return result.scalars().all()

# NEW: Update Key (PUT) - Phục vụ nút Edit trên Panel
@router.put("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def uk(key: str, d: KReq, s: AsyncSession = Depends(get_session)):
    k = await s.get(GatewayKey, key)
    if not k:
        raise HTTPException(404, "Key not found")
    
    # Update fields
    k.name = d.name
    k.rate_limit = d.rate_limit
    k.usage_limit = d.usage_limit
    
    s.add(k)
    await s.commit()
    return {"status": "ok", "key": k}

@router.delete("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def dk(key: str, s: AsyncSession = Depends(get_session)):
    k = await s.get(GatewayKey, key)
    if k and not k.is_hidden: 
        await s.delete(k)
        await s.commit()
    return {"status": "ok"}

# --- MODEL MAP ROUTES (Async) ---
@router.get("/admin/maps", dependencies=[Depends(get_current_admin)])
async def list_maps(s: AsyncSession = Depends(get_session)):
    # SỬA: .exec() -> .execute() và thêm .scalars().all()
    result = await s.execute(select(ModelMap))
    return result.scalars().all()

class MapReq(BaseModel):
    source_model: str
    target_model: str

@router.post("/admin/maps", dependencies=[Depends(get_current_admin)])
async def create_map(d: MapReq, s: AsyncSession = Depends(get_session)):
    existing = await s.get(ModelMap, d.source_model)
    if existing:
        raise HTTPException(400, "Mapping exists")
        
    s.add(ModelMap(source_model=d.source_model, target_model=d.target_model))
    await s.commit()
    return {"status": "ok"}

@router.delete("/admin/maps/{source}", dependencies=[Depends(get_current_admin)])
async def delete_map(source: str, s: AsyncSession = Depends(get_session)):
    m = await s.get(ModelMap, source)
    if m:
        await s.delete(m)
        await s.commit()
    return {"status": "ok"}