import asyncio
import time
from fastapi import FastAPI, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from sqlmodel import text

from app.database import (
    create_db_and_tables, 
    init_redis, 
    close_redis, 
    AsyncSessionLocal,
    redis_client 
)
import app.database as db_module 

from app.routers import admin, gateway
from app.engine import ai_engine
from app.cache import log_cache, FLUSH_INTERVAL
from app.utils import refresh_model_cache 

# ID phiên bản (Cache Busting)
SERVER_VER = str(int(time.time()))
templates = Jinja2Templates(directory="app/templates")

# --- BACKGROUND TASKS ---
async def log_flusher_task():
    """Chạy định kỳ xả log từ Redis xuống DB"""
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        await log_cache.flush_to_db()

async def warmup_cache_task():
    """Chạy ngầm lấy danh sách Model để không chặn quá trình khởi động server"""
    print("🔄 [System] Warming up Model Cache (Background)...")
    try:
        async with AsyncSessionLocal() as session:
            # Hàm này sẽ gọi API của các provider để lấy model thật về
            models, count = await refresh_model_cache(session)
            print(f"✅ [System] Cache Warmup Complete: {count} models available.")
    except Exception as e:
        print(f"❌ [System] Cache Warmup Failed: {e}")

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    print("🚀 [System] Starting up...")
    
    # 1. Init DB
    await create_db_and_tables()
    
    # 2. Init Engine
    async with AsyncSessionLocal() as session:
        await ai_engine.initialize(session)
    
    # 3. Init Redis
    await init_redis()

    # 4. Start Background Tasks (Non-blocking)
    asyncio.create_task(warmup_cache_task()) # Lấy model ngầm
    flusher = asyncio.create_task(log_flusher_task()) # Ghi log ngầm
    
    yield
    
    # --- SHUTDOWN ---
    print("🛑 [System] Shutting down...")
    
    flusher.cancel()
    
    print("💾 [System] Flushing remaining logs to DB...")
    await log_cache.flush_to_db()
    
    await close_redis()
    print("✅ [System] Shutdown complete.")

app = FastAPI(lifespan=lifespan, title="AI Gateway Enterprise")

# --- STATIC FILES ---
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        
    allow_credentials=True,
    allow_methods=["*"],        
    allow_headers=["*"],        
)

# --- HEALTH CHECK ---
@app.get("/health", tags=["System"])
async def health_check():
    status_report = {"status": "ok", "components": {"db": "unknown", "redis": "disabled"}}
    is_healthy = True

    # Check DB
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        status_report["components"]["db"] = "up"
    except Exception as e:
        status_report["components"]["db"] = f"down: {str(e)}"
        is_healthy = False

    # Check Redis
    if db_module.redis_client:
        try:
            await db_module.redis_client.ping()
            status_report["components"]["redis"] = "up"
        except Exception as e:
            status_report["components"]["redis"] = f"down: {str(e)}"
            is_healthy = False
    
    if not is_healthy:
        status_report["status"] = "degraded"
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=status_report)
    
    return status_report

# --- ROUTERS ---
app.include_router(admin.router)
app.include_router(gateway.router)

@app.get("/", include_in_schema=False)
async def root(): 
    return RedirectResponse(url="/panel")

# Route Panel (Dashboard)
@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
async def panel(request: Request):
    return templates.TemplateResponse("panel.html", {"request": request, "ver": SERVER_VER})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)