from fastapi import FastAPI, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from contextlib import asynccontextmanager
from sqlmodel import Session, text


from app.database import create_db_and_tables, init_redis, close_redis, engine
import app.database as db_module
from app.models import GatewayKey
from app.config import MASTER_TRACKER_ID
from app.routers import admin, gateway
from app.engine import ai_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Init DB
    create_db_and_tables()
    
    # 2. Check/Create Master Key
    with Session(engine) as session:
        if not session.get(GatewayKey, MASTER_TRACKER_ID):
            session.add(GatewayKey(key=MASTER_TRACKER_ID, name="👑 ADMIN TRACKER", usage_count=0, is_hidden=True))
            session.commit()
        
        # 3. Init AI Engine
        ai_engine.initialize(session)
    
    # 4. Init Redis
    await init_redis()
    
    yield
    
    # 5. Cleanup
    await close_redis()

app = FastAPI(lifespan=lifespan, title="AI Gateway Enterprise")

# --- HEALTH CHECK ENDPOINT (MỚI THÊM) ---
@app.get("/health", tags=["System"])
async def health_check():
    """
    Kiểm tra trạng thái hệ thống (Database & Redis).
    Trả về 503 nếu một trong các component bị chết.
    """
    status_report = {
        "status": "ok",
        "components": {
            "db": "unknown",
            "redis": "disabled"
        }
    }
    is_healthy = True

    # 1. Check Database
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
        status_report["components"]["db"] = "up"
    except Exception as e:
        status_report["components"]["db"] = f"down: {str(e)}"
        is_healthy = False

    # 2. Check Redis
    if db_module.redis_client: 
        try:
            await db_module.redis_client.ping()
            status_report["components"]["redis"] = "up"
        except Exception as e:
            status_report["components"]["redis"] = f"down: {str(e)}"
            is_healthy = False
    else:
        # Debug thêm: In ra để biết tại sao nó vẫn None (nếu cần)
        # print("Redis client is still None inside module!")
        pass

    # Trả về lỗi 503 nếu hệ thống không khỏe
    if not is_healthy:
        status_report["status"] = "degraded"
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            content=status_report
        )
    
    return status_report
# ----------------------------------------

app.include_router(admin.router)
app.include_router(gateway.router)

@app.get("/", include_in_schema=False)
async def root(): return RedirectResponse(url="/panel")

@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
async def panel():
    with open("app/templates/panel.html", "r", encoding="utf-8") as f: return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
