import json
import asyncio
import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from sqlmodel import Session, select
from litellm import acompletion, image_generation, speech, transcription

# --- IMPORT CÁC LOẠI LỖI CỦA LITELLM ---
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    BudgetExceededError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    UnprocessableEntityError,
)

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

# --- 2. CHAT COMPLETIONS ---
@router.post("/chat/completions")
async def chat(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
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
        # Lọc các tham số khác
        **{k: v for k, v in body.items() if k not in ["model", "messages"]}
    }

    if provider.base_url:
        kwargs["api_base"] = provider.base_url
        if provider.provider_type == "openai": kwargs["custom_llm_provider"] = "openai"

    # --- EXECUTION ---
    try:
        # 1. Gọi acompletion NGAY LẬP TỨC để bắt lỗi khởi tạo (Auth, RateLimit, TokenLimit...)
        # Nếu lỗi ở đây, nó sẽ nhảy xuống except block và trả về JSON đúng chuẩn.
        response = await acompletion(**kwargs)

        # 2. Xử lý Stream
        if body.get("stream", False):
            async def gen():
                try:
                    # response là một async generator khi stream=True
                    async for chunk in response:
                        if chunk:
                            data_str = chunk.model_dump_json()
                            yield f"data: {data_str}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    # Lỗi xảy ra *giữa* chừng khi đang stream (ít gặp hơn)
                    # Lúc này header 200 đã gửi rồi, nên chỉ có thể gửi text lỗi
                    err_payload = json.dumps({"error": str(e)})
                    yield f"data: {err_payload}\n\n"
            
            return StreamingResponse(gen(), media_type="text/event-stream")
        
        # 3. Xử lý Non-Stream
        else:
            # Dùng model_dump() để lấy Dictionary
            if hasattr(response, 'model_dump'):
                final_data = response.model_dump()
            else:
                final_data = response.dict() 
            
            return JSONResponse(content=final_data)
            
    # --- BẮT CÁC LỖI CỤ THỂ CỦA LITELLM ---
    except (
        AuthenticationError,
        BadRequestError,      # Gồm ContextWindowExceededError, ContentPolicyViolationError
        NotFoundError,
        PermissionDeniedError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
        UnprocessableEntityError,
        APIConnectionError,
        APIError,
        BudgetExceededError
    ) as e:
        # Lấy status_code từ lỗi (mặc định 500 nếu không có)
        error_code = getattr(e, "status_code", 500)
        if isinstance(e, BudgetExceededError): error_code = 400 # Budget lỗi thường là 400
        
        # Đảm bảo code là int
        if not isinstance(error_code, int): error_code = 500

        return JSONResponse(
            status_code=error_code,
            content={
                "error": {
                    "message": str(e), # Message đầy đủ (bao gồm link shop, lý do...)
                    "type": type(e).__name__,
                    "param": None,
                    "code": error_code
                }
            }
        )

    except Exception as e:
        # Catch-all cho lỗi hệ thống (Code lỗi, DB lỗi...)
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
# (Các phần này giữ nguyên hoặc có thể áp dụng khối try/except tương tự như trên nếu muốn bắt lỗi chi tiết cho ảnh/voice)

@router.post("/images/generations")
async def image_gen(req: Request, k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
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
    try: body=await req.json()
    except: raise HTTPException(400, "JSON Error")
    p, m = parse_model_alias(body.get("model",""), s)
    try:
        res = await speech(model=m, input=body.get("input"), voice=body.get("voice","alloy"), api_key=p.api_key, api_base=p.base_url)
        return StreamingResponse(res.iter_content(chunk_size=1024), media_type="audio/mpeg")
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage), s: Session=Depends(get_session)):
    p, m = parse_model_alias(model, s)
    try:
        res = await transcription(model=m, file=file.file, api_key=p.api_key, api_base=p.base_url)
        data = res.model_dump() if hasattr(res, 'model_dump') else res.dict()
        return JSONResponse(content=data)
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})
