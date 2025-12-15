import httpx
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.models import Provider, ModelMap
from app.config import MODEL_FETCH_TIMEOUT

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
        # Auto-fill base_url nếu user để trống
        if not api_base:
            if provider.provider_type == "openrouter": api_base = "https://openrouter.ai/api/v1"
            elif provider.provider_type == "openai": api_base = "https://api.openai.com/v1"
            else: return []
        
        # Normalize URL
        api_base = api_base.rstrip('/')
        if not api_base.endswith("/v1") and "azure" not in provider.provider_type: 
            # Azure thường có format khác (/openai/deployments...), còn lại thường là /v1
            api_base += "/v1"
        
        headers = {
            "Authorization": f"Bearer {provider.api_key}", 
            "Content-Type": "application/json"
        }
        if provider.provider_type == "openrouter": 
            headers["HTTP-Referer"] = "gw"
            
        try:
            # Azure endpoint list models khác biệt, ở đây ta assume standard OpenAI format
            # Nếu là Azure, fetch models thường phức tạp hơn (cần list deployments), 
            # tạm thời support standard /models endpoint
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

async def parse_model_alias(raw_model: str, session: AsyncSession):
    """
    Phân giải Model Alias -> (Provider, Real Model Name).
    Hỗ trợ Async Database.
    """
    if not raw_model:
         raw_model = "gpt-3.5-turbo"

    # 1. Check Forwarding Map (Async)
    # Lưu ý: Nếu source_model KHÔNG phải là Primary Key của ModelMap, 
    # hãy dùng select().where() thay vì session.get()
    # Ở đây giả sử source_model có thể tìm được bằng query
    stmt_map = select(ModelMap).where(ModelMap.source_model == raw_model)
    res_map = await session.execute(stmt_map)
    forward_rule = res_map.scalars().first()
    
    if forward_rule:
        raw_model = forward_rule.target_model

    # 2. Standard Logic (alias/model_name)
    if "/" not in raw_model:
        # Fallback: Nếu user chỉ gửi "gpt-4" mà không có alias provider -> Tìm provider đầu tiên phù hợp
        
        # [FIX] Dùng execute() thay vì exec()
        result = await session.execute(select(Provider))
        providers = result.scalars().all() # [FIX] Dùng scalars() để lấy object
        
        # Ưu tiên các provider phổ biến
        for p in providers:
            if p.provider_type in ["openrouter", "gemini", "openai"]: 
                return p, raw_model
        
        if providers: 
            return providers[0], raw_model
            
        raise HTTPException(400, "Unknown model alias and no default provider found.")
    
    # 3. Parse Alias
    alias, actual = raw_model.split("/", 1)
    
    # [FIX] Dùng select theo tên thay vì session.get (trừ khi alias là ID)
    stmt_provider = select(Provider).where(Provider.name == alias)
    res_provider = await session.execute(stmt_provider)
    provider = res_provider.scalars().first()
    
    if not provider: 
        raise HTTPException(404, f"Provider '{alias}' not found")
        
    return provider, actual