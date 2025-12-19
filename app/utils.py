import httpx
import json
import asyncio
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Provider, ModelGroup # <-- Thay ModelMap bằng ModelGroup
from app.config import MODEL_FETCH_TIMEOUT, CACHE_TTL
from app.database import redis_client

async def fetch_provider_models(client: httpx.AsyncClient, provider: Provider):
    """
    Fetch list models từ Provider API (Async).
    Giữ nguyên logic cũ vì code này vẫn dùng để lấy raw models từ OpenAI/Gemini...
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

# --- NEW: HÀM CẬP NHẬT CACHE (Đã update logic Group) ---
async def refresh_model_cache(session: AsyncSession):
    """
    Hàm này lấy tất cả provider (raw models) + Model Groups (load balancers)
    và lưu vào Redis.
    """
    try:
        # 1. Fetch Raw Models
        result = await session.execute(select(Provider))
        providers = result.scalars().all()
        
        all_models = []
        if providers:
            async with httpx.AsyncClient() as client:
                tasks = [fetch_provider_models(client, p) for p in providers]
                res = await asyncio.gather(*tasks)
                all_models = [m for sub in res for m in sub]
        
        # 2. Fetch Model Groups -> THÊM PREFIX group/
        groups = (await session.execute(select(ModelGroup))).scalars().all()
        
        # SỬA DÒNG NÀY: Thêm f"group/{g.id}"
        group_data = [{
            "id": f"group/{g.id}", 
            "object": "model", 
            "owned_by": "gateway-group",
            "permission": [] 
        } for g in groups]
        
        # 3. Combine
        final_list = all_models + group_data
        final_data = {"object": "list", "data": final_list}
        
        # 4. Save to Redis
        if redis_client:
            await redis_client.set("gw:models", json.dumps(final_data), ex=CACHE_TTL)
            
        return final_list, len(final_list)
    except Exception as e:
        print(f"Error refreshing model cache: {e}")
        return [], 0