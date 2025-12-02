from fastapi import FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware  # <--- Import CORS
from contextlib import asynccontextmanager
from sqlmodel import Session, text

# Import các hàm khởi tạo
from app.database import create_db_and_tables, init_redis, close_redis, engine
# Import module database để lấy biến redis_client realtime (Fix lỗi Redis disabled)
import app.database as db_module 

from app.models import GatewayKey
from app.config import MASTER_TRACKER_ID
from app.routers import admin, gateway
from app.engine import ai_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Init DB & Master Key
    create_db_and_tables()
    with Session(engine) as session:
        if not session.get(GatewayKey, MASTER_TRACKER_ID):
            session.add(GatewayKey(
                key=MASTER_TRACKER_ID, 
                name="👑 ADMIN TRACKER", 
                usage_count=0, 
                is_hidden=True
            ))
            session.commit()
        
        # 2. Init AI Engine
        ai_engine.initialize(session)
    
    # 3. Init Redis
    await init_redis()
    
    yield
    
    # 4. Cleanup
    await close_redis()

app = FastAPI(lifespan=lifespan, title="AI Gateway Enterprise")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = str(exc)
    
    # Log lỗi ra terminal để debug
    print(f"❌ [Global Error] {error_msg}")
    
    # Trả về JSON thay vì HTML
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": f"Provider Error or Internal Server Error: {error_msg}",
                "type": "internal_server_error",
                "code": 500,
                "param": None
            }
        }
    )

# --- 1. CẤU HÌNH CORS (BYPASS) ---
# Cho phép tất cả các domain khác gọi vào API này
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Cho phép mọi nguồn (localhost, vercel, v.v.)
    allow_credentials=True,
    allow_methods=["*"],      # Cho phép mọi method (GET, POST, PUT, DELETE...)
    allow_headers=["*"],      # Cho phép mọi header
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

    # Check Database
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
        status_report["components"]["db"] = "up"
    except Exception as e:
        status_report["components"]["db"] = f"down: {str(e)}"
        is_healthy = False

    # Check Redis (Dùng db_module để tránh lỗi stale import)
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
async def root(): return RedirectResponse(url="/panel")

@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
async def panel():
    try:
        with open("app/templates/panel.html", "r", encoding="utf-8") as f: 
            return f.read()
    except FileNotFoundError:
        return "Panel HTML not found."

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
