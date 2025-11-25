import secrets
from fastapi import FastAPI, Response, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from contextlib import asynccontextmanager
from sqlmodel import Session
from pydantic import BaseModel

from app.database import create_db_and_tables, init_redis, close_redis, engine, get_session
from app.models import GatewayKey, AdminSession
from app.config import MASTER_KEY, MASTER_TRACKER_ID
from app.routers import admin, gateway
from app.security import create_session

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    with Session(engine) as session:
        if not session.get(GatewayKey, MASTER_TRACKER_ID):
            session.add(GatewayKey(key=MASTER_TRACKER_ID, name="👑 ADMIN TRACKER", usage_count=0, is_hidden=True))
            session.commit()
    await init_redis()
    yield
    await close_redis()

app = FastAPI(lifespan=lifespan, title="AI Gateway v3.4 Secure")

app.include_router(admin.router)
app.include_router(gateway.router)

# --- AUTH ROUTES ---
class LoginRequest(BaseModel):
    master_key: str

@app.post("/api/auth/login")
async def login(data: LoginRequest, response: Response, session: Session = Depends(get_session)):
    """Đăng nhập và set HttpOnly Cookie"""
    if secrets.compare_digest(data.master_key, MASTER_KEY):
        # Tạo session
        token = create_session(session)
        # Set cookie (HttpOnly = True để JS không đọc được -> Chống XSS lấy key)
        response.set_cookie(
            key="gateway_session", 
            value=token, 
            httponly=True, 
            max_age=7*24*60*60, 
            samesite="strict"
        )
        return {"status": "ok"}
    else:
        raise HTTPException(status_code=401, detail="Invalid Master Key")

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("gateway_session")
    return {"status": "ok"}

# --- FRONTEND ---
@app.get("/", include_in_schema=False)
async def root(): return RedirectResponse(url="/panel")

@app.get("/panel", response_class=HTMLResponse, include_in_schema=False)
async def panel():
    with open("app/templates/panel.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
