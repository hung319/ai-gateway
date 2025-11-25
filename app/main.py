import os
import secrets
import asyncio
import json
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends, Security, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from sqlmodel import Field, Session, SQLModel, create_engine, select
from pydantic import BaseModel
from litellm import acompletion, image_generation, speech, transcription

# --- 1. CONFIGURATION ---
DB_PATH = os.getenv("DB_PATH", "gateway.db")
MASTER_KEY = os.getenv("MASTER_KEY", "sk-master-secret-123") 
MODEL_FETCH_TIMEOUT = 10.0
MASTER_TRACKER_ID = "MASTER_ADMIN_TRACKER"

sqlite_url = f"sqlite:///{DB_PATH}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# --- 2. DATABASE MODELS ---
class Provider(SQLModel, table=True):
    name: str = Field(primary_key=True, index=True) 
    api_key: str
    base_url: Optional[str] = None 
    provider_type: str = "openai" 

class GatewayKey(SQLModel, table=True):
    key: str = Field(primary_key=True, index=True)
    name: str = Field(default="Client App")
    usage_count: int = Field(default=0)
    is_active: bool = Field(default=True)
    is_hidden: bool = Field(default=False)

# MỚI: Bảng lưu cấu hình MCP
class MCPServer(SQLModel, table=True):
    name: str = Field(primary_key=True, index=True) # VD: filesystem, github
    command: str # VD: npx, python, uv
    args: str # VD: -y @modelcontextprotocol/server-filesystem /Users/me
    env_vars: Optional[str] = None # JSON string lưu biến môi trường
    description: Optional[str] = None

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if not session.get(GatewayKey, MASTER_TRACKER_ID):
            session.add(GatewayKey(key=MASTER_TRACKER_ID, name="👑 ADMIN TRACKER", usage_count=0, is_hidden=True))
            session.commit()

def get_session():
    with Session(engine) as session:
        yield session

# --- 3. AUTH LOGIC ---
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

def get_token_from_header(header: str) -> str:
    if not header: raise HTTPException(401, "Missing Authorization Header")
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer": raise HTTPException(401, "Invalid Format")
    return parts[1]

async def verify_admin(header: str = Security(api_key_header)):
    token = get_token_from_header(header)
    if not secrets.compare_digest(token, MASTER_KEY): raise HTTPException(403, "Invalid Master Key")
    return token

async def verify_usage_access(header: str = Security(api_key_header), session: Session = Depends(get_session)):
    token = get_token_from_header(header)
    if secrets.compare_digest(token, MASTER_KEY):
        key_record = session.get(GatewayKey, MASTER_TRACKER_ID)
    else:
        key_record = session.get(GatewayKey, token)
    
    if not key_record or not key_record.is_active: raise HTTPException(401, "Invalid API Key")
    
    key_record.usage_count += 1
    session.add(key_record); session.commit(); session.refresh(key_record)
    return key_record

# --- 4. LIFECYCLE ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield

app = FastAPI(lifespan=lifespan, title="AI Gateway v2.8 MCP")

# --- 5. HELPER ---
async def fetch_provider_models(client: httpx.AsyncClient, provider: Provider):
    api_base = provider.base_url
    if not api_base:
        if provider.provider_type == "openrouter": api_base = "https://openrouter.ai/api/v1"
        elif provider.provider_type == "openai": api_base = "https://api.openai.com/v1"
        else: return []

    api_base = api_base.rstrip('/')
    if not api_base.endswith("/v1") and ("openai" in provider.provider_type or "openrouter" in provider.provider_type):
         api_base = f"{api_base}/v1"

    url = f"{api_base}/models"
    headers = {"Authorization": f"Bearer {provider.api_key}", "Content-Type": "application/json"}
    if provider.provider_type == "openrouter": headers["HTTP-Referer"] = "gateway"; headers["X-Title"] = "AI Gateway"

    fetched_ids = []
    try:
        resp = await client.get(url, headers=headers, timeout=MODEL_FETCH_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data and isinstance(data["data"], list):
                for item in data["data"]:
                    if "id" in item: fetched_ids.append(item["id"])
    except: pass

    return [{"id": f"{provider.name}/{m_id}", "object": "model", "created": 1700000000, "owned_by": provider.provider_type, "permission": []} for m_id in fetched_ids]

def parse_model_alias(raw_model: str, session: Session):
    if "/" not in raw_model: raise HTTPException(400, "Format: provider_alias/model_name")
    alias, actual_model = raw_model.split("/", 1)
    provider = session.get(Provider, alias)
    if not provider: raise HTTPException(404, f"Provider '{alias}' not found")
    return provider, actual_model

# --- 6. FRONTEND (MCP UPDATE) ---
html_panel = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <title>AI Gateway Admin</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    <style>
        :root { --primary: #4f46e5; --bg: #f3f4f6; --text: #1f2937; --border: #e5e7eb; }
        body { font-family: sans-serif; background: var(--bg); color: var(--text); margin: 0; padding-bottom: 50px; font-size: 16px; }
        * { box-sizing: border-box; }
        .hidden { display: none !important; }
        .container { max-width: 800px; margin: 0 auto; padding: 20px; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 2px solid #ddd; padding-bottom: 10px; overflow-x: auto; }
        .tab-btn { background: none; border: none; font-size: 1rem; font-weight: bold; color: #6b7280; padding: 10px 15px; cursor: pointer; border-radius: 6px; white-space: nowrap; }
        .tab-btn.active { background: #eef2ff; color: var(--primary); }
        .card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; border: 1px solid var(--border); box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
        .card-title { font-weight: bold; margin-bottom: 15px; display: flex; gap: 10px; align-items: center; font-size: 1.1rem; }
        input, select, textarea { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 6px; margin-top: 5px; font-size: 16px; margin-bottom: 15px; font-family: inherit; }
        textarea { resize: vertical; min-height: 80px; font-family: monospace; font-size: 0.9rem; }
        label { font-size: 0.75rem; font-weight: bold; color: #6b7280; text-transform: uppercase; }
        .btn { width: 100%; padding: 12px; border: none; border-radius: 6px; font-weight: bold; color: white; cursor: pointer; }
        .btn-primary { background: var(--primary); }
        .btn-dark { background: #1f2937; }
        .btn-danger { background: #ef4444; width: auto; padding: 6px 10px; font-size: 0.8rem; }
        .badge { background: #e0e7ff; color: var(--primary); padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 0.85rem; }
        .badge-master { background: #fef3c7; color: #d97706; font-weight: bold; }
        .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: flex; justify-content: center; align-items: center; z-index: 99; }
        .modal-box { background: white; padding: 30px; border-radius: 12px; width: 90%; max-width: 350px; text-align: center; }
        .code-block { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 6px; overflow-x: auto; font-family: monospace; font-size: 0.85rem; margin-top: 10px; }
    </style>
</head>
<body>
    <div id="loginModal" class="modal-overlay hidden">
        <div class="modal-box">
            <h2 style="margin-top:0">Gateway Login</h2>
            <form id="loginForm"><input type="password" id="masterKeyInput" placeholder="Enter MASTER_KEY" required style="text-align:center"><button class="btn btn-primary">Login</button></form>
        </div>
    </div>
    <div id="appContent" class="container hidden">
        <header style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
            <h1 style="margin:0; color:var(--primary);"><i class="fa-solid fa-layer-group"></i> AI Gateway</h1>
            <button onclick="logout()" style="border:none; background:none; color:#ef4444; cursor:pointer;">Logout</button>
        </header>
        
        <div class="tabs">
            <button class="tab-btn active" onclick="switchTab('config')" id="tab-config"><i class="fa-solid fa-gears"></i> Cấu Hình</button>
            <button class="tab-btn" onclick="switchTab('mcp')" id="tab-mcp"><i class="fa-solid fa-diagram-project"></i> MCP Ecosystem</button>
            <button class="tab-btn" onclick="switchTab('stats')" id="tab-stats"><i class="fa-solid fa-chart-simple"></i> Thống Kê</button>
        </div>

        <div id="view-config">
            <div class="card" style="border-top: 4px solid var(--primary);">
                <div class="card-title" style="color:var(--primary)"><i class="fa-solid fa-server"></i> Thêm Provider</div>
                <form id="providerForm">
                    <label>Alias (Tên gọi)</label><input type="text" id="p_name" placeholder="vd: open, gpt" required>
                    <label>Loại API</label>
                    <select id="p_type" onchange="autoFillBaseUrl()" required>
                        <option value="openai">OpenAI Standard</option>
                        <option value="openrouter">OpenRouter</option>
                        <option value="azure">Azure OpenAI</option>
                    </select>
                    <label>Base URL</label><input type="text" id="p_base" placeholder="Auto fill...">
                    <label>API Key</label><input type="password" id="p_key" placeholder="sk-...">
                    <button class="btn btn-primary">Lưu Provider</button>
                </form>
                <div id="providerList" style="margin-top:20px;"></div>
            </div>
            <div class="card" style="border-top: 4px solid #10b981;">
                <div class="card-title" style="color:#059669"><i class="fa-solid fa-plus-circle"></i> Tạo Client Key</div>
                <form id="createKeyForm">
                    <label>Tên Ứng Dụng</label><input type="text" id="k_name" placeholder="vd: Web Chat" required>
                    <label>Custom API Key</label><input type="text" id="k_custom" placeholder="Optional">
                    <button class="btn" style="background:#10b981">Tạo Key</button>
                </form>
            </div>
        </div>

        <div id="view-mcp" class="hidden">
            <div class="card" style="border-top: 4px solid #8b5cf6;">
                <div class="card-title" style="color:#7c3aed"><i class="fa-solid fa-plug"></i> Quản lý MCP Servers</div>
                <p style="font-size:0.85rem; color:#666; margin-bottom:15px;">Khai báo các MCP Servers tại đây để tạo file cấu hình cho Claude/Cursor.</p>
                
                <form id="mcpForm">
                    <label>Server Name</label><input type="text" id="m_name" placeholder="vd: filesystem, github" required>
                    <label>Command (Lệnh chạy)</label><input type="text" id="m_command" placeholder="vd: npx, uvx, python" required>
                    <label>Arguments (Tham số)</label><input type="text" id="m_args" placeholder="vd: -y @modelcontextprotocol/server-filesystem /path/to/allow">
                    <label>Environment Variables (JSON)</label>
                    <textarea id="m_env" placeholder='{"GITHUB_TOKEN": "..."}'></textarea>
                    <button class="btn" style="background:#8b5cf6">Lưu MCP Server</button>
                </form>
                
                <div id="mcpList" style="margin-top:20px;"></div>
            </div>

            <div class="card">
                <div class="card-title"><i class="fa-solid fa-file-code"></i> Export Config</div>
                <p style="font-size:0.85rem; color:#666;">Copy nội dung này vào file <code>claude_desktop_config.json</code> hoặc cấu hình Cursor của bạn.</p>
                <div id="mcpExport" class="code-block">Chưa có dữ liệu...</div>
                <button onclick="copyConfig()" class="btn btn-dark" style="margin-top:10px;"><i class="fa-regular fa-copy"></i> Copy JSON</button>
            </div>
        </div>

        <div id="view-stats" class="hidden">
            <div class="card">
                <div class="card-title"><i class="fa-solid fa-list"></i> Danh Sách Key</div>
                <div style="overflow-x:auto"><table><thead><tr><th>Tên</th><th>Key</th><th>Dùng</th><th>#</th></tr></thead><tbody id="statsList"></tbody></table></div>
            </div>
        </div>
    </div>

    <script>
        const MASTER_KEY_KEY = 'gw_master_key_v2';
        let currentKey = localStorage.getItem(MASTER_KEY_KEY);

        // Auto Fill
        function autoFillBaseUrl() {
            const t = document.getElementById('p_type').value;
            const b = document.getElementById('p_base');
            if(t==='openrouter') b.value='https://openrouter.ai/api/v1';
            else if(t==='openai') b.value='';
        }

        function switchTab(t) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('[id^=view-]').forEach(v => v.classList.add('hidden'));
            document.getElementById(`view-${t}`).classList.remove('hidden');
            document.getElementById(`tab-${t}`).classList.add('active');
            if(t==='stats') loadKeys();
            if(t==='mcp') loadMCP();
        }

        // Auth
        function checkAuth() {
            if (!currentKey) { document.getElementById('loginModal').classList.remove('hidden'); document.getElementById('appContent').classList.add('hidden'); }
            else { document.getElementById('loginModal').classList.add('hidden'); document.getElementById('appContent').classList.remove('hidden'); initApp(); }
        }
        document.getElementById('loginForm').onsubmit = (e) => { e.preventDefault(); const val = document.getElementById('masterKeyInput').value.trim(); if(val) { localStorage.setItem(MASTER_KEY_KEY, val); currentKey = val; checkAuth(); }}
        function logout() { localStorage.removeItem(MASTER_KEY_KEY); location.reload(); }

        // API
        async function api(path, method='GET', body=null) {
            const opts = { method, headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentKey}` }};
            if(body) opts.body = JSON.stringify(body);
            try { const res = await fetch(path, opts); if(res.status===401||res.status===403){logout();return null;} if(!res.ok){alert((await res.json()).detail);return null;} return res.json(); } catch(e){alert("Error");return null;}
        }

        // LOADERS
        async function loadProviders() {
            const ps = await api('/api/admin/providers');
            if(ps) document.getElementById('providerList').innerHTML = ps.map(p => `<div style="background:#f9fafb; padding:10px; border:1px solid #eee; border-radius:6px; margin-bottom:5px; display:flex; justify-content:space-between; align-items:center;"><div><div style="font-weight:bold; color:#374151">${p.name}</div><div style="font-size:0.8rem; color:#6b7280">${p.base_url||'Default'} (${p.provider_type})</div></div><button onclick="delProvider('${p.name}')" style="border:none; background:none; color:#ef4444; cursor:pointer;"><i class="fa-solid fa-trash"></i></button></div>`).join('');
        }
        async function loadKeys() {
            const ks = await api('/api/admin/keys');
            if(ks) {
                ks.sort((a,b) => b.is_hidden - a.is_hidden);
                document.getElementById('statsList').innerHTML = ks.map(k => `<tr><td style="font-weight:bold">${k.name}</td><td>${k.is_hidden?'<span class="badge badge-master">MASTER</span>':`<span class="badge" onclick="copy('${k.key}')" style="cursor:pointer">${k.key}</span>`}</td><td style="text-align:center;font-weight:bold">${k.usage_count}</td><td style="text-align:right">${!k.is_hidden?`<button onclick="delKey('${k.key}')" class="btn-danger"><i class="fa-solid fa-trash"></i></button>`:''}</td></tr>`).join('');
            }
        }
        
        // MCP LOGIC
        async function loadMCP() {
            const servers = await api('/api/admin/mcp');
            if(!servers) return;
            
            // Render List
            document.getElementById('mcpList').innerHTML = servers.map(s => `
                <div style="background:#f5f3ff; padding:10px; border:1px solid #ddd6fe; border-radius:6px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <div style="font-weight:bold; color:#5b21b6">${s.name}</div>
                        <button onclick="delMCP('${s.name}')" style="border:none; background:none; color:#ef4444; cursor:pointer;"><i class="fa-solid fa-trash"></i></button>
                    </div>
                    <div style="font-family:monospace; font-size:0.8rem; color:#4b5563; margin-top:5px; word-break:break-all;">
                        <span style="color:#7c3aed">${s.command}</span> ${s.args}
                    </div>
                </div>
            `).join('');

            // Generate Config JSON
            const mcpConfig = { mcpServers: {} };
            servers.forEach(s => {
                mcpConfig.mcpServers[s.name] = {
                    command: s.command,
                    args: s.args.split(' ').filter(a => a.trim() !== ''),
                    env: s.env_vars ? JSON.parse(s.env_vars) : undefined
                };
            });
            document.getElementById('mcpExport').textContent = JSON.stringify(mcpConfig, null, 2);
        }

        // HANDLERS
        document.getElementById('providerForm').onsubmit = async (e) => { e.preventDefault(); await api('/api/admin/providers', 'POST', { name: document.getElementById('p_name').value, provider_type: document.getElementById('p_type').value, api_key: document.getElementById('p_key').value||"sk-dummy", base_url: document.getElementById('p_base').value||null }); e.target.reset(); loadProviders(); };
        document.getElementById('createKeyForm').onsubmit = async (e) => { e.preventDefault(); const res=await api('/api/admin/keys', 'POST', { name: document.getElementById('k_name').value, custom_key: document.getElementById('k_custom').value.trim()||null }); if(res){alert(`Key: ${res.key}`);e.target.reset();switchTab('stats');} };
        
        document.getElementById('mcpForm').onsubmit = async (e) => {
            e.preventDefault();
            const envRaw = document.getElementById('m_env').value.trim();
            // Validate JSON
            if(envRaw) { try { JSON.parse(envRaw); } catch { alert("Environment Variables phải là JSON hợp lệ!"); return; } }
            
            await api('/api/admin/mcp', 'POST', {
                name: document.getElementById('m_name').value,
                command: document.getElementById('m_command').value,
                args: document.getElementById('m_args').value,
                env_vars: envRaw || null
            });
            e.target.reset(); loadMCP();
        };

        async function delProvider(n) { if(confirm('Xóa?')) { await api(`/api/admin/providers/${n}`, 'DELETE'); loadProviders(); }}
        async function delKey(k) { if(confirm('Xóa?')) { await api(`/api/admin/keys/${k}`, 'DELETE'); loadKeys(); }}
        async function delMCP(n) { if(confirm('Xóa MCP này?')) { await api(`/api/admin/mcp/${n}`, 'DELETE'); loadMCP(); }}
        
        function copy(t) { navigator.clipboard.writeText(t); alert("Copied!"); }
        function copyConfig() { navigator.clipboard.writeText(document.getElementById('mcpExport').textContent); alert("Đã copy JSON Config!"); }
        
        function initApp() { loadProviders(); loadKeys(); }
        checkAuth();
    </script>
</body>
</html>
"""

# --- 7. ROUTES ---
@app.get("/")
async def root(): return RedirectResponse(url="/panel")
@app.get("/panel", response_class=HTMLResponse)
async def panel(): return html_panel

# --- MCP API ---
class MCPRequest(BaseModel): name: str; command: str; args: str; env_vars: Optional[str]=None
@app.post("/api/admin/mcp", dependencies=[Depends(verify_admin)])
async def create_mcp(d: MCPRequest, s: Session = Depends(get_session)):
    s.merge(MCPServer(**d.dict())); s.commit(); return {"status":"ok"}
@app.get("/api/admin/mcp", dependencies=[Depends(verify_admin)])
async def list_mcp(s: Session = Depends(get_session)): return s.exec(select(MCPServer)).all()
@app.delete("/api/admin/mcp/{name}", dependencies=[Depends(verify_admin)])
async def delete_mcp(name: str, s: Session = Depends(get_session)):
    obj=s.get(MCPServer,name); (s.delete(obj), s.commit()) if obj else None; return {"status":"ok"}

# --- OTHER CRUD ---
@app.post("/api/admin/providers", dependencies=[Depends(verify_admin)])
async def create_provider(p: Provider, s: Session = Depends(get_session)): s.merge(p); s.commit(); return {"status": "ok"}
@app.get("/api/admin/providers", dependencies=[Depends(verify_admin)])
async def list_providers(s: Session = Depends(get_session)): return s.exec(select(Provider)).all()
@app.delete("/api/admin/providers/{name}", dependencies=[Depends(verify_admin)])
async def delete_provider(name: str, s: Session = Depends(get_session)): p=s.get(Provider,name); (s.delete(p),s.commit()) if p else None; return {"status": "ok"}
class KeyCreateRequest(BaseModel): name: str; custom_key: Optional[str]=None
@app.post("/api/admin/keys", dependencies=[Depends(verify_admin)])
async def create_key(d: KeyCreateRequest, s: Session = Depends(get_session)):
    k = d.custom_key if d.custom_key else f"sk-gw-{secrets.token_hex(16)}"
    if s.get(GatewayKey, k): raise HTTPException(400, "Exists")
    db_k = GatewayKey(key=k, name=d.name); s.add(db_k); s.commit(); return db_k
@app.get("/api/admin/keys", dependencies=[Depends(verify_admin)])
async def list_keys(s: Session = Depends(get_session)): return s.exec(select(GatewayKey)).all()
@app.delete("/api/admin/keys/{key}", dependencies=[Depends(verify_admin)])
async def delete_key(key: str, s: Session = Depends(get_session)): k=s.get(GatewayKey,key); (s.delete(k),s.commit()) if k and not k.is_hidden else None; return {"status": "ok"}

# --- AI ENDPOINTS ---
@app.get("/v1/models")
async def list_models(k: GatewayKey=Depends(verify_usage_access), s: Session=Depends(get_session)):
    providers = s.exec(select(Provider)).all()
    async with httpx.AsyncClient() as client:
        tasks = [fetch_provider_models(client, p) for p in providers]
        results = await asyncio.gather(*tasks)
    all_models = [m for sub in results for m in sub]
    all_models.sort(key=lambda x: x["id"])
    return {"object": "list", "data": all_models}

@app.post("/v1/chat/completions")
async def chat_completions(req: Request, k: GatewayKey=Depends(verify_usage_access), s: Session=Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "JSON")
    provider, actual_model = parse_model_alias(body.get("model", ""), s)
    del body["model"]
    kwargs = {"model": actual_model, "messages": body.get("messages"), "api_key": provider.api_key, "metadata": {"user": k.name}, **body}
    if provider.base_url: kwargs["api_base"] = provider.base_url; kwargs["custom_llm_provider"] = "openai"
    try:
        if body.get("stream", False):
            async def gen():
                r = await acompletion(**kwargs)
                async for c in r: yield f"data: {c.json()}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream")
        else: return JSONResponse((await acompletion(**kwargs)).json())
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/v1/images/generations")
async def image_gen(req: Request, k: GatewayKey=Depends(verify_usage_access), s: Session=Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "JSON")
    provider, actual_model = parse_model_alias(body.get("model", ""), s)
    try:
        res = await image_generation(model=actual_model, prompt=body.get("prompt"), api_key=provider.api_key, api_base=provider.base_url, n=body.get("n",1), size=body.get("size","1024x1024"))
        return JSONResponse(res.json())
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/v1/videos/generations")
async def video_gen(req: Request, k: GatewayKey=Depends(verify_usage_access), s: Session=Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "JSON")
    provider, actual_model = parse_model_alias(body.get("model", ""), s)
    try:
        res = await image_generation(model=actual_model, prompt=body.get("prompt"), api_key=provider.api_key, api_base=provider.base_url, n=1)
        return JSONResponse(res.json())
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/v1/audio/speech")
async def tts(req: Request, k: GatewayKey=Depends(verify_usage_access), s: Session=Depends(get_session)):
    try: body = await req.json()
    except: raise HTTPException(400, "JSON")
    provider, actual_model = parse_model_alias(body.get("model", ""), s)
    try:
        res = await speech(model=actual_model, input=body.get("input"), voice=body.get("voice","alloy"), api_key=provider.api_key, api_base=provider.base_url)
        return StreamingResponse(res.iter_content(chunk_size=1024), media_type="audio/mpeg")
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/v1/audio/transcriptions")
async def stt(model: str=Form(...), file: UploadFile=File(...), k: GatewayKey=Depends(verify_usage_access), s: Session=Depends(get_session)):
    provider, actual_model = parse_model_alias(model, s)
    try:
        res = await transcription(model=actual_model, file=file.file, api_key=provider.api_key, api_base=provider.base_url)
        return JSONResponse(res.json())
    except Exception as e: raise HTTPException(500, str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
