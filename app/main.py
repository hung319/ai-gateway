from fastapi import FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from contextlib import asynccontextmanager
from sqlmodel import text, select

# Import các hàm khởi tạo từ module database async
from app.database import (
    create_db_and_tables, 
    init_redis, 
    close_redis, 
    AsyncSessionLocal # <--- Dùng cái này thay vì engine trực tiếp
)
# Import module database để lấy biến redis_client realtime
import app.database as db_module 

from app.models import GatewayKey
from app.config import MASTER_TRACKER_ID
from app.routers import admin, gateway
from app.engine import ai_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    
    # 1. Init DB & Master Key (Hàm này đã xử lý tạo Master Key bên trong)
    await create_db_and_tables()
    
    # 2. Init AI Engine
    # Cần tạo một session async tạm thời để load providers vào Router
    async with AsyncSessionLocal() as session:
        await ai_engine.initialize(session)
    
    # 3. Init Redis
    await init_redis()
    
    yield
    
    # --- SHUTDOWN ---
    await close_redis()

app = FastAPI(lifespan=lifespan, title="AI Gateway Enterprise")

# --- 0. STATIC FILES ---
# Mount thư mục static để phục vụ CSS/JS
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# --- 1. CẤU HÌNH CORS (BYPASS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      
    allow_credentials=True,
    allow_methods=["*"],      
    allow_headers=["*"],      
)

# --- 2. HEALTH CHECK ---
@app.get("/health", tags=["System"])
async def health_check():
    """
    Checks: Database Connection, Redis Connection.
    """
    status_report = {
        "status": "ok",
        "components": {
            "db": "unknown",
            "redis": "disabled"
        }
    }
    is_healthy = True

    # Check Database (Async)
    try:
        async with AsyncSessionLocal() as session:
            await session.exec(text("SELECT 1"))
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
    
    # Return 503 if unhealthy
    if not is_healthy:
        status_report["status"] = "degraded"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            content=status_report
        )
    
    return status_report

# --- 3. ROUTERS ---
app.include_router(admin.router)
app.include_router(gateway.router)

@app.get("/", include_in_schema=False)
async def root(): 
    return RedirectResponse(url="/panel")

@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
async def panel():
    try:
        # Đọc file HTML (Vẫn dùng sync open cho đơn giản vì file nhỏ)
        with open("app/templates/panel.html", "r", encoding="utf-8") as f: 
            return f.read()
    except FileNotFoundError:
        return "Panel HTML not found. Please check app/templates/panel.html"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)