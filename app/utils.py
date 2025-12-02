import httpx
from sqlmodel import select, Session
from fastapi import HTTPException
from app.models import Provider, ModelMap
from app.config import MODEL_FETCH_TIMEOUT

async def fetch_provider_models(client: httpx.AsyncClient, provider: Provider):
    fetched_ids = []
    if provider.provider_type == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={provider.api_key}"
        try:
            resp = await client.get(url, timeout=MODEL_FETCH_TIMEOUT)
            if resp.status_code == 200 and "models" in resp.json():
                for item in resp.json()["models"]: fetched_ids.append(item.get("name", "").replace("models/", ""))
        except: pass
    else:
        api_base = provider.base_url
        if not api_base:
            if provider.provider_type == "openrouter": api_base = "https://openrouter.ai/api/v1"
            elif provider.provider_type == "openai": api_base = "https://api.openai.com/v1"
            else: return []
        api_base = api_base.rstrip('/')
        if not api_base.endswith("/v1"): api_base += "/v1"
        
        headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
        if provider.provider_type == "openrouter": headers["HTTP-Referer"] = "gw"
        try:
            resp = await client.get(f"{api_base}/models", headers=headers, timeout=MODEL_FETCH_TIMEOUT)
            if resp.status_code == 200 and "data" in resp.json():
                for item in resp.json()["data"]: fetched_ids.append(item["id"])
        except: pass

    return [{"id": f"{provider.name}/{m}", "object": "model", "created": 1700000000, "owned_by": provider.provider_type} for m in fetched_ids]

def parse_model_alias(raw_model: str, session: Session):
    # 1. Check Forwarding Map
    forward_rule = session.get(ModelMap, raw_model)
    if forward_rule:
        raw_model = forward_rule.target_model

    # 2. Standard Logic
    if "/" not in raw_model:
        providers = session.exec(select(Provider)).all()
        for p in providers:
            if p.provider_type in ["openrouter", "gemini", "openai"]: return p, raw_model
        if providers: return providers[0], raw_model
        raise HTTPException(400, "Unknown model alias")
    
    alias, actual = raw_model.split("/", 1)
    provider = session.get(Provider, alias)
    if not provider: raise HTTPException(404, f"Provider '{alias}' not found")
    return provider, actual
