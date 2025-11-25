from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from contextlib import asynccontextmanager
from sqlmodel import Session

from app.database import create_db_and_tables, init_redis, close_redis, engine
from app.models import GatewayKey
from app.config import MASTER_TRACKER_ID
from app.routers import admin, gateway
from app.engine import ai_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        if not session.get(GatewayKey, MASTER_TRACKER_ID):
            session.add(GatewayKey(key=MASTER_TRACKER_ID, name="👑 ADMIN TRACKER", usage_count=0, is_hidden=True))
            session.commit()
        
        # Init AI Engine
        ai_engine.initialize(session)
    
    await init_redis()
    yield
    await close_redis()

app = FastAPI(lifespan=lifespan, title="AI Gateway Enterprise")

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
