import httpx
import json
import asyncio
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.models import Provider, ModelMap
from app.config import MODEL_FETCH_TIMEOUT, CACHE_TTL
# Import Redis client để lưu cache tại đây luôn
from app.database import redis_client

async def fetch_provider_models(client: httpx.AsyncClient, provider: Provider):
    """
    Fetch list models từ Provider API (Async).
    """
    fetched_ids = []
    
    # --- GEMINI LOGIC ---
    if provider.provider_type == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={provider.api_key}"
        try:
            resp = await client.get(url, timeout=MODEL_FETCH_TIMEOUT)
            if resp.status_code == 200 and "models" in resp.json():
                for item in resp.json()["models"]: 
                    fetched_ids.append(item.get("name", "").replace("models/", ""))
        except: 
            pass

    # --- OPENAI / OPENROUTER / AZURE LOGIC ---
    else:
        api_base = provider.base_url
        if not api_base:
            if provider.provider_type == "openrouter": api_base = "https://openrouter.ai/api/v1"
            elif provider.provider_type == "openai": api_base = "https://api.openai.com/v1"
            else: return []
        
        api_base = api_base.rstrip('/')
        if not api_base.endswith("/v1") and "azure" not in provider.provider_type: 
            api_base += "/v1"
        
        headers = {
            "Authorization": f"Bearer {provider.api_key}", 
            "Content-Type": "application/json"
        }
        if provider.provider_type == "openrouter": 
            headers["HTTP-Referer"] = "gw"
            
        try:
            resp = await client.get(f"{api_base}/models", headers=headers, timeout=MODEL_FETCH_TIMEOUT)
            if resp.status_code == 200 and "data" in resp.json():
                for item in resp.json()["data"]: 
                    fetched_ids.append(item["id"])
        except: 
            pass

    return [{
        "id": f"{provider.name}/{m}", 
        "object": "model", 
        "created": 1700000000, 
        "owned_by": provider.provider_type
    } for m in fetched_ids]

# --- NEW: HÀM CẬP NHẬT CACHE ---
async def refresh_model_cache(session: AsyncSession):
    """
    Hàm này lấy tất cả provider, fetch models thật và lưu vào Redis.
    Trả về: List Models và Count.
    """
    try:
        result = await session.execute(select(Provider))
        providers = result.scalars().all()
        
        if not providers:
            return [], 0

        async with httpx.AsyncClient() as client:
            tasks = [fetch_provider_models(client, p) for p in providers]
            res = await asyncio.gather(*tasks)
        
        all_models = [m for sub in res for m in sub]
        final_data = {"object": "list", "data": all_models}
        
        # Lưu vào Redis
        if redis_client:
            await redis_client.set("gw:models", json.dumps(final_data), ex=CACHE_TTL)
            
        return all_models, len(all_models)
    except Exception as e:
        print(f"Error refreshing model cache: {e}")
        return [], 0

async def parse_model_alias(raw_model: str, session: AsyncSession):
    # ... (Giữ nguyên logic cũ của hàm này) ...
    if not raw_model: raw_model = "gpt-3.5-turbo"
    stmt_map = select(ModelMap).where(ModelMap.source_model == raw_model)
    res_map = await session.execute(stmt_map)
    forward_rule = res_map.scalars().first()
    if forward_rule: raw_model = forward_rule.target_model

    if "/" not in raw_model:
        result = await session.execute(select(Provider))
        providers = result.scalars().all()
        for p in providers:
            if p.provider_type in ["openrouter", "gemini", "openai"]: return p, raw_model
        if providers: return providers[0], raw_model
        raise HTTPException(400, "Unknown model alias")
    
    alias, actual = raw_model.split("/", 1)
    stmt_provider = select(Provider).where(Provider.name == alias)
    res_provider = await session.execute(stmt_provider)
    provider = res_provider.scalars().first()
    
    if not provider: raise HTTPException(404, f"Provider '{alias}' not found")
    return provider, actual