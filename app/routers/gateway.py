import json
import asyncio
import httpx
import inspect
import time
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session, select
from litellm import acompletion, image_generation, speech, transcription

# --- IMPORT DYNAMIC EXCEPTIONS ---
import litellm.exceptions

# --- TỰ ĐỘNG LẤY TẤT CẢ LỖI TỪ LITELLM ---
LITELLM_EXCEPTIONS = tuple(
    member for name, member in inspect.getmembers(litellm.exceptions)
    if inspect.isclass(member) and issubclass(member, Exception)
)

from app.database import get_session, redis_client
from app.models import Provider, GatewayKey
from app.security import verify_usage
from app.utils import fetch_provider_models, parse_model_alias
from app.config import CACHE_TTL

router = APIRouter(prefix="/v1", tags=["Gateway"])

# --- HELPER: CHECK LIMITS ---
async def check_limits(k: GatewayKey):
    """
    Kiểm tra Usage Limit (Quota) và Rate Limit (RPM).
    Raise HTTPException nếu vượt quá giới hạn.
    """
    # 1. Check Usage Limit (Quota)
    if k.usage_limit is not None and k.usage_count >= k.usage_limit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Usage limit exceeded for this API Key."
        )

    # 2. Check Rate Limit (RPM)
    if k.rate_limit is not None:
        if redis_client:
            # Sử dụng Redis để đếm request trong cửa sổ 60s
            key_redis = f"ratelimit:{k.key}"
            current_count = await redis_client.incr(key_redis)
            if current_count == 1:
                await redis_client.expire(key_redis, 60)
            
            if current_count > k.rate_limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded."
                )
        else:
            # Fallback nếu không có Redis (Simple Warning log or pass)
            pass

# --- 1. LIST MODELS ---
@router.get("/models")
async def list_models(k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    # Check limit cho list models (optional, thường thì không cần tính quota nhưng có thể tính rate limit)
    await check_limits(k)

    if redis_client:
        try:
            c = await redis_client.get("gw:models")
            if c: return json.loads(c)
        except: pass
    
    ps = s.exec(select(Provider)).all()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in ps]
        res = await asyncio.gather(*tasks)
    
    final = {"object": "list", "data": [m for sub in res for m in sub]}
    
    if redis_client:
        try: await redis_client.set("gw:models", json.dumps(final), ex=CACHE_TTL)
        except: pass
    return final

# --- 2. CHAT COMPLETIONS ---
@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    # --- CHECK LIMITS ---
    await check_limits(k)

    try: 
        body = await req.json()
    except: 
        raise HTTPException(400, "JSON Error")
    
    # Fix Cursor/Agent inputs
    if "input" in body and "messages" not in body: body["messages"]=body["input"]; del body["input"]
    
    # Parse Model
    raw_model = body.get("model", "")
    provider, real_model = parse_model_alias(raw_model, s)
    del body["model"]
    
    # Construct LiteLLM Model String
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
    try:
        # Gọi acompletion
        response = await acompletion(**kwargs)

        # Xử lý Stream
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
        
        # Xử lý Non-Stream
        else:
            if hasattr(response, 'model_dump'):
                final_data = response.model_dump()
            else:
                final_data = response.dict() 
            return JSONResponse(content=final_data)
            
    # --- BẮT LỖI TỰ ĐỘNG ---
    except LITELLM_EXCEPTIONS as e:
        error_code = getattr(e, "status_code", 500)
        if not isinstance(error_code, int): 
            error_code = 400

        return JSONResponse(
            status_code=error_code,
            content={
                "error": {
                    "message": str(e),
                    "type": type(e).__name__,
                    "param": None,
                    "code": error_code
                }
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "message": f"Internal Server Error: {str(e)}",
                    "type": "internal_server_error",
                    "param": None,
                    "code": 500
                }
            }
        )

# --- 3. MULTIMEDIA ---

@router.post("/images/generations")
async def image_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    await check_limits(k) # Check Limit
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try: 
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=body.get("n",1), size=body.get("size","1024x1024"))
        data = res.model_dump() if hasattr(res, 'model_dump') else res.dict()
        return JSONResponse(content=data)
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/videos/generations")
async def video_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    await check_limits(k) # Check Limit
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try:
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=1)
        data = res.model_dump() if hasattr(res, 'model_dump') else res.dict()
        return JSONResponse(content=data)
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/audio/speech")
async def tts(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    await check_limits(k) # Check Limit
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try:
        res = await speech(model=m, input=body.get("input"), voice=body.get("voice","alloy"), api_key=p.api_key, api_base=p.base_url)
        return StreamingResponse(res.iter_content(chunk_size=1024), media_type="audio/mpeg")
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    await check_limits(k) # Check Limit
    p, m = parse_model_alias(model, s)
    try:
        res = await transcription(model=m, file=file.file, api_key=p.api_key, api_base=p.base_url)
        data = res.model_dump() if hasattr(res, 'model_dump') else res.dict()
        return JSONResponse(content=data)
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})