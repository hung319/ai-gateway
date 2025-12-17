import json
import asyncio
import httpx
import inspect
import time
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from litellm import acompletion, image_generation, speech, transcription

import litellm.exceptions

LITELLM_EXCEPTIONS = tuple(
    member for name, member in inspect.getmembers(litellm.exceptions)
    if inspect.isclass(member) and issubclass(member, Exception)
)

from app.database import get_session, redis_client
# THÊM IMPORT RequestLog
from app.models import Provider, GatewayKey, RequestLog
from app.security import verify_usage
from app.utils import fetch_provider_models, parse_model_alias
from app.config import CACHE_TTL

router = APIRouter(prefix="/v1", tags=["Gateway"])

# --- HELPER: CHECK LIMITS ---
async def check_limits(k: GatewayKey):
    if k.usage_limit is not None and k.usage_count >= k.usage_limit:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Usage limit exceeded.")

    if k.rate_limit is not None and redis_client:
        key_redis = f"ratelimit:{k.key}"
        current = await redis_client.incr(key_redis)
        if current == 1: await redis_client.expire(key_redis, 60)
        
        if current > k.rate_limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded.")

# --- 1. LIST MODELS ---
@router.get("/models")
async def list_models(k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    if redis_client:
        try:
            c = await redis_client.get("gw:models")
            if c: return json.loads(c)
        except: pass
    
    result = await s.execute(select(Provider))
    ps = result.scalars().all()
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in ps]
        res = await asyncio.gather(*tasks)
    
    final = {"object": "list", "data": [m for sub in res for m in sub]}
    
    if redis_client:
        try: await redis_client.set("gw:models", json.dumps(final), ex=CACHE_TTL)
        except: pass
    return final

# --- 2. CHAT COMPLETIONS (LOGGING ADDED) ---
@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)

    try: 
        body = await req.json()
    except: 
        raise HTTPException(400, "JSON Error")
    
    if "input" in body and "messages" not in body: body["messages"]=body["input"]; del body["input"]
    
    # 1. LOGGING: INIT PROCESSING
    raw_model = body.get("model", "unknown")
    log_entry = RequestLog(
        model=raw_model,
        key_name=k.name,
        status="processing",
        timestamp=time.time()
    )
    s.add(log_entry)
    await s.commit()
    await s.refresh(log_entry) # Lấy ID để update sau này

    start_time = time.time()

    try:
        # Gọi Utils (Async)
        provider, real_model = await parse_model_alias(raw_model, s)
        
        # Cập nhật provider name vào log
        log_entry.provider_name = provider.name
        
        if "model" in body: del body["model"]
        
        if provider.provider_type == "openai": litellm_model = f"openai/{real_model}" 
        elif provider.provider_type == "azure": litellm_model = f"azure/{real_model}"
        else: litellm_model = f"{provider.provider_type}/{real_model}"

        metadata = {
            "user": k.name, 
            "key_hash": k.key[:5]+"...",
            "provider": provider.name
        }
        
        kwargs = {
            "model": litellm_model,
            "messages": body.get("messages"),
            "api_key": provider.api_key,
            "metadata": metadata,
            **{key: val for key, val in body.items() if key not in ["model", "messages"]}
        }

        if provider.base_url:
            kwargs["api_base"] = provider.base_url
            if provider.provider_type == "openai": kwargs["custom_llm_provider"] = "openai"

        # --- EXECUTION ---
        response = await acompletion(**kwargs)

        # 2. LOGGING: SUCCESS (Update Status & Latency)
        log_entry.status = "success"
        log_entry.latency = time.time() - start_time
        s.add(log_entry)
        await s.commit()

        if body.get("stream", False):
            async def gen():
                try:
                    async for chunk in response:
                        if chunk:
                            data_str = chunk.model_dump_json()
                            yield f"data: {data_str}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    err_payload = json.dumps({"error": str(e)})
                    yield f"data: {err_payload}\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            if hasattr(response, 'model_dump'):
                final_data = response.model_dump()
            else:
                final_data = response.dict() 
            return JSONResponse(content=final_data)
            
    except Exception as e:
        # 3. LOGGING: FAIL
        log_entry.status = "fail"
        log_entry.latency = time.time() - start_time
        s.add(log_entry)
        await s.commit()

        # Handle Errors
        if isinstance(e, LITELLM_EXCEPTIONS):
            error_code = getattr(e, "status_code", 500)
            if not isinstance(error_code, int): error_code = 400
            return JSONResponse(status_code=error_code, content={"error": {"message": str(e), "type": type(e).__name__, "code": error_code}})
        
        return JSONResponse(status_code=500, content={"error": {"message": f"Internal Error: {str(e)}", "type": "internal_server_error", "code": 500}})

# --- 3. MULTIMEDIA (Giữ nguyên logic cũ, có thể thêm Logging tương tự nếu cần) ---
@router.post("/images/generations")
async def image_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = await parse_model_alias(body.get("model",""), s)
    try: 
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=body.get("n",1), size=body.get("size","1024x1024"))
        return JSONResponse(content=res.model_dump() if hasattr(res, 'model_dump') else res.dict())
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/videos/generations")
async def video_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = await parse_model_alias(body.get("model",""), s)
    try:
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=1)
        return JSONResponse(content=res.model_dump() if hasattr(res, 'model_dump') else res.dict())
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/audio/speech")
async def tts(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = await parse_model_alias(body.get("model",""), s)
    try:
        res = await speech(model=m, input=body.get("input"), voice=body.get("voice","alloy"), api_key=p.api_key, api_base=p.base_url)
        return StreamingResponse(res.iter_content(chunk_size=1024), media_type="audio/mpeg")
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    p, m = await parse_model_alias(model, s)
    try:
        res = await transcription(model=m, file=file.file, api_key=p.api_key, api_base=p.base_url)
        return JSONResponse(content=res.model_dump() if hasattr(res, 'model_dump') else res.dict())
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})