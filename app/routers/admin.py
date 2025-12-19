import secrets
import json
from datetime import datetime
from fastapi import APIRouter, Depends, Response, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, desc, not_
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_session, redis_client
from app.models import Provider, GatewayKey, ModelGroup, GroupMember, RequestLog
from app.security import get_current_admin, create_session
from app.engine import ai_engine
from app.config import MASTER_KEY
from app.cache import PROCESSING_SET
from app.utils import refresh_model_cache

router = APIRouter(prefix="/api", tags=["Admin"])

# --- AUTH ---
class LoginRequest(BaseModel): 
    master_key: str

@router.post("/auth/login")
async def login(d: LoginRequest, resp: Response, s: AsyncSession = Depends(get_session)):
    if secrets.compare_digest(d.master_key, MASTER_KEY):
        t = await create_session(s)
        resp.set_cookie("gateway_session", t, httponly=True, secure=False, samesite="lax", max_age=604800)
        return {"status": "ok"}
    raise HTTPException(401, "Invalid Master Key")

@router.post("/auth/logout")
async def logout(resp: Response): 
    resp.delete_cookie("gateway_session")
    return {"status": "ok"}

# --- STATS / DASHBOARD (UPDATED) ---
@router.get("/admin/stats", dependencies=[Depends(get_current_admin)])
async def get_dashboard_stats(s: AsyncSession = Depends(get_session)):
    total_providers = (await s.execute(select(func.count(Provider.name)))).scalar_one()
    total_groups = (await s.execute(select(func.count(ModelGroup.id)))).scalar_one()
    total_request = (await s.execute(select(func.count(RequestLog.id)))).scalar_one()
    
    total_models_in_cache = 0
    request_now = 0
    if redis_client:
        request_now = await redis_client.scard(PROCESSING_SET)
        cached_models = await redis_client.get("gw:models")
        if cached_models:
            try:
                data = json.loads(cached_models)
                total_models_in_cache = len(data.get("data", []))
            except: pass
    
    if total_models_in_cache == 0 and total_providers > 0:
        _, total_models_in_cache = await refresh_model_cache(s)

    # --- CHART LOGIC: Group by REAL MODEL ---
    # coalesce(real_model, model): Nếu real_model null (log cũ) thì lấy model gốc
    model_col = func.coalesce(RequestLog.real_model, RequestLog.model).label("model_name")
    
    top_models_query = (
        select(model_col, func.count(RequestLog.id).label("count"))
        .group_by(model_col)
        .order_by(desc("count"))
        .limit(10)
    )
    
    top_models_res = (await s.execute(top_models_query)).all()
    chart_data = {
        "labels": [row[0] for row in top_models_res],
        "data": [row[1] for row in top_models_res]
    }

    # Live Requests
    live_requests_query = select(RequestLog.status, RequestLog.ts).order_by(desc(RequestLog.ts)).limit(300)
    live_res = (await s.execute(live_requests_query)).all()
    live_data = []
    for row in live_res:
        status, ts = row
        ts_str = ts.isoformat() if ts else None
        live_data.append({"status": status, "ts": ts_str})
    
    return {
        "overview": {
            "total_provider": total_providers,
            "total_models": total_models_in_cache,
            "total_groups": total_groups,
            "total_request": total_request,
            "request_now": request_now,
        },
        "chart_top_models": chart_data,
        "live_requests": live_data 
    }

# --- CRUD PROVIDERS ---
class ProviderUpdate(BaseModel):
    name: str; provider_type: str; base_url: Optional[str] = None; api_key: Optional[str] = None 

@router.post("/admin/providers", dependencies=[Depends(get_current_admin)])
async def create_provider(p: Provider, s: AsyncSession = Depends(get_session)):
    await s.merge(p); await s.commit(); await ai_engine.reload(s); return {"status": "ok"}

@router.put("/admin/providers/{name}", dependencies=[Depends(get_current_admin)])
async def update_provider(name: str, p: ProviderUpdate, s: AsyncSession = Depends(get_session)):
    existing = await s.get(Provider, name)
    if not existing: raise HTTPException(404, "Provider not found")
    existing.provider_type = p.provider_type; existing.base_url = p.base_url
    if p.api_key is not None: existing.api_key = p.api_key
    s.add(existing); await s.commit(); await ai_engine.reload(s); return {"status": "ok"}

@router.get("/admin/providers", dependencies=[Depends(get_current_admin)])
async def list_providers(s: AsyncSession = Depends(get_session)): return (await s.execute(select(Provider))).scalars().all()

@router.delete("/admin/providers/{name}", dependencies=[Depends(get_current_admin)])
async def delete_provider(name: str, s: AsyncSession = Depends(get_session)):
    p = await s.get(Provider, name)
    if p: await s.delete(p); await s.commit(); await ai_engine.reload(s)
    return {"status": "ok"}

# --- CRUD KEYS ---
class KeyRequest(BaseModel): 
    name: str; custom_key: Optional[str]=None; rate_limit: Optional[int]=None; usage_limit: Optional[int]=None

@router.post("/admin/keys", dependencies=[Depends(get_current_admin)])
async def create_key(d: KeyRequest, s: AsyncSession = Depends(get_session)):
    k_str = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(8)}"
    if await s.get(GatewayKey, k_str): raise HTTPException(400, "Key exists")
    s.add(GatewayKey(key=k_str, name=d.name, rate_limit=d.rate_limit, usage_limit=d.usage_limit))
    await s.commit(); return {"key": k_str}

@router.get("/admin/keys", dependencies=[Depends(get_current_admin)])
async def list_keys(s: AsyncSession = Depends(get_session)): return (await s.execute(select(GatewayKey))).scalars().all()

@router.put("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def update_key(key: str, d: KeyRequest, s: AsyncSession = Depends(get_session)):
    k = await s.get(GatewayKey, key); 
    if not k: raise HTTPException(404, "Key not found")
    k.name = d.name; k.rate_limit = d.rate_limit; k.usage_limit = d.usage_limit
    s.add(k); await s.commit(); return {"status": "ok", "key": k}

@router.delete("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def delete_key(key: str, s: AsyncSession = Depends(get_session)):
    k = await s.get(GatewayKey, key)
    if k: await s.delete(k); await s.commit()
    return {"status": "ok"}

# --- CRUD GROUPS & MEMBERS ---
class GroupReq(BaseModel): id: str; description: Optional[str] = None; balance_strategy: str = "random" 
class MemberReq(BaseModel): group_id: str; provider_name: str; target_model: str; weight: int = 1

@router.post("/admin/groups", dependencies=[Depends(get_current_admin)])
async def create_group(d: GroupReq, s: AsyncSession = Depends(get_session)):
    if await s.get(ModelGroup, d.id): raise HTTPException(400, "Group exists")
    s.add(ModelGroup(id=d.id, description=d.description, balance_strategy=d.balance_strategy))
    await s.commit(); return {"status": "ok"}

@router.put("/admin/groups/{group_id}", dependencies=[Depends(get_current_admin)])
async def update_group(group_id: str, d: GroupReq, s: AsyncSession = Depends(get_session)):
    g = await s.get(ModelGroup, group_id)
    if not g: raise HTTPException(404, "Group not found")
    if d.description is not None: g.description = d.description
    if d.balance_strategy: g.balance_strategy = d.balance_strategy
    s.add(g); await s.commit(); return {"status": "ok"}

@router.get("/admin/groups", dependencies=[Depends(get_current_admin)])
async def list_groups(s: AsyncSession = Depends(get_session)): return (await s.execute(select(ModelGroup))).scalars().all()

@router.delete("/admin/groups/{group_id}", dependencies=[Depends(get_current_admin)])
async def delete_group(group_id: str, s: AsyncSession = Depends(get_session)):
    g = await s.get(ModelGroup, group_id)
    if g:
        members = (await s.execute(select(GroupMember).where(GroupMember.group_id == group_id))).scalars().all()
        for m in members: await s.delete(m)
        await s.delete(g); await s.commit()
    return {"status": "ok"}

@router.post("/admin/members", dependencies=[Depends(get_current_admin)])
async def add_member(d: MemberReq, s: AsyncSession = Depends(get_session)):
    if not await s.get(ModelGroup, d.group_id): raise HTTPException(404, "Group not found")
    if not await s.get(Provider, d.provider_name): raise HTTPException(404, "Provider not found")
    s.add(GroupMember(group_id=d.group_id, provider_name=d.provider_name, target_model=d.target_model, weight=d.weight))
    await s.commit(); return {"status": "ok"}

@router.get("/admin/members/{group_id}", dependencies=[Depends(get_current_admin)])
async def list_members(group_id: str, s: AsyncSession = Depends(get_session)): return (await s.execute(select(GroupMember).where(GroupMember.group_id == group_id))).scalars().all()

@router.delete("/admin/members/{member_id}", dependencies=[Depends(get_current_admin)])
async def delete_member(member_id: int, s: AsyncSession = Depends(get_session)):
    m = await s.get(GroupMember, member_id); 
    if m: await s.delete(m); await s.commit()
    return {"status": "ok"}