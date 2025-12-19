import json
import asyncio
import httpx
import inspect
import time
import random 
from datetime import datetime
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from litellm import acompletion, image_generation, speech, transcription

import litellm.exceptions

# Catch lỗi chuẩn của LiteLLM
LITELLM_EXCEPTIONS = tuple(
    member for name, member in inspect.getmembers(litellm.exceptions)
    if inspect.isclass(member) and issubclass(member, Exception)
)

from app.database import get_session, redis_client
from app.models import Provider, GatewayKey, RequestLog, ModelGroup, GroupMember
from app.security import verify_usage
from app.utils import fetch_provider_models
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

# --- HELPER: ROUTING LOGIC ---
async def select_model_from_group(raw_model_id: str, session: AsyncSession):
    """
    Xử lý logic tìm model thật từ Group ID.
    Input: "group/dall-e-3" -> Output: (ProviderObj, "dall-e-3")
    """
    clean_id = raw_model_id
    if clean_id.startswith("group/"):
        clean_id = clean_id.replace("group/", "", 1)

    # 1. Tìm Group
    group = await session.get(ModelGroup, clean_id)
    
    if not group:
        # Nếu user gọi có prefix group/ mà ko thấy -> 404
        if raw_model_id.startswith("group/"):
             raise HTTPException(404, f"Model Group '{clean_id}' not found.")
        # Nếu gọi trực tiếp model provider -> Trả về None để xử lý fallback
        return None, None 

    # 2. Lấy Members
    stmt = select(GroupMember).where(GroupMember.group_id == clean_id)
    members = (await session.execute(stmt)).scalars().all()
    
    if not members:
        raise HTTPException(503, f"Group '{clean_id}' has no active models.")

    selected_member = None

    # 3. Load Balance Strategy
    if group.balance_strategy == "round_robin" and redis_client:
        rr_key = f"rr_counter:{clean_id}"
        count = await redis_client.incr(rr_key)
        index = count % len(members)
        selected_member = members[index]
    elif group.balance_strategy == "weighted":
         weighted_pool = []
         for m in members:
             weighted_pool.extend([m] * m.weight)
         selected_member = random.choice(weighted_pool) if weighted_pool else random.choice(members)
    else:
        selected_member = random.choice(members)

    # 4. Get Provider
    provider = await session.get(Provider, selected_member.provider_name)
    if not provider:
         raise HTTPException(500, f"Provider '{selected_member.provider_name}' linked to group not found.")

    return provider, selected_member.target_model

# ==========================================
# 1. LIST MODELS
# ==========================================
@router.get("/models")
async def list_models(k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    
    # Fetch Provider Models (Optional)
    result = await s.execute(select(Provider))
    ps = result.scalars().all()
    
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in ps]
        res = await asyncio.gather(*tasks)
    
    raw_models = [m for sub in res for m in sub]

    # Fetch Groups & Add Prefix
    groups = (await s.execute(select(ModelGroup))).scalars().all()
    group_data = []
    for g in groups:
        display_id = g.id if g.id.startswith("group/") else f"group/{g.id}"
        group_data.append({
            "id": display_id, 
            "object": "model", 
            "created": int(time.time()),
            "owned_by": "gateway-group",
            "permission": []
        })
    
    return {"object": "list", "data": raw_models + group_data}

# ==========================================
# 2. CHAT COMPLETIONS
# ==========================================
@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    try: body = await req.json()
    except: raise HTTPException(400, "JSON Error")
    
    if "input" in body and "messages" not in body: body["messages"]=body["input"]; del body["input"]
    
    # Log Init
    raw_model = body.get("model", "unknown")
    log_entry = RequestLog(model=raw_model, app_name=k.name, status="processing", ts=datetime.utcnow(), ip=req.client.host)
    s.add(log_entry); await s.commit(); await s.refresh(log_entry)
    start_time = time.time()

    try:
        provider, real_model = await select_model_from_group(raw_model, s)
        if not provider: raise HTTPException(404, f"Model Group '{raw_model}' not found.")

        # Update Log
        log_entry.provider_name = provider.name; log_entry.real_model = real_model
        if "model" in body: del body["model"]
        
        # Litellm Params
        litellm_model = f"{provider.provider_type}/{real_model}" if provider.provider_type != "openai" else f"openai/{real_model}"
        kwargs = {
            "model": litellm_model, "messages": body.get("messages"), "api_key": provider.api_key,
            "metadata": {"user": k.name, "provider": provider.name, "group_id": raw_model},
            **{key: val for key, val in body.items() if key not in ["model", "messages"]}
        }
        if provider.base_url: kwargs["api_base"] = provider.base_url
        if provider.provider_type == "openai" and provider.base_url: kwargs["custom_llm_provider"] = "openai"

        response = await acompletion(**kwargs)

        # Log Success
        log_entry.status = "success"; log_entry.latency = time.time() - start_time
        if hasattr(response, 'usage'):
             log_entry.input_tokens = response.usage.prompt_tokens
             log_entry.output_tokens = response.usage.completion_tokens
        s.add(log_entry); await s.commit()

        if body.get("stream", False):
            async def gen():
                try:
                    async for chunk in response:
                        if chunk: yield f"data: {chunk.model_dump_json()}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e: yield f"data: {json.dumps({'error': str(e)})}\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            return JSONResponse(content=response.model_dump() if hasattr(response, 'model_dump') else response.dict())
            
    except Exception as e:
        log_entry.status = "fail"; log_entry.latency = time.time() - start_time
        s.add(log_entry); await s.commit()
        return JSONResponse(status_code=500, content={"error": {"message": str(e), "type": "internal_error"}})

# ==========================================
# 3. IMAGE GENERATIONS (Tạo ảnh)
# ==========================================
@router.post("/images/generations")
async def generate_image(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    try: body = await req.json()
    except: raise HTTPException(400, "JSON Error")

    raw_model = body.get("model", "dall-e-3")
    
    # Log Init
    log_entry = RequestLog(model=raw_model, app_name=k.name, status="processing_image", ts=datetime.utcnow(), ip=req.client.host)
    s.add(log_entry); await s.commit(); await s.refresh(log_entry)
    start_time = time.time()

    try:
        # Routing Logic cho Image
        provider, real_model = await select_model_from_group(raw_model, s)
        if not provider: raise HTTPException(404, f"Image Model Group '{raw_model}' not found.")

        # Update Log
        log_entry.provider_name = provider.name; log_entry.real_model = real_model
        
        # Call LiteLLM Image Generation
        response = await image_generation(
            model=real_model,
            prompt=body.get("prompt"),
            n=body.get("n", 1),
            size=body.get("size", "1024x1024"),
            api_key=provider.api_key,
            api_base=provider.base_url
        )

        # Log Success
        log_entry.status = "success"; log_entry.latency = time.time() - start_time
        s.add(log_entry); await s.commit()

        return JSONResponse(content=response.model_dump() if hasattr(response, 'model_dump') else response.dict())

    except Exception as e:
        log_entry.status = "fail"; log_entry.latency = time.time() - start_time
        s.add(log_entry); await s.commit()
        return JSONResponse(status_code=500, content={"error": {"message": str(e)}})

# ==========================================
# 4. AUDIO SPEECH (TTS)
# ==========================================
@router.post("/audio/speech")
async def tts(req: Request, k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    try: body = await req.json()
    except: raise HTTPException(400, "JSON Error")
    
    raw_model = body.get("model", "")
    
    # Log đơn giản hoặc log đầy đủ tùy bạn (ở đây log init)
    log_entry = RequestLog(model=raw_model, app_name=k.name, status="processing_audio", ts=datetime.utcnow())
    s.add(log_entry); await s.commit()

    try:
        provider, real_model = await select_model_from_group(raw_model, s)
        if not provider: raise HTTPException(404, f"Audio Model Group '{raw_model}' not found.")
        
        # Update Log
        log_entry.real_model = real_model; log_entry.provider_name = provider.name
        s.add(log_entry); await s.commit()

        res = await speech(
            model=real_model, 
            input=body.get("input"), 
            voice=body.get("voice", "alloy"), 
            api_key=provider.api_key, 
            api_base=provider.base_url
        )
        
        # Log success
        log_entry.status = "success"
        s.add(log_entry); await s.commit()

        return StreamingResponse(res.iter_content(chunk_size=1024), media_type="audio/mpeg")
    except Exception as e: 
        log_entry.status = "fail"
        s.add(log_entry); await s.commit()
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==========================================
# 5. AUDIO TRANSCRIPTIONS (STT)
# ==========================================
@router.post("/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage), s: AsyncSession=Depends(get_session)):
    await check_limits(k)
    
    log_entry = RequestLog(model=model, app_name=k.name, status="processing_stt", ts=datetime.utcnow())
    s.add(log_entry); await s.commit()

    try:
        provider, real_model = await select_model_from_group(model, s)
        if not provider: raise HTTPException(404, f"Model Group '{model}' not found.")
        
        log_entry.real_model = real_model; log_entry.provider_name = provider.name
        
        file_content = await file.read()
        res = await transcription(
            model=real_model, 
            file=file_content, 
            api_key=provider.api_key, 
            api_base=provider.base_url
        )
        
        log_entry.status = "success"
        s.add(log_entry); await s.commit()

        return JSONResponse(content=res.model_dump() if hasattr(res, 'model_dump') else res.dict())
    except Exception as e: 
        log_entry.status = "fail"
        s.add(log_entry); await s.commit()
        return JSONResponse(status_code=500, content={"error": str(e)})