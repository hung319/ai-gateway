import json
import asyncio
import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session, select
from litellm import acompletion, image_generation, speech, transcription

from app.database import get_session, redis_client
from app.models import Provider, GatewayKey
from app.security import verify_usage
from app.utils import fetch_provider_models, parse_model_alias
from app.engine import ai_engine
from app.config import CACHE_TTL

router = APIRouter(prefix="/v1", tags=["Gateway"])

# --- 1. LIST MODELS ---
@router.get("/models")
async def list_models(k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
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

# --- 2. CHAT COMPLETIONS (FIXED JSON RESPONSE) ---
@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "JSON Error")
    
    if "input" in body and "messages" not in body: body["messages"]=body["input"]; del body["input"]
    
    provider, real_model = parse_model_alias(body.get("model", ""), s)
    del body["model"]
    
    # Construct LiteLLM Model String
    if provider.provider_type == "openai":
        litellm_model = f"openai/{real_model}" 
    elif provider.provider_type == "azure":
        litellm_model = f"azure/{real_model}"
    else:
        litellm_model = f"{provider.provider_type}/{real_model}"

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
        **{k: v for k, v in body.items() if k not in ["model", "messages"]}
    }

    if provider.base_url:
        kwargs["api_base"] = provider.base_url
        if provider.provider_type == "openai":
            kwargs["custom_llm_provider"] = "openai"

    try:
        if body.get("stream", False):
            async def gen():
                response = await acompletion(**kwargs)
                async for chunk in response:
                    # Chunk trong stream là object, cần .json() để serialize
                    yield f"data: {chunk.json()}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            # --- [FIX LỖI DOUBLE JSON ENCODING] ---
            response = await acompletion(**kwargs)
            
            # Cách 1: Parse chuỗi JSON từ litellm thành dict rồi mới trả về
            # response.json() trả về string -> json.loads chuyển thành dict -> JSONResponse serialize lại thành chuẩn
            return JSONResponse(content=json.loads(response.json()))
            
    except Exception as e:
        print(f"❌ Gateway Error: {str(e)}")
        # Trả về lỗi chuẩn JSON để n8n đọc được
        return JSONResponse(
            status_code=500, 
            content={"error": {"message": str(e), "type": "internal_server_error"}}
        )

# --- 3. MULTIMEDIA ---
@router.post("/images/generations")
async def image_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try: 
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=1, size=body.get("size","1024x1024"))
        return JSONResponse(content=json.loads(res.json())) # FIX TƯƠNG TỰ
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/videos/generations")
async def video_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try:
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=1)
        return JSONResponse(content=json.loads(res.json())) # FIX TƯƠNG TỰ
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/audio/speech")
async def tts(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try:
        res = await speech(model=m, input=body.get("input"), voice=body.get("voice","alloy"), api_key=p.api_key, api_base=p.base_url)
        return StreamingResponse(res.iter_content(1024), media_type="audio/mpeg")
    except Exception as e: raise HTTPException(500, str(e))

@router.post("/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    p, m = parse_model_alias(model, s)
    try:
        res = await transcription(model=m, file=file.file, api_key=p.api_key, api_base=p.base_url)
        return JSONResponse(content=json.loads(res.json())) # FIX TƯƠNG TỰ
    except Exception as e: raise HTTPException(500, str(e))
