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

# --- 6. FRONTEND (NATIVE CSS - NO TAILWIND DEPENDENCY) ---
html_panel = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <title>AI Gateway Admin</title>
    
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />

    <style>
        /* --- RESET & BASE --- */
        :root {
            --primary: #4f46e5; /* Indigo 600 */
            --primary-hover: #4338ca;
            --danger: #ef4444;
            --success: #10b981;
            --bg: #f3f4f6;
            --card-bg: #ffffff;
            --text-main: #1f2937;
            --text-muted: #6b7280;
            --border: #e5e7eb;
        }
        
        * { box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 0;
            padding-bottom: 50px;
            font-size: 16px; /* Chuẩn mobile */
        }

        /* --- UTILS --- */
        .hidden { display: none !important; }
        .container { max-width: 800px; margin: 0 auto; padding: 20px; }
        .flex { display: flex; align-items: center; }
        .justify-between { justify-content: space-between; }
        .gap-2 { gap: 0.5rem; }
        .mt-4 { margin-top: 1rem; }
        .text-xs { font-size: 0.75rem; }
        .font-bold { font-weight: 700; }
        .uppercase { text-transform: uppercase; }

        /* --- COMPONENTS --- */
        /* Header */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 2px solid var(--border);
        }
        h1 { margin: 0; font-size: 1.5rem; color: var(--primary); }
        .logout-btn { color: var(--danger); text-decoration: none; font-size: 0.9rem; border: none; background: none; cursor: pointer; }

        /* Card */
        .card {
            background: var(--card-bg);
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid var(--border);
        }
        .card-title {
            font-size: 1.1rem;
            font-weight: bold;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        /* Forms */
        .form-group { margin-bottom: 12px; }
        label { display: block; font-size: 0.75rem; font-weight: bold; color: var(--text-muted); text-transform: uppercase; margin-bottom: 4px; }
        
        input, select {
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--border);
            border-radius: 6px;
            font-size: 16px; /* iOS không zoom */
            background: #fff;
            transition: border 0.2s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
        }

        /* Buttons */
        .btn {
            display: inline-flex;
            justify-content: center;
            align-items: center;
            padding: 10px 16px;
            border-radius: 6px;
            font-weight: 600;
            border: none;
            cursor: pointer;
            width: 100%;
            transition: background 0.2s;
        }
        .btn-primary { background: var(--primary); color: white; }
        .btn-primary:hover { background: var(--primary-hover); }
        .btn-green { background: var(--success); color: white; width: auto; }
        
        .btn-icon {
            background: none; border: none; padding: 5px; cursor: pointer; color: var(--text-muted);
        }
        .btn-icon:hover { color: var(--danger); }

        /* List Items */
        .list-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f9fafb;
            padding: 10px;
            border-radius: 8px;
            border: 1px solid var(--border);
            margin-bottom: 8px;
        }
        .item-main { font-weight: 600; color: #111827; }
        .item-sub { font-size: 0.8rem; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 200px; }

        /* Table */
        table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
        td { padding: 10px; border-bottom: 1px solid var(--border); }
        .key-copy { 
            font-family: monospace; color: var(--primary); cursor: pointer; background: #eef2ff; padding: 2px 6px; border-radius: 4px;
        }

        /* Modal */
        .modal-overlay {
            position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.8);
            display: flex; justify-content: center; align-items: center;
            z-index: 1000;
        }
        .modal-box {
            background: white; padding: 30px; border-radius: 16px; width: 90%; max-width: 350px; text-align: center;
        }
    </style>
</head>
<body>

    <div id="loginModal" class="modal-overlay hidden">
        <div class="modal-box">
            <div style="font-size: 40px; color: var(--primary); margin-bottom: 10px;"><i class="fa-solid fa-shield-cat"></i></div>
            <h2 style="font-size: 20px; font-weight: bold;">Admin Login</h2>
            <p style="color: #666; margin-bottom: 20px; font-size: 14px;">Nhập MASTER_KEY của server</p>
            <form id="loginForm">
                <input type="password" id="masterKeyInput" placeholder="sk-..." required style="text-align: center; margin-bottom: 15px;">
                <button type="submit" class="btn btn-primary">Đăng Nhập</button>
            </form>
        </div>
    </div>

    <div id="appContent" class="container hidden">
        <header>
            <h1><i class="fa-solid fa-layer-group"></i> AI Gateway</h1>
            <button onclick="logout()" class="logout-btn"><i class="fa-solid fa-right-from-bracket"></i> Thoát</button>
        </header>

        <div class="card" style="border-top: 4px solid var(--primary);">
            <div class="card-title" style="color: var(--primary);">
                <i class="fa-solid fa-server"></i> Cấu hình Provider
            </div>
            <form id="providerForm">
                <div class="form-group">
                    <label>Alias (Tên ngắn gọi API)</label>
                    <input type="text" id="p_name" placeholder="Ví dụ: gpt, local, deepseek" required>
                </div>
                <div class="form-group">
                    <label>Loại API</label>
                    <select id="p_type" required>
                        <option value="openai">OpenAI Standard (Khuyên dùng)</option>
                        <option value="azure">Azure OpenAI</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Base URL (Bắt buộc cho Local/Ollama)</label>
                    <input type="text" id="p_base" placeholder="http://localhost:11434">
                    <p class="text-xs" style="color: #888; margin-top: 4px;">* OpenAI Official thì để trống.</p>
                </div>
                <div class="form-group">
                    <label>API Key</label>
                    <input type="password" id="p_key" placeholder="sk-...">
                </div>
                <button type="submit" class="btn btn-primary"><i class="fa-solid fa-save"></i> Lưu Cấu Hình</button>
            </form>
            
            <div id="providerList" class="mt-4"></div>
        </div>

        <div class="card" style="border-top: 4px solid var(--success);">
            <div class="card-title" style="color: var(--success);">
                <i class="fa-solid fa-key"></i> Tạo Key cho Ứng dụng
            </div>
            <form id="keyForm" style="display: flex; gap: 10px; margin-bottom: 15px;">
                <input type="text" id="k_name" placeholder="Tên App (VD: Cursor, Web)" required style="margin-bottom: 0;">
                <button type="submit" class="btn btn-green"><i class="fa-solid fa-plus"></i></button>
            </form>
            
            <div style="overflow-x: auto;">
                <table>
                    <tbody id="keyList"></tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        const MASTER_KEY_KEY = 'gw_master_key_v2';
        let currentKey = localStorage.getItem(MASTER_KEY_KEY);

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

        async function api(path, method='GET', body=null) {
            const opts = { method, headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentKey}` }};
            if(body) opts.body = JSON.stringify(body);
            try {
                const res = await fetch(path, opts);
                if(res.status === 401 || res.status === 403) { logout(); return null; }
                return res.json();
            } catch(e) { alert("Lỗi kết nối server!"); return null; }
        }

        async function loadData() {
            const [providers, keys] = await Promise.all([api('/api/admin/providers'), api('/api/admin/keys')]);
            
            if(providers) {
                document.getElementById('providerList').innerHTML = providers.map(p => `
                    <div class="list-item">
                        <div>
                            <div class="item-main">${p.name}</div>
                            <div class="item-sub">${p.base_url || 'OpenAI Official'}</div>
                        </div>
                        <button onclick="delProvider('${p.name}')" class="btn-icon"><i class="fa-solid fa-trash"></i></button>
                    </div>
                `).join('');
            }
            if(keys) {
                document.getElementById('keyList').innerHTML = keys.map(k => `
                    <tr>
                        <td><b>${k.name}</b></td>
                        <td style="text-align:center;"><span class="key-copy" onclick="copy('${k.key}')">COPY KEY</span></td>
                        <td style="text-align:right;"><button onclick="delKey('${k.key}')" class="btn-icon" style="color:#ef4444;"><i class="fa-solid fa-trash"></i></button></td>
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
            if(res) { prompt("Copy Client Key của bạn:", res.key); e.target.reset(); loadData(); }
        };

        async function delProvider(n) { if(confirm('Xóa Provider này?')) { await api(`/api/admin/providers/${n}`, 'DELETE'); loadData(); }}
        async function delKey(k) { if(confirm('Thu hồi Key này?')) { await api(`/api/admin/keys/${k}`, 'DELETE'); loadData(); }}
        function copy(t) { navigator.clipboard.writeText(t); alert("Đã copy vào clipboard!"); }
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
