const KEY='gw_v5_final_clean'; 

// --- 1. STATE MANAGEMENT ---
const STATE = {
    p: { data: [], filtered: [], page: 1, size: 10 },        // Providers
    k: { data: [], filtered: [], page: 1, size: 20 },        // Keys
    m: { data: [], filtered: [], page: 1, size: 20 },        // Models
    map: { data: [] },                                       // Forwarding Maps
    chart: null // Chart instance
};

// --- 2. API & AUTH LOGIC ---
if(localStorage.getItem('theme')==='dark') document.documentElement.classList.add('dark');
function toggleTheme(){ 
    const isDark = document.documentElement.classList.toggle('dark'); 
    localStorage.setItem('theme', isDark?'dark':'light'); 
}

async function api(u, m='GET', d=null) {
    try {
        const r = await fetch(u, { method: m, headers: {'Content-Type':'application/json'}, body: d?JSON.stringify(d):null });
        if(r.status===401) { document.getElementById('loginModal').classList.remove('hidden'); return null; }
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

// --- 3. DATA LOADING & RENDERING ---

// --- OVERVIEW ---
async function loadOverview() {
    // 1. Fetch Stats
    const d = await api('/api/admin/stats');
    if(!d) return;
    
    // 2. Fetch Keys count if empty (to get Total API Keys)
    if(STATE.k.data.length === 0) await loadK();
    document.getElementById('ov_keys').innerText = STATE.k.data.length;

    // 3. Fill Basic Stats (Order: Provider, Model, Key, Map, Request, Processing)
    document.getElementById('ov_providers').innerText = d.overview.total_provider;
    document.getElementById('ov_models').innerText = d.overview.total_models;
    document.getElementById('ov_maps').innerText = d.overview.total_mapping;
    document.getElementById('ov_requests').innerText = d.overview.total_request;
    document.getElementById('ov_processing').innerText = d.overview.request_now;

    // 4. Chart.js (Doughnut - Top 10)
    const ctx = document.getElementById('topModelChart').getContext('2d');
    if(STATE.chart) STATE.chart.destroy();
    
    const isDark = document.documentElement.classList.contains('dark');
    const txtColor = isDark ? '#94a3b8' : '#6b7280';
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#6366f1', '#14b8a6', '#f97316', '#64748b'];

    STATE.chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: d.chart_top_models.labels,
            datasets: [{
                data: d.chart_top_models.data,
                backgroundColor: colors,
                borderWidth: 0,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '65%',
            plugins: { 
                legend: { 
                    position: 'right', 
                    labels: { color: txtColor, boxWidth: 10, font: {size: 11} } 
                } 
            }
        }
    });

    // 5. Live Request Grid (Sorted Old -> New)
    const grid = document.getElementById('liveGrid');
    if(d.live_requests && d.live_requests.length > 0) {
        // Reverse to show Oldest first (Left/Top) -> Newest (Right/Bottom)
        const sortedReqs = [...d.live_requests].reverse();
        
        grid.innerHTML = sortedReqs.map(req => {
            let cls = 'bg-process';
            if(req.status === 'success') cls = 'bg-success';
            if(req.status === 'fail') cls = 'bg-fail';
            
            const timeStr = req.ts ? new Date(req.ts).toLocaleString('vi-VN') : 'Unknown Time';
            
            // Pass event to stop propagation
            return `<div class="live-sq ${cls}" 
                        title="${timeStr} - ${req.status}" 
                        onclick="showReqDetail(event, '${timeStr}', '${req.status}', '${req.status}')">
                    </div>`;
        }).join('');
        
        // Auto scroll to bottom to show newest
        setTimeout(() => { grid.scrollTop = grid.scrollHeight; }, 50);
    } else {
        grid.innerHTML = '<span style="color:var(--text-muted); font-size:0.8rem; padding:10px">No recent activity</span>';
    }
}

// REQUEST POPUP LOGIC (No timeout, click outside to close)
function showReqDetail(e, time, status, rawStatus) {
    e.stopPropagation(); // Stop click from propagating to window
    const p = document.getElementById("reqDetailPopup");
    
    let icon = '<i class="fa-solid fa-circle-info"></i>';
    let colorStyle = '';
    if(rawStatus === 'success') { icon = '<i class="fa-solid fa-check-circle"></i>'; colorStyle = 'color:var(--success)'; }
    if(rawStatus === 'fail') { icon = '<i class="fa-solid fa-triangle-exclamation"></i>'; colorStyle = 'color:var(--danger)'; }

    p.innerHTML = `
        <h4 style="${colorStyle}">${icon} Request Detail</h4>
        <div style="border-top:1px solid var(--border); margin:10px 0; padding-top:10px;">
            <p><strong>Time:</strong> ${time}</p>
            <p><strong>Status:</strong> <span style="font-weight:bold; ${colorStyle}">${status.toUpperCase()}</span></p>
        </div>
        <p style="font-size:0.75rem; font-style:italic;">(Click outside to close)</p>
    `;
    
    // Reset animation by triggering reflow
    p.classList.remove("show");
    void p.offsetWidth;
    p.classList.add("show");
}

// GLOBAL CLICK HANDLER
window.onclick = function(event) {
    // 1. Close Dropdown
    if (!event.target.matches('.three-dots-btn')) {
        document.querySelectorAll('.dropdown-content.show').forEach(d => {
            d.classList.remove('show');
            setTimeout(() => d.style.display = 'none', 200);
        });
        document.querySelectorAll('.three-dots-btn.active').forEach(b => b.classList.remove('active'));
    }
    
    // 2. Close Modal
    if (event.target.classList.contains('modal-overlay')) {
        closeKeyModal();
    }

    // 3. Close Request Popup (NEW)
    const reqPopup = document.getElementById("reqDetailPopup");
    if (reqPopup && reqPopup.classList.contains('show')) {
        // If click is NOT inside the popup, close it
        if (!reqPopup.contains(event.target)) {
            reqPopup.classList.remove("show");
        }
    }
};

window.onscroll = function() {
    if(document.querySelector('.dropdown-content.show')) {
        document.querySelectorAll('.dropdown-content.show').forEach(d => {
            d.classList.remove('show');
            d.style.display = 'none';
        });
    }
};

// --- Providers ---
async function loadP() {
    const d = await api('/api/admin/providers');
    if(d) {
        STATE.p.data = d;
        STATE.p.filtered = d;
        STATE.p.page = 1;
        document.getElementById('pTotal').innerText = d.length;
        renderP();
    }
}

function searchP() {
    const q = document.getElementById('pSearch').value.toLowerCase();
    STATE.p.filtered = !q ? STATE.p.data : STATE.p.data.filter(p => p.name.toLowerCase().includes(q));
    STATE.p.page = 1;
    renderP();
}

function renderP() {
    const { filtered, page, size } = STATE.p;
    if(filtered.length === 0) {
        document.getElementById('pList').innerHTML = '<tr><td colspan="3" class="text-center text-muted" style="padding:15px">No providers found</td></tr>';
        updatePagination('p', 0);
        return;
    }

    const view = filtered.slice((page - 1) * size, page * size);
    document.getElementById('pList').innerHTML = view.map(p => {
        const url = p.base_url || 'Default';
        return `
        <tr>
            <td class="font-bold text-main">${p.name}</td>
            <td>
                <span class="clickable-badge" onclick="copyTxt('${url}')" title="Copy URL: ${url}">
                    ${p.provider_type} <i class="fa-solid fa-link" style="font-size:0.8em; margin-left:5px; opacity:0.6"></i>
                </span>
            </td>
            <td class="text-right"><button class="btn-danger-ghost" onclick="delP('${p.name}')">Del</button></td>
        </tr>`;
    }).join('');
    updatePagination('p', filtered.length);
}

// --- Keys ---
async function loadK() {
    const d = await api('/api/admin/keys');
    if(d) {
        d.sort((a,b) => b.is_hidden - a.is_hidden);
        STATE.k.data = d;
        STATE.k.filtered = d;
        STATE.k.page = 1;
        document.getElementById('kTotal').innerText = d.length;
        renderK();
    }
}

function searchK() {
    const q = document.getElementById('kSearch').value.toLowerCase();
    STATE.k.filtered = !q ? STATE.k.data : STATE.k.data.filter(k => k.name.toLowerCase().includes(q));
    STATE.k.page = 1;
    renderK();
}

function renderK() {
    const { filtered, page, size } = STATE.k;
    if(filtered.length === 0) {
        document.getElementById('kList').innerHTML = '<tr><td colspan="3" class="text-center text-muted" style="padding:15px">No keys found</td></tr>';
        updatePagination('k', 0);
        return;
    }

    const view = filtered.slice((page - 1) * size, page * size);
    document.getElementById('kList').innerHTML = view.map(k => {
        const isMaster = k.is_hidden;
        const keyDisplay = isMaster 
            ? `<span style="color:#d97706; background:#fffbeb; padding:4px 8px; border-radius:4px; font-size:0.7rem; border:1px solid #fcd34d;">MASTER</span>`
            : `<span class="copy-box" onclick="copyTxt('${k.key}')" oncontextmenu="return false;" title="${k.key}">${k.key} <i class="fa-regular fa-copy"></i></span>`;
        
        const actionHtml = `
            <div class="action-menu">
                <button onclick="toggleDropdown(event, '${k.key}')" class="three-dots-btn" id="btn-${k.key}">⋮</button>
                <div id="dd-${k.key}" class="dropdown-content">
                    <a onclick="openKeyModal('${k.key}')"><i class="fa-solid fa-circle-info"></i> Details</a>
                    ${!isMaster ? `<a onclick="delK('${k.key}')" class="text-danger"><i class="fa-solid fa-trash"></i> Delete</a>` : ''}
                </div>
            </div>`;

        return `
        <tr>
            <td class="font-bold" title="${k.name}">${k.name}</td>
            <td>${keyDisplay}</td>
            <td class="text-right">${actionHtml}</td>
        </tr>`;
    }).join('');
    updatePagination('k', filtered.length);
}

// --- Dropdown ---
function toggleDropdown(e, id) {
    e.stopPropagation();
    const menu = document.getElementById(`dd-${id}`);
    const btn = document.getElementById(`btn-${id}`);
    
    document.querySelectorAll('.dropdown-content').forEach(d => {
        if (d.id !== `dd-${id}`) {
            d.classList.remove('show');
            d.style.display = 'none';
        }
    });

    const isShowing = menu.classList.contains('show');
    
    if (isShowing) {
        menu.classList.remove('show');
        setTimeout(() => menu.style.display = 'none', 200);
        btn.classList.remove('active');
    } else {
        menu.style.display = 'block';
        const rect = btn.getBoundingClientRect();
        const menuWidth = 160; 
        
        let top = rect.bottom + 5;
        let left = rect.left - menuWidth + rect.width;
        if (top + 100 > window.innerHeight) top = rect.top - 100;

        menu.style.top = `${top}px`;
        menu.style.left = `${left}px`;
        requestAnimationFrame(() => { menu.classList.add('show'); });
        btn.classList.add('active');
    }
}

// --- Modal & Edit ---
function openKeyModal(keyStr) {
    const k = STATE.k.data.find(item => item.key === keyStr);
    if (!k) return;
    document.getElementById('m_key_id').value = k.key;
    document.getElementById('m_name').value = k.name;
    document.getElementById('m_rate').value = k.rate_limit || '';
    document.getElementById('m_quota').value = k.usage_limit || '';
    document.getElementById('m_used').innerText = k.usage_count;
    disableEditMode();
    document.getElementById('keyModal').style.display = 'block';
}

function closeKeyModal() { document.getElementById('keyModal').style.display = 'none'; }

function enableEditMode() {
    document.getElementById('m_name').disabled = false;
    document.getElementById('m_rate').disabled = false;
    document.getElementById('m_quota').disabled = false;
    document.getElementById('btnSaveGroup').classList.remove('hidden');
    document.getElementById('editBtn').classList.add('active');
}

function disableEditMode() {
    document.getElementById('m_name').disabled = true;
    document.getElementById('m_rate').disabled = true;
    document.getElementById('m_quota').disabled = true;
    document.getElementById('btnSaveGroup').classList.add('hidden');
    document.getElementById('editBtn').classList.remove('active');
}

async function saveKeyChanges() {
    const keyStr = document.getElementById('m_key_id').value;
    const payload = {
        name: document.getElementById('m_name').value,
        rate_limit: document.getElementById('m_rate').value ? parseInt(document.getElementById('m_rate').value) : null,
        usage_limit: document.getElementById('m_quota').value ? parseInt(document.getElementById('m_quota').value) : null
    };

    const res = await api(`/api/admin/keys/${keyStr}`, 'PUT', payload);
    if(res) {
        closeKeyModal();
        loadK(); 
        const t = document.getElementById("toast"); 
        t.innerHTML = '<i class="fa-solid fa-check"></i> Updated!'; t.className="show"; 
        setTimeout(()=>t.className="", 2000);
    } else {
        alert("Update failed.");
    }
}

// --- Models ---
async function loadM() {
    document.getElementById('mList').innerHTML = '<tr><td colspan="3" class="text-center" style="padding:20px;">Loading...</td></tr>';
    const res = await api('/v1/models');
    if(res && res.data) {
        STATE.m.data = res.data;
        STATE.m.filtered = res.data; 
        STATE.m.page = 1;
        document.getElementById('mTotal').innerText = res.data.length;
        renderM();
    } else {
        document.getElementById('mList').innerHTML = '<tr><td colspan="3" class="text-center text-muted">No models found</td></tr>';
    }
}

function searchM() {
    const q = document.getElementById('mSearch').value.toLowerCase();
    STATE.m.filtered = !q ? STATE.m.data : STATE.m.data.filter(m => m.id.toLowerCase().includes(q));
    STATE.m.page = 1;
    renderM();
}

function renderM() {
    const { filtered, page, size } = STATE.m;
    if(filtered.length === 0) {
        document.getElementById('mList').innerHTML = '<tr><td colspan="3" class="text-center text-muted" style="padding:20px">No matching models</td></tr>';
        updatePagination('m', 0);
        return;
    }
    const view = filtered.slice((page - 1) * size, page * size);
    document.getElementById('mList').innerHTML = view.map(m => {
        const parts = m.id.split('/');
        const alias = parts[0];
        const realModel = parts.slice(1).join('/');
        return `
        <tr>
            <td style="font-weight:bold; color:var(--primary)">${alias}</td>
            <td onclick="copyTxt('${realModel}')" class="text-copy" title="Click to copy Real Name">${realModel}</td>
            <td><span class="copy-box" onclick="copyTxt('${m.id}')">${m.id} <i class="fa-solid fa-paste"></i></span></td>
        </tr>`;
    }).join('');
    updatePagination('m', filtered.length);
}

// --- Maps ---
async function loadMap() {
    const d = await api('/api/admin/maps');
    if(d) {
        STATE.map.data = d;
        document.getElementById('mapTotal').innerText = d.length;
        renderMap();
    }
}

function renderMap() {
    const list = document.getElementById('mapList');
    if(STATE.map.data.length === 0) {
        list.innerHTML = '<tr><td colspan="4" class="text-center text-muted" style="padding:15px">No forwarding rules</td></tr>';
        return;
    }
    list.innerHTML = STATE.map.data.map(m => `
        <tr>
            <td style="font-weight:bold; color:var(--primary)">${m.source_model}</td>
            <td class="text-center text-muted"><i class="fa-solid fa-arrow-right"></i></td>
            <td>${m.target_model}</td>
            <td class="text-right">
                <button class="btn-danger-ghost" onclick="delMap('${m.source_model}')">Del</button>
            </td>
        </tr>
    `).join('');
}

async function delMap(src) {
    if(confirm(`Delete rule for '${src}'?`)) { await api(`/api/admin/maps/${src}`, 'DELETE'); loadMap(); }
}

// --- Utils ---
function updatePagination(type, totalItems) {
    const s = STATE[type];
    const totalPages = Math.ceil(totalItems / s.size);
    const el = document.getElementById(`${type}Pagination`);
    if(totalItems > s.size) {
        el.classList.remove('hidden');
        document.getElementById(`pageInfo_${type}`).innerText = `Page ${s.page} / ${totalPages}`;
        document.getElementById(`btnPrev_${type}`).disabled = s.page === 1;
        document.getElementById(`btnNext_${type}`).disabled = s.page === totalPages;
    } else {
        el.classList.add('hidden');
    }
}

function changePage(type, step) {
    const s = STATE[type];
    const totalItems = s.filtered.length;
    const totalPages = Math.ceil(totalItems / s.size);
    const next = s.page + step;
    if(next >= 1 && next <= totalPages) {
        s.page = next;
        if(type === 'p') renderP(); if(type === 'k') renderK(); if(type === 'm') renderM();
    }
}

function fillUrl() {
    const t = document.getElementById('p_type').value;
    const b = document.getElementById('p_base');
    if(t==='openrouter') { b.value='https://openrouter.ai/api/v1'; b.disabled=false; }
    else if(t==='gemini') { b.value='https://generativelanguage.googleapis.com'; b.disabled=false; }
    else { b.value=''; b.disabled=false; b.placeholder='https://api.openai.com/v1'; }
}

function tab(t) {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`t-${t}`).classList.add('active');
    
    ['v-overview', 'v-config','v-stats','v-models','v-maps'].forEach(id => {
        const el = document.getElementById(id);
        if(el) { el.classList.add('hidden'); el.classList.remove('tab-content'); }
    });

    const target = document.getElementById(`v-${t}`);
    target.classList.remove('hidden');
    void target.offsetWidth; 
    target.classList.add('tab-content');
    
    if(t==='overview') loadOverview();
    if(t==='config') loadP(); 
    if(t==='stats') loadK(); 
    if(t==='models') loadM();
    if(t==='maps') loadMap();
}

function copyTxt(txt) {
    const ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); 
        const t = document.getElementById("toast"); 
        t.innerHTML = '<i class="fa-solid fa-check"></i> Copied!'; t.className="show"; 
        setTimeout(()=>t.className="", 2000);
    } catch(e){}
    document.body.removeChild(ta);
}

// --- Init ---
document.getElementById('loginForm').onsubmit = async(e)=>{
    e.preventDefault();
    const k = document.getElementById('mk').value;
    const res = await fetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({master_key:k})});
    if(res.ok) { 
        document.getElementById('loginModal').classList.add('hidden'); 
        document.getElementById('app').classList.remove('hidden'); 
        document.getElementById('mainNav').classList.remove('hidden');
        loadOverview();
    }
    else { document.getElementById('loginMsg').style.display='block'; }
};

async function logout() { await fetch('/api/auth/logout', {method:'POST'}); location.reload(); }

async function check() { 
    const d=await api('/api/admin/providers'); 
    if(d){ 
        document.getElementById('loginModal').classList.add('hidden'); 
        document.getElementById('app').classList.remove('hidden'); 
        document.getElementById('mainNav').classList.remove('hidden');
        loadOverview();
    } 
    else { document.getElementById('loginModal').classList.remove('hidden'); } 
}

document.getElementById('pForm').onsubmit = async(e)=>{
    e.preventDefault(); 
    await api('/api/admin/providers','POST',{name:document.getElementById('p_name').value, provider_type:document.getElementById('p_type').value, api_key:document.getElementById('p_key').value, base_url:document.getElementById('p_base').value||null}); 
    e.target.reset(); loadP(); 
};
document.getElementById('kForm').onsubmit = async(e)=>{
    e.preventDefault(); 
    const r=await api('/api/admin/keys','POST',{name:document.getElementById('k_name').value, custom_key:document.getElementById('k_cust').value||null}); 
    if(r){ copyTxt(r.key); e.target.reset(); tab('stats'); }
};
document.getElementById('mapForm').onsubmit = async(e) => {
    e.preventDefault();
    const src = document.getElementById('map_src').value.trim();
    const target = document.getElementById('map_target').value.trim();
    if(!src || !target) return;
    const r = await api('/api/admin/maps', 'POST', { source_model: src, target_model: target });
    if(r) { e.target.reset(); loadMap(); } else { alert('Error: Alias might already exist'); }
};

async function delP(n){if(confirm('Delete provider?')) {await api(`/api/admin/providers/${n}`,'DELETE'); loadP();}}
async function delK(k){if(confirm('Delete key?')) {await api(`/api/admin/keys/${k}`,'DELETE'); loadK();}}

check();