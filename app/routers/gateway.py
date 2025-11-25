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

@router.get("/models")
async def list_models(k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    if redis_client:
        c = await redis_client.get("gw:models")
        if c: return json.loads(c)
    
    ps = s.exec(select(Provider)).all()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in ps]
        res = await asyncio.gather(*tasks)
    
    final = {"object": "list", "data": [m for sub in res for m in sub]}
    if redis_client: await redis_client.set("gw:models", json.dumps(final), ex=CACHE_TTL)
    return final

@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "JSON")
    
    if "input" in body and "messages" not in body: body["messages"]=body["input"]; del body["input"]
    
    requested_model = body.get("model")
    # Nếu model chứa "/" (vd: google/gemini), AI Engine sẽ dùng nó làm Deployment ID
    # Nếu model ko chứa "/" (vd: gpt-4o), Router sẽ tìm deployment có model_name="gpt-4o"
    
    # Metadata cho Log
    metadata = {"user": k.name, "key_hash": k.key[:5]+"..."}
    
    kwargs = {
        "model": requested_model,
        "messages": body.get("messages"),
        "metadata": metadata,
        **{k: v for k, v in body.items() if k not in ["model", "messages"]}
    }

    try:
        if body.get("stream", False):
            async def gen():
                # Gọi qua Engine Router
                r = await ai_engine.router.acompletion(**kwargs)
                async for c in r: yield f"data: {c.json()}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            return JSONResponse((await ai_engine.router.acompletion(**kwargs)).json())
    except Exception as e:
        # Fallback logic nếu Router chưa init hoặc lỗi (dùng cách cũ)
        # ... (Code fallback cũ ở đây nếu muốn, nhưng Router nên hoạt động)
        raise HTTPException(500, str(e))

# --- Multimedia (Giữ nguyên cách cũ vì Router chủ yếu tối ưu cho Chat) ---
@app.post("/images/generations")
async def img(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body=await req.json()
    except: raise HTTPException(400)
    p, m = parse_model_alias(body.get("model",""), s)
    try: 
        res = await image_generation(model=m, prompt=body.get("prompt"), api_key=p.api_key, api_base=p.base_url, n=1, size=body.get("size","1024x1024"))
        return JSONResponse(res.json())
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/audio/speech")
async def tts(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    try: body=await req.json()
    except: raise HTTPException(400)
    p, m = parse_model_alias(body.get("model",""), s)
    try:
        res = await speech(model=m, input=body.get("input"), voice=body.get("voice","alloy"), api_key=p.api_key, api_base=p.base_url)
        return StreamingResponse(res.iter_content(1024), media_type="audio/mpeg")
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    p, m = parse_model_alias(model, s)
    try:
        res = await transcription(model=m, file=file.file, api_key=p.api_key, api_base=p.base_url)
        return JSONResponse(res.json())
    except Exception as e: raise HTTPException(500, str(e))
