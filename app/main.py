import os
import secrets
import asyncio
from typing import Optional, List
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends, Security
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from sqlmodel import Field, Session, SQLModel, create_engine, select
from pydantic import BaseModel
from litellm import acompletion

# --- 1. CONFIGURATION ---
DB_PATH = os.getenv("DB_PATH", "gateway.db")
# MASTER_KEY: Key quyền lực nhất (dùng để Login Panel + Gọi API Bypass DB)
MASTER_KEY = os.getenv("MASTER_KEY", "sk-master-secret-123") 
MODEL_FETCH_TIMEOUT = 5.0 # Thời gian tối đa chờ 1 provider trả về list model

sqlite_url = f"sqlite:///{DB_PATH}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# --- 2. DATABASE MODELS ---
class Provider(SQLModel, table=True):
    name: str = Field(primary_key=True, index=True) # Alias: local, gpt4, deepseek
    api_key: str
    base_url: Optional[str] = None # Quan trọng cho Custom API
    provider_type: str = "openai" # Mặc định là openai cho độ tương thích cao nhất

class GatewayKey(SQLModel, table=True):
    key: str = Field(primary_key=True, index=True)
    name: str = Field(default="Client App")
    is_active: bool = Field(default=True)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

# --- 3. AUTHENTICATION LOGIC ---
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def get_token_from_header(header: str) -> str:
    if not header:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Header Format. Use 'Bearer <key>'")
    return parts[1]

async def verify_admin(header: str = Security(api_key_header)):
    """Chỉ MASTER_KEY mới được vào Admin API"""
    token = get_token_from_header(header)
    if not secrets.compare_digest(token, MASTER_KEY):
        raise HTTPException(status_code=403, detail="Invalid Master Key")
    return token

async def verify_chat_access(
    header: str = Security(api_key_header),
    session: Session = Depends(get_session)
):
    """MASTER_KEY hoặc Client Key đều được Chat"""
    token = get_token_from_header(header)

    # 1. Master Key (Root Access)
    if secrets.compare_digest(token, MASTER_KEY):
        return GatewayKey(key=MASTER_KEY, name="MASTER_ADMIN")

    # 2. Client Key (DB Access)
    key_record = session.get(GatewayKey, token)
    if not key_record or not key_record.is_active:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return key_record

# --- 4. APP LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan, title="AI Unified Gateway")

# --- 5. HELPER: DYNAMIC MODEL FETCHING (OpenAI Standard) ---
async def fetch_provider_models(client: httpx.AsyncClient, provider: Provider):
    """
    Gọi GET /v1/models của Provider để lấy danh sách model thực tế.
    Hỗ trợ: OpenAI, Azure, LocalAI, Ollama, vLLM, DeepSeek, Groq...
    """
    # Xử lý URL
    api_base = provider.base_url
    if not api_base:
        if provider.provider_type == "openai":
            api_base = "https://api.openai.com/v1"
        else:
            return [] # Không đoán URL của các hãng lạ

    api_base = api_base.rstrip('/')
    # Tự động thêm /v1 nếu thiếu (trừ khi user cố tình nhập url lạ)
    if not api_base.endswith("/v1") and "openai" in provider.provider_type:
         api_base = f"{api_base}/v1"

    url = f"{api_base}/models"
    headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}

    fetched_ids = []
    try:
        # Gọi API với timeout ngắn
        resp = await client.get(url, headers=headers, timeout=MODEL_FETCH_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    if "id" in item: fetched_ids.append(item["id"])
    except Exception:
        pass # Lỗi thì bỏ qua, trả về rỗng

    # Format về chuẩn Gateway: alias/model_id
    current_time = 1700000000
    return [{
        "id": f"{provider.name}/{m_id}",
        "object": "model",
        "created": current_time,
        "owned_by": provider.provider_type,
        "permission": []
    } for m_id in fetched_ids]

# --- 6. FRONTEND (UPDATED: HYBRID CSS) ---
html_panel = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <title>AI Gateway Panel</title>
    
    <script src="https://cdn.tailwindcss.com"></script>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" />

    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f3f4f6; margin: 0; padding-bottom: 80px; }
        
        /* Utility Classes giả lập Tailwind (đề phòng CDN chết) */
        .hidden { display: none !important; }
        .fixed { position: fixed; }
        .inset-0 { top: 0; right: 0; bottom: 0; left: 0; }
        .z-50 { z-index: 50; }
        .flex { display: flex; }
        .items-center { align-items: center; }
        .justify-center { justify-content: center; }
        .w-full { width: 100%; }
        .h-full { height: 100%; }
        
        /* Custom UI */
        .login-overlay { background-color: rgba(17, 24, 39, 0.95); }
        .card { background: white; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); padding: 20px; margin-bottom: 20px; border: 1px solid #e5e7eb; }
        .card-header { font-weight: bold; font-size: 1.125rem; margin-bottom: 1rem; display: flex; align-items: center; gap: 0.5rem; }
        
        /* Inputs & Buttons */
        input, select {
            width: 100%;
            padding: 12px;
            margin-top: 4px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 16px; /* Chặn zoom iOS */
            box-sizing: border-box;
            background-color: #fff;
        }
        input:focus, select:focus { outline: 2px solid #4f46e5; border-color: transparent; }
        
        .btn { width: 100%; padding: 12px; border-radius: 8px; font-weight: 600; cursor: pointer; border: none; transition: 0.2s; margin-top: 10px; }
        .btn-primary { background-color: #4f46e5; color: white; }
        .btn-primary:hover { background-color: #4338ca; }
        
        .btn-green { background-color: #059669; color: white; }
        .btn-green:hover { background-color: #047857; }
        
        .btn-icon { background: none; border: none; cursor: pointer; padding: 8px; }
        .text-red { color: #ef4444; }
        
        /* List Items */
        .list-item { background-color: #f9fafb; padding: 12px; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border: 1px solid #e5e7eb; }
        .list-title { font-weight: 700; color: #312e81; }
        .list-sub { font-size: 0.75rem; color: #6b7280; }

        /* Container */
        .container-custom { max-width: 800px; margin: 0 auto; padding: 20px; }
        .header-custom { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
    </style>
</head>
<body>

    <div id="loginModal" class="fixed inset-0 login-overlay z-50 flex items-center justify-center p-4 hidden">
        <div class="card w-full max-w-sm" style="text-align: center;">
            <div style="font-size: 3rem; color: #4f46e5; margin-bottom: 1rem;"><i class="fa-solid fa-shield-cat"></i></div>
            <h2 style="font-size: 1.5rem; font-weight: bold; margin-bottom: 0.5rem;">Gateway Login</h2>
            <p style="color: #6b7280; margin-bottom: 1.5rem;">Nhập Master Key</p>
            <form id="loginForm">
                <input type="password" id="masterKeyInput" placeholder="sk-..." required style="text-align: center;">
                <button type="submit" class="btn btn-primary">Truy cập Panel</button>
            </form>
        </div>
    </div>

    <div id="appContent" class="container-custom hidden">
        <header class="header-custom">
            <h1 style="font-size: 1.5rem; font-weight: bold; color: #374151; display: flex; align-items: center; gap: 10px;">
                <i class="fa-solid fa-network-wired" style="color: #4f46e5;"></i> AI Gateway
            </h1>
            <button onclick="logout()" style="background: none; border: none; color: #6b7280; cursor: pointer;">
                <i class="fa-solid fa-right-from-bracket"></i> Thoát
            </button>
        </header>

        <div class="card" style="border-top: 4px solid #4f46e5;">
            <div class="card-header" style="color: #4338ca;">
                <i class="fa-solid fa-server"></i> Thêm Provider
            </div>
            <form id="providerForm">
                <div style="margin-bottom: 10px;">
                    <label style="font-size: 0.75rem; font-weight: bold; color: #6b7280; text-transform: uppercase;">Alias (Tên ngắn)</label>
                    <input type="text" id="p_name" placeholder="vd: local, gpt" required>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="font-size: 0.75rem; font-weight: bold; color: #6b7280; text-transform: uppercase;">Loại API</label>
                    <select id="p_type" required>
                        <option value="openai">OpenAI Standard (Official/Compatible)</option>
                        <option value="azure">Azure OpenAI</option>
                    </select>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="font-size: 0.75rem; font-weight: bold; color: #6b7280; text-transform: uppercase;">Base URL (Tùy chọn)</label>
                    <input type="text" id="p_base" placeholder="http://host.docker.internal:11434">
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="font-size: 0.75rem; font-weight: bold; color: #6b7280; text-transform: uppercase;">API Key</label>
                    <input type="password" id="p_key" placeholder="sk-...">
                </div>
                <button type="submit" class="btn btn-primary"><i class="fa-solid fa-plus"></i> Lưu Provider</button>
            </form>
            
            <div id="providerList" style="margin-top: 20px;"></div>
        </div>

        <div class="card" style="border-top: 4px solid #059669;">
            <div class="card-header" style="color: #047857;">
                <i class="fa-solid fa-key"></i> Tạo Client Key
            </div>
            <form id="keyForm" style="display: flex; gap: 10px; margin-bottom: 15px;">
                <input type="text" id="k_name" placeholder="Tên App (vd: Cursor)" required style="margin-top: 0;">
                <button type="submit" class="btn btn-green" style="margin-top: 0; width: auto; padding: 0 20px;">+ Tạo</button>
            </form>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse; font-size: 0.875rem;">
                    <tbody id="keyList"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const MASTER_KEY_KEY = 'gw_master_key_v2';
        let currentKey = localStorage.getItem(MASTER_KEY_KEY);

        // --- AUTH ---
        function checkAuth() {
            if (!currentKey) {
                document.getElementById('loginModal').classList.remove('hidden');
                document.getElementById('appContent').classList.add('hidden');
            } else {
                document.getElementById('loginModal').classList.add('hidden');
                document.getElementById('appContent').classList.remove('hidden');
                initApp();
            }
        }
        document.getElementById('loginForm').onsubmit = (e) => {
            e.preventDefault();
            const val = document.getElementById('masterKeyInput').value.trim();
            if(val) { localStorage.setItem(MASTER_KEY_KEY, val); currentKey = val; checkAuth(); }
        }
        function logout() { localStorage.removeItem(MASTER_KEY_KEY); location.reload(); }

        // --- API ---
        async function api(path, method='GET', body=null) {
            const opts = { method, headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentKey}` }};
            if(body) opts.body = JSON.stringify(body);
            try {
                const res = await fetch(path, opts);
                if(res.status === 401 || res.status === 403) { logout(); return null; }
                return res.json();
            } catch(e) { alert("Lỗi kết nối!"); return null; }
        }

        // --- LOGIC ---
        async function loadData() {
            const [providers, keys] = await Promise.all([api('/api/admin/providers'), api('/api/admin/keys')]);
            
            if(providers) {
                document.getElementById('providerList').innerHTML = providers.map(p => `
                    <div class="list-item">
                        <div>
                            <div class="list-title">${p.name}</div>
                            <div class="list-sub">${p.base_url || 'Default OpenAI'}</div>
                        </div>
                        <button onclick="delProvider('${p.name}')" class="btn-icon text-red"><i class="fa-solid fa-trash"></i></button>
                    </div>
                `).join('');
            }
            if(keys) {
                document.getElementById('keyList').innerHTML = keys.map(k => `
                    <tr style="border-bottom: 1px solid #f3f4f6;">
                        <td style="padding: 10px; font-weight: 500;">${k.name}</td>
                        <td style="padding: 10px; color: #2563eb; font-family: monospace; cursor: pointer;" onclick="copy('${k.key}')">Copy Key</td>
                        <td style="padding: 10px; text-align: right;"><button onclick="delKey('${k.key}')" class="btn-icon text-red"><i class="fa-solid fa-trash"></i></button></td>
                    </tr>
                `).join('');
            }
        }

        document.getElementById('providerForm').onsubmit = async (e) => {
            e.preventDefault();
            await api('/api/admin/providers', 'POST', {
                name: document.getElementById('p_name').value,
                provider_type: document.getElementById('p_type').value,
                api_key: document.getElementById('p_key').value || "sk-dummy",
                base_url: document.getElementById('p_base').value || null
            });
            e.target.reset(); loadData();
        };

        document.getElementById('keyForm').onsubmit = async (e) => {
            e.preventDefault();
            const res = await api('/api/admin/keys', 'POST', { name: document.getElementById('k_name').value });
            if(res) { prompt("Copy Client Key:", res.key); e.target.reset(); loadData(); }
        };

        async function delProvider(n) { if(confirm('Xóa?')) { await api(`/api/admin/providers/${n}`, 'DELETE'); loadData(); }}
        async function delKey(k) { if(confirm('Xóa?')) { await api(`/api/admin/keys/${k}`, 'DELETE'); loadData(); }}
        function copy(t) { navigator.clipboard.writeText(t); alert("Đã copy!"); }
        function initApp() { loadData(); }

        checkAuth();
    </script>
</body>
</html>
"""

# --- 7. ROUTES & API ENDPOINTS ---

@app.get("/")
async def root():
    return RedirectResponse(url="/panel")

@app.get("/panel", response_class=HTMLResponse)
async def panel():
    return html_panel

# --- ADMIN API (Protected by Master Key) ---
@app.post("/api/admin/providers", dependencies=[Depends(verify_admin)])
async def create_provider(provider: Provider, session: Session = Depends(get_session)):
    session.merge(provider)
    session.commit()
    return {"status": "ok"}

@app.get("/api/admin/providers", dependencies=[Depends(verify_admin)])
async def list_providers(session: Session = Depends(get_session)):
    return session.exec(select(Provider)).all()

@app.delete("/api/admin/providers/{name}", dependencies=[Depends(verify_admin)])
async def delete_provider(name: str, session: Session = Depends(get_session)):
    p = session.get(Provider, name)
    if p: session.delete(p); session.commit()
    return {"status": "ok"}

class KeyCreate(BaseModel):
    name: str

@app.post("/api/admin/keys", dependencies=[Depends(verify_admin)])
async def create_key(data: KeyCreate, session: Session = Depends(get_session)):
    new_key = f"sk-gw-{secrets.token_hex(16)}"
    db_key = GatewayKey(key=new_key, name=data.name)
    session.add(db_key); session.commit()
    return db_key

@app.get("/api/admin/keys", dependencies=[Depends(verify_admin)])
async def list_keys(session: Session = Depends(get_session)):
    return session.exec(select(GatewayKey)).all()

@app.delete("/api/admin/keys/{key}", dependencies=[Depends(verify_admin)])
async def delete_key(key: str, session: Session = Depends(get_session)):
    k = session.get(GatewayKey, key)
    if k: session.delete(k); session.commit()
    return {"status": "ok"}

# --- PUBLIC API: LIST MODELS (Parallel Dynamic Fetch) ---
@app.get("/v1/models")
async def list_models(
    key: GatewayKey = Depends(verify_chat_access),
    session: Session = Depends(get_session)
):
    providers = session.exec(select(Provider)).all()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in providers]
        results = await asyncio.gather(*tasks)
    
    all_models = [m for sub in results for m in sub]
    all_models.sort(key=lambda x: x["id"])
    return {"object": "list", "data": all_models}

# --- PUBLIC API: CHAT COMPLETIONS (The Core) ---
class ChatRequest(BaseModel):
    model: str
    messages: List[dict]
    stream: Optional[bool] = False
    class Config:
        extra = "allow"

@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    key_info: GatewayKey = Depends(verify_chat_access),
    session: Session = Depends(get_session)
):
    try:
        body = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # 1. Routing: alias/model
    raw_model = body.get("model", "")
    if "/" not in raw_model:
         raise HTTPException(status_code=400, detail="Model format must be: provider_alias/model_name")
    
    alias, actual_model = raw_model.split("/", 1)
    provider = session.get(Provider, alias)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Provider '{alias}' not found")

    del body["model"]

    # 2. Setup LiteLLM parameters
    # Lưu ý: LiteLLM hỗ trợ custom base_url thông qua tham số api_base
    kwargs = {
        "model": actual_model, # Chỉ truyền tên model thật (vd: llama3)
        "messages": body.get("messages"),
        "api_key": provider.api_key,
        "metadata": {"user": key_info.name},
        **body
    }

    # SUPPORT CUSTOM API: Truyền Base URL vào LiteLLM
    if provider.base_url:
        kwargs["api_base"] = provider.base_url
        kwargs["custom_llm_provider"] = "openai" # Ép kiểu về OpenAI generic

    # 3. Execute
    try:
        if body.get("stream", False):
            async def stream_gen():
                resp = await acompletion(**kwargs)
                async for chunk in resp:
                    yield f"data: {chunk.json()}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(stream_gen(), media_type="text/event-stream")
        else:
            resp = await acompletion(**kwargs)
            return JSONResponse(content=resp.json())
    except Exception as e:
        print(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
