import secrets
import json
from datetime import datetime  # <--- THÊM DÒNG NÀY
from fastapi import APIRouter, Depends, Response, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, desc
from pydantic import BaseModel
from typing import Optional, List

from app.database import get_session, redis_client
from app.models import Provider, GatewayKey, ModelMap, RequestLog
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
    # 1. Basic Counts
    total_providers = (await s.execute(select(func.count(Provider.name)))).scalar_one()
    total_mapping = (await s.execute(select(func.count(ModelMap.source_model)))).scalar_one()
    total_request = (await s.execute(select(func.count(RequestLog.id)))).scalar_one()
    
    # 2. Redis Stats
    total_models = 0
    request_now = 0
    if redis_client:
        request_now = await redis_client.scard(PROCESSING_SET)
        cached_models = await redis_client.get("gw:models")
        if cached_models:
            try:
                data = json.loads(cached_models)
                total_models = len(data.get("data", []))
            except: pass
    
    # Fallback nếu Redis chưa có model (lần đầu chạy)
    if total_models == 0 and total_providers > 0:
        _, total_models = await refresh_model_cache(s)

    # 3. Top 10 Models Chart
    top_models_query = (
        select(RequestLog.model, func.count(RequestLog.id).label("count"))
        .group_by(RequestLog.model)
        .order_by(desc("count"))
        .limit(10)
    )
    top_models_res = (await s.execute(top_models_query)).all()
    chart_data = {
        "labels": [row[0] for row in top_models_res],
        "data": [row[1] for row in top_models_res]
    }

    # 4. Live Requests Grid (Lấy 300 request mới nhất để fill grid)
    live_requests_query = (
        select(RequestLog.status, RequestLog.timestamp)
        .order_by(desc(RequestLog.timestamp))
        .limit(300)
    )
    live_res = (await s.execute(live_requests_query)).all()
    
    # --- [FIX LỖI TIMESTAMP FLOAT] ---
    live_data = []
    for row in live_res:
        status, ts = row
        ts_str = None
        if ts is not None:
            # Nếu DB lưu là float (UNIX timestamp), convert sang datetime rồi mới format
            if isinstance(ts, (float, int)):
                ts_str = datetime.fromtimestamp(ts).isoformat()
            # Nếu DB đã trả về object datetime (tùy driver DB)
            elif hasattr(ts, "isoformat"):
                ts_str = ts.isoformat()
        
        live_data.append({"status": status, "ts": ts_str})
    # ---------------------------------
    
    return {
        "overview": {
            "total_provider": total_providers,
            "total_models": total_models,
            "total_mapping": total_mapping,
            "total_request": total_request,
            "request_now": request_now,
        },
        "chart_top_models": chart_data,
        "live_requests": live_data 
    }

# --- CRUD PROVIDERS ---
@router.post("/admin/providers", dependencies=[Depends(get_current_admin)])
async def create_provider(p: Provider, s: AsyncSession = Depends(get_session)):
    await s.merge(p)
    await s.commit()
    await ai_engine.reload(s)
    return {"status": "ok"}

@router.get("/admin/providers", dependencies=[Depends(get_current_admin)])
async def list_providers(s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(Provider))).scalars().all()

@router.delete("/admin/providers/{name}", dependencies=[Depends(get_current_admin)])
async def delete_provider(name: str, s: AsyncSession = Depends(get_session)):
    p = await s.get(Provider, name)
    if p: 
        await s.delete(p)
        await s.commit()
        await ai_engine.reload(s)
    return {"status": "ok"}

# --- CRUD KEYS ---
class KeyRequest(BaseModel): 
    name: str
    custom_key: Optional[str]=None
    rate_limit: Optional[int]=None
    usage_limit: Optional[int]=None

@router.post("/admin/keys", dependencies=[Depends(get_current_admin)])
async def create_key(d: KeyRequest, s: AsyncSession = Depends(get_session)):
    k_str = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(8)}"
    if await s.get(GatewayKey, k_str): 
        raise HTTPException(400, "Key exists")
    
    s.add(GatewayKey(key=k_str, name=d.name, rate_limit=d.rate_limit, usage_limit=d.usage_limit))
    await s.commit()
    return {"key": k_str}

@router.get("/admin/keys", dependencies=[Depends(get_current_admin)])
async def list_keys(s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(GatewayKey))).scalars().all()

@router.put("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def update_key(key: str, d: KeyRequest, s: AsyncSession = Depends(get_session)):
    k = await s.get(GatewayKey, key)
    if not k: raise HTTPException(404, "Key not found")
    
    k.name = d.name
    k.rate_limit = d.rate_limit
    k.usage_limit = d.usage_limit
    s.add(k)
    await s.commit()
    return {"status": "ok", "key": k}

@router.delete("/admin/keys/{key}", dependencies=[Depends(get_current_admin)])
async def delete_key(key: str, s: AsyncSession = Depends(get_session)):
    k = await s.get(GatewayKey, key)
    if k: 
        await s.delete(k)
        await s.commit()
    return {"status": "ok"}

# --- CRUD MAPPINGS ---
class MapReq(BaseModel): 
    source_model: str
    target_model: str

@router.post("/admin/maps", dependencies=[Depends(get_current_admin)])
async def create_map(d: MapReq, s: AsyncSession = Depends(get_session)):
    if await s.get(ModelMap, d.source_model): 
        raise HTTPException(400, "Mapping exists")
    s.add(ModelMap(source_model=d.source_model, target_model=d.target_model))
    await s.commit()
    return {"status": "ok"}

@router.get("/admin/maps", dependencies=[Depends(get_current_admin)])
async def list_maps(s: AsyncSession = Depends(get_session)):
    return (await s.execute(select(ModelMap))).scalars().all()

@router.delete("/admin/maps", dependencies=[Depends(get_current_admin)])
async def delete_map(source: str, s: AsyncSession = Depends(get_session)):
    m = await s.get(ModelMap, source)
    if m: 
        await s.delete(m)
        await s.commit()
    return {"status": "ok"}