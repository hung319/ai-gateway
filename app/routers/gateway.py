import json
import httpx
import asyncio
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session, select
from litellm import acompletion, image_generation, speech, transcription

from app.database import get_session, redis_client
from app.models import Provider, GatewayKey
from app.security import verify_usage
from app.utils import fetch_provider_models, parse_model_alias
from app.config import CACHE_TTL

router = APIRouter(prefix="/v1", tags=["AI Gateway"])

@router.get("/models")
async def list_models(k: GatewayKey = Depends(verify_usage), s: Session = Depends(get_session)):
    # 1. Cache
    if redis_client:
        cached = await redis_client.get("gw:models")
        if cached: return json.loads(cached)
    
    # 2. Fetch
    providers = s.exec(select(Provider)).all()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in providers]
        results = await asyncio.gather(*tasks)
    
    res = {"object": "list", "data": [m for sub in results for m in sub]}
    
    # 3. Set Cache
    if redis_client:
        await redis_client.set("gw:models", json.dumps(res), ex=CACHE_TTL)
    return res

@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey = Depends(verify_usage), s: Session = Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "Invalid JSON")

    # Cursor Fix
    if "input" in body and "messages" not in body:
        body["messages"] = body["input"]
        del body["input"]

    provider, actual_model = parse_model_alias(body.get("model", ""), s)
    del body["model"]

    litellm_model = f"{provider.provider_type}/{actual_model}"
    if provider.provider_type == "openai": litellm_model = actual_model

    kwargs = {
        "model": litellm_model,
        "messages": body.get("messages"),
        "api_key": provider.api_key,
        "metadata": {"user": k.name},
        **body
    }
    if provider.base_url:
        kwargs["api_base"] = provider.base_url
        kwargs["custom_llm_provider"] = "openai"

    try:
        if body.get("stream", False):
            async def gen():
                r = await acompletion(**kwargs)
                async for c in r: yield f"data: {c.json()}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            return JSONResponse((await acompletion(**kwargs)).json())
    except Exception as e:
        raise HTTPException(500, str(e))

# (Giữ nguyên các hàm image_gen, tts, stt tương tự, copy từ code cũ vào đây)
# ...
