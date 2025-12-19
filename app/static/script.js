const KEY = "gw_v5_final";
const STATE = {
    p: { data: [], filtered: [], page: 1, size: 10 },
    k: { data: [], filtered: [], page: 1, size: 20 },
    m: { data: [], filtered: [], page: 1, size: 20 },
    g: { data: [], filtered: [] },
    chart: null,
    editingGroupId: null,
    availableModels: [],
};

if (localStorage.getItem("theme") === "dark")
    document.documentElement.classList.add("dark");
function toggleTheme() {
    const isDark = document.documentElement.classList.toggle("dark");
    localStorage.setItem("theme", isDark ? "dark" : "light");
    if (STATE.chart) loadOverview();
}
async function api(u, m = "GET", d = null) {
    try {
        const r = await fetch(u, {
            method: m,
            headers: { "Content-Type": "application/json" },
            body: d ? JSON.stringify(d) : null,
        });
        if (r.status === 401) {
            document.getElementById("loginModal").classList.remove("hidden");
            return null;
        }
        return r.ok ? await r.json() : null;
    } catch {
        return null;
    }
}

// --- OVERVIEW ---
async function loadOverview() {
    const d = await api("/api/admin/stats");
    if (!d) return;
    if (STATE.k.data.length === 0) await loadK();
    document.getElementById("ov_keys").innerText = STATE.k.data.length;
    document.getElementById("ov_providers").innerText =
        d.overview.total_provider;
    document.getElementById("ov_models").innerText = d.overview.total_models;
    document.getElementById("ov_groups").innerText =
        d.overview.total_groups || 0;
    document.getElementById("ov_requests").innerText = d.overview.total_request;
    document.getElementById("ov_processing").innerText = d.overview.request_now;

    const ctx = document.getElementById("topModelChart").getContext("2d");
    if (STATE.chart) STATE.chart.destroy();
    const colors = [
        "#FF9AA2",
        "#FFB7B2",
        "#FFDAC1",
        "#E2F0CB",
        "#B5EAD7",
        "#C7CEEA",
        "#F0E6EF",
        "#A0C4FF",
        "#BDB2FF",
        "#FFC6FF",
    ];
    STATE.chart = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: d.chart_top_models.labels,
            datasets: [
                {
                    data: d.chart_top_models.data,
                    backgroundColor: colors,
                    borderWidth: 2,
                    borderColor: document.documentElement.classList.contains(
                        "dark"
                    )
                        ? "#000000"
                        : "#ffffff",
                    hoverOffset: 6,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "60%",
            plugins: { legend: { display: false } },
        },
    });

    const grid = document.getElementById("liveGrid");
    if (d.live_requests && d.live_requests.length > 0) {
        grid.innerHTML = d.live_requests
            .reverse()
            .map(
                (r) =>
                    `<div class="live-sq ${
                        r.status === "success"
                            ? "bg-success"
                            : r.status === "fail"
                            ? "bg-fail"
                            : "bg-process"
                    }" onclick="showReqDetail(event,'${r.ts}','${r.status}','${
                        r.status
                    }')"></div>`
            )
            .join("");
        setTimeout(() => (grid.scrollTop = grid.scrollHeight), 50);
    } else
        grid.innerHTML =
            '<span style="color:var(--text-muted);font-size:0.8rem;padding:10px">No activity</span>';
}

// LOGIC TOOLTIP LIVE REQUEST (Fix vị trí)
function showReqDetail(e, t, s, rs) {
    e.stopPropagation();
    const p = document.getElementById("reqDetailPopup");
    const target = e.target;
    const rect = target.getBoundingClientRect();

    p.innerHTML = `<div style="font-weight:bold">${s.toUpperCase()}</div><div style="font-size:0.7rem; opacity:0.8">${t}</div>`;
    p.classList.add("show");

    // Tính toán toạ độ để hiện ngay trên ô vuông
    const top = rect.top - p.offsetHeight - 8;
    const left = rect.left + rect.width / 2;

    p.style.top = `${top}px`;
    p.style.left = `${left}px`;
}

// --- DROPDOWNS & UI ---
function toggleDropdown(e, id) {
    e.stopPropagation();
    document.querySelectorAll(".dropdown-content.show").forEach((d) => {
        if (d.id !== id) d.classList.remove("show");
    });
    const m = document.getElementById(id);
    if (m.classList.contains("show")) m.classList.remove("show");
    else m.classList.add("show");
}
window.onclick = (e) => {
    if (!e.target.closest(".three-dots-btn"))
        document
            .querySelectorAll(".dropdown-content.show")
            .forEach((d) => d.classList.remove("show"));
    if (e.target.classList.contains("modal-overlay")) {
        closeKeyModal();
        closeGroupModal();
        closeProviderModal();
    }
    const p = document.getElementById("reqDetailPopup");
    if (p && p.classList.contains("show")) p.classList.remove("show");
};

// --- PROVIDERS ---
async function loadP() {
    const d = await api("/api/admin/providers");
    if (d) {
        STATE.p.data = d;
        STATE.p.filtered = d;
        STATE.p.page = 1;
        document.getElementById("pTotal").innerText = d.length;
        renderP();
    }
}
function searchP() {
    const q = document.getElementById("pSearch").value.toLowerCase();
    STATE.p.filtered = !q
        ? STATE.p.data
        : STATE.p.data.filter((p) => p.name.toLowerCase().includes(q));
    STATE.p.page = 1;
    renderP();
}
function renderP() {
    const { filtered, page, size } = STATE.p;
    const list = document.getElementById("pList");
    if (filtered.length === 0) {
        list.innerHTML =
            '<tr><td colspan="3" class="text-center text-muted" style="padding:15px">No providers</td></tr>';
        updatePagination("p", 0);
        return;
    }
    const view = filtered.slice((page - 1) * size, page * size);
    list.innerHTML = view
        .map(
            (p) =>
                `<tr><td class="font-bold">${
                    p.name
                }</td><td><span class="clickable-badge" onclick="copyTxt('${
                    p.base_url || "Default"
                }')">${
                    p.provider_type
                }</span></td><td class="text-right"><div class="action-menu"><button class="three-dots-btn" onclick="toggleDropdown(event,'pm-${
                    p.name
                }')"><i class="fa-solid fa-ellipsis-vertical"></i></button><div id="pm-${
                    p.name
                }" class="dropdown-content"><a onclick="openEditProvider('${
                    p.name
                }')"><i class="fa-solid fa-pen"></i> Edit</a><a onclick="delP('${
                    p.name
                }')" class="text-danger"><i class="fa-solid fa-trash"></i> Delete</a></div></div></td></tr>`
        )
        .join("");
    updatePagination("p", filtered.length);
}
// Provider Modal Logic
function openProviderModal() {
    document.getElementById("pModalTitle").innerText = "New Provider";
    document.getElementById("pm_is_edit").value = "false";
    document.getElementById("pm_name").value = "";
    document.getElementById("pm_name").disabled = false;
    document.getElementById("pm_type").value = "openai";
    document.getElementById("pm_base").value = "https://api.openai.com/v1";
    document.getElementById("pm_has_key").checked = true;
    toggleKeyInput();
    document.getElementById("pm_key").value = "";
    document.getElementById("pm_key_help").innerText = "Enter API Key";
    document.getElementById("providerModal").style.display = "block";
}
function openEditProvider(name) {
    const p = STATE.p.data.find((x) => x.name === name);
    if (!p) return;
    document.getElementById("pModalTitle").innerText = "Edit Provider";
    document.getElementById("pm_is_edit").value = "true";
    document.getElementById("pm_name").value = p.name;
    document.getElementById("pm_name").disabled = true;
    document.getElementById("pm_type").value = p.provider_type;
    document.getElementById("pm_base").value = p.base_url || "";
    document.getElementById("pm_has_key").checked = true;
    toggleKeyInput();
    document.getElementById("pm_key").value = "";
    document.getElementById("pm_key_help").innerText =
        "Leave blank to keep unchanged.";
    document.getElementById("providerModal").style.display = "block";
}
function closeProviderModal() {
    document.getElementById("providerModal").style.display = "none";
}
function toggleKeyInput() {
    const hasKey = document.getElementById("pm_has_key").checked;
    const keyInput = document.getElementById("pm_key");
    if (hasKey) {
        keyInput.style.display = "block";
        keyInput.disabled = false;
        const isEdit = document.getElementById("pm_is_edit").value === "true";
        document.getElementById("pm_key_help").innerText = isEdit
            ? "Leave blank to keep unchanged."
            : "Enter API Key";
    } else {
        keyInput.style.display = "none";
        keyInput.disabled = true;
        document.getElementById("pm_key_help").innerText =
            "No API Key will be used.";
    }
}
function fillPUrl() {
    const t = document.getElementById("pm_type").value;
    document.getElementById("pm_base").value =
        t === "openrouter"
            ? "https://openrouter.ai/api/v1"
            : t === "gemini"
            ? "https://generativelanguage.googleapis.com"
            : "https://api.openai.com/v1";
}
async function saveProvider() {
    const isEdit = document.getElementById("pm_is_edit").value === "true";
    const name = document.getElementById("pm_name").value;
    const type = document.getElementById("pm_type").value;
    const base = document.getElementById("pm_base").value;
    const hasKey = document.getElementById("pm_has_key").checked;
    let key = null;
    if (!hasKey) {
        key = "";
    } else {
        const val = document.getElementById("pm_key").value;
        if (val.trim() !== "") key = val;
    }
    const payload = { name, provider_type: type, base_url: base, api_key: key };
    if (isEdit) {
        if (await api(`/api/admin/providers/${name}`, "PUT", payload)) {
            closeProviderModal();
            loadP();
            showToast();
        } else alert("Update failed");
    } else {
        if (await api("/api/admin/providers", "POST", payload)) {
            closeProviderModal();
            loadP();
            showToast();
        } else alert("Failed");
    }
}

// --- KEYS ---
async function loadK() {
    const d = await api("/api/admin/keys");
    if (d) {
        d.sort((a, b) => b.is_hidden - a.is_hidden);
        STATE.k.data = d;
        STATE.k.filtered = d;
        STATE.k.page = 1;
        document.getElementById("kTotal").innerText = d.length;
        renderK();
    }
}
function searchK() {
    const q = document.getElementById("kSearch").value.toLowerCase();
    STATE.k.filtered = !q
        ? STATE.k.data
        : STATE.k.data.filter((k) => k.name.toLowerCase().includes(q));
    STATE.k.page = 1;
    renderK();
}
function renderK() {
    const { filtered, page, size } = STATE.k;
    const list = document.getElementById("kList");
    if (filtered.length === 0) {
        list.innerHTML =
            '<tr><td colspan="3" class="text-center text-muted" style="padding:15px">No keys</td></tr>';
        updatePagination("k", 0);
        return;
    }
    const view = filtered.slice((page - 1) * size, page * size);
    list.innerHTML = view
        .map(
            (k) =>
                `<tr><td class="font-bold">${k.name}</td><td>${
                    k.is_hidden
                        ? '<span style="color:#d97706;background:#fffbeb;padding:2px 6px;border-radius:4px;border:1px solid #fcd34d;font-size:0.7rem">MASTER</span>'
                        : `<span class="copy-box" onclick="copyTxt('${k.key}')">${k.key} <i class="fa-regular fa-copy"></i></span>`
                }</td><td class="text-right"><div class="action-menu"><button class="three-dots-btn" onclick="toggleDropdown(event,'dd-${
                    k.key
                }')"><i class="fa-solid fa-ellipsis-vertical"></i></button><div id="dd-${
                    k.key
                }" class="dropdown-content"><a onclick="openKeyModal('${
                    k.key
                }')"><i class="fa-solid fa-circle-info"></i> Details</a>${
                    !k.is_hidden
                        ? `<a onclick="delK('${k.key}')" class="text-danger"><i class="fa-solid fa-trash"></i> Delete</a>`
                        : ""
                }</div></div></td></tr>`
        )
        .join("");
    updatePagination("k", filtered.length);
}
function openKeyModal(k) {
    const d = STATE.k.data.find((x) => x.key === k);
    if (!d) return;
    document.getElementById("m_key_id").value = d.key;
    document.getElementById("m_name").value = d.name;
    document.getElementById("m_rate").value = d.rate_limit || "";
    document.getElementById("m_quota").value = d.usage_limit || "";
    document.getElementById("m_used").innerText = d.usage_count;
    disableEditMode();
    document.getElementById("keyModal").style.display = "block";
}
function closeKeyModal() {
    document.getElementById("keyModal").style.display = "none";
}
function enableEditMode() {
    document.getElementById("m_name").disabled = false;
    document.getElementById("m_rate").disabled = false;
    document.getElementById("m_quota").disabled = false;
    document.getElementById("btnSaveGroup").classList.remove("hidden");
    document.getElementById("editBtn").classList.add("active");
}
function disableEditMode() {
    document.getElementById("m_name").disabled = true;
    document.getElementById("m_rate").disabled = true;
    document.getElementById("m_quota").disabled = true;
    document.getElementById("btnSaveGroup").classList.add("hidden");
    document.getElementById("editBtn").classList.remove("active");
}
async function saveKeyChanges() {
    const k = document.getElementById("m_key_id").value,
        p = {
            name: document.getElementById("m_name").value,
            rate_limit: document.getElementById("m_rate").value
                ? parseInt(document.getElementById("m_rate").value)
                : null,
            usage_limit: document.getElementById("m_quota").value
                ? parseInt(document.getElementById("m_quota").value)
                : null,
        };
    if (await api(`/api/admin/keys/${k}`, "PUT", p)) {
        closeKeyModal();
        loadK();
        showToast();
    } else alert("Failed");
}

// --- GROUPS ---
async function loadGroups() {
    const d = await api("/api/admin/groups");
    if (d) {
        STATE.g.data = d;
        STATE.g.filtered = d;
        document.getElementById("gTotal").innerText = d.length;
        renderGroups();
    }
}
function searchGroups() {
    const q = document.getElementById("gSearch").value.toLowerCase();
    STATE.g.filtered = !q
        ? STATE.g.data
        : STATE.g.data.filter((g) => g.id.toLowerCase().includes(q));
    renderGroups();
}
function renderGroups() {
    const list = document.getElementById("gList");
    if (STATE.g.filtered.length === 0) {
        list.innerHTML =
            '<div style="padding:20px;text-align:center;color:var(--text-muted);grid-column:1/-1">No groups</div>';
        return;
    }
    list.innerHTML = STATE.g.filtered
        .map(
            (g) =>
                `<div class="group-item"><div class="group-info"><h4><i class="fa-solid fa-layer-group"></i> ${g.id}</h4><p style="margin-top:5px;font-weight:600;color:var(--text-muted);font-size:0.8rem;">${g.balance_strategy}</p></div><div style="margin-top:20px;display:flex;justify-content:flex-end;gap:8px;"><button class="btn-edit-ghost" onclick="openGroupModal('${g.id}')"><i class="fa-solid fa-pen"></i> Edit</button><button class="btn-danger-ghost" onclick="deleteGroup('${g.id}')"><i class="fa-solid fa-trash"></i></button></div></div>`
        )
        .join("");
}
async function deleteGroup(id) {
    if (confirm(`Delete ${id}?`)) {
        await api(`/api/admin/groups/${id}`, "DELETE");
        loadGroups();
    }
}
function openCreateGroupModal() {
    STATE.editingGroupId = null;
    document.getElementById("groupModalTitle").innerText = "New Group";
    document
        .querySelector("#groupModal .modal-content")
        .classList.remove("large-modal");
    document.getElementById("gm_id").value = "";
    document.getElementById("gm_id").disabled = false;
    document.getElementById("gm_strategy").value = "random";
    document.getElementById("gm_edit_sections").classList.add("hidden");
    document.getElementById("btnSaveGroupInfo").innerText = "Create";
    document.getElementById("groupModal").style.display = "block";
}
async function openGroupModal(id) {
    STATE.editingGroupId = id;
    const g = STATE.g.data.find((x) => x.id === id);
    if (!g) return;
    document
        .querySelector("#groupModal .modal-content")
        .classList.add("large-modal");
    document.getElementById("groupModalTitle").innerText = "Edit " + id;
    document.getElementById("gm_id").value = g.id;
    document.getElementById("gm_id").disabled = true;
    document.getElementById("gm_strategy").value = g.balance_strategy;
    document.getElementById("gm_edit_sections").classList.remove("hidden");
    document.getElementById("btnSaveGroupInfo").innerText = "Update";
    document.getElementById("groupModal").style.display = "block";
    await loadGroupMembers(id);
    prepareAddableModels();
}
function closeGroupModal() {
    document.getElementById("groupModal").style.display = "none";
    STATE.editingGroupId = null;
}
async function saveGroupInfo() {
    const id = document.getElementById("gm_id").value.trim(),
        s = document.getElementById("gm_strategy").value;
    if (!id) return alert("ID required");
    if (STATE.editingGroupId === id) {
        if (
            await api(`/api/admin/groups/${id}`, "PUT", {
                id,
                balance_strategy: s,
            })
        ) {
            showToast();
            loadGroups();
        }
    } else {
        if (
            await api("/api/admin/groups", "POST", { id, balance_strategy: s })
        ) {
            showToast();
            loadGroups();
            closeGroupModal();
        }
    }
}
async function loadGroupMembers(gid) {
    const l = document.getElementById("gm_members_list");
    l.innerHTML = "Loading...";
    const m = await api(`/api/admin/members/${gid}`);
    if (!m || m.length === 0) {
        l.innerHTML =
            '<p class="text-muted" style="text-align:center">No models in group</p>';
        return;
    }
    l.innerHTML = m
        .map(
            (x) =>
                `<div class="member-list-item"><div class="member-info"><div class="member-model">${x.target_model}</div><div class="member-prov">${x.provider_name} • Weight: ${x.weight}</div></div><button class="btn-danger-ghost" onclick="removeMember(${x.id},'${gid}')" style="flex-shrink:0;"><i class="fa-solid fa-trash"></i></button></div>`
        )
        .join("");
}
async function removeMember(mid, gid) {
    if (confirm("Remove?")) {
        await api(`/api/admin/members/${mid}`, "DELETE");
        loadGroupMembers(gid);
    }
}
function prepareAddableModels() {
    if (STATE.m.data.length === 0)
        api("/v1/models").then((r) => {
            if (r) {
                STATE.m.data = r.data.filter(
                    (x) => x.owned_by !== "gateway-group"
                );
                renderAddableModels();
            }
        });
    else renderAddableModels();
}
function searchAddableModels() {
    renderAddableModels();
}
function renderAddableModels() {
    const q = document.getElementById("gm_add_search").value.toLowerCase(),
        l = document.getElementById("gm_add_list"),
        f = STATE.m.data.filter((m) => m.id.toLowerCase().includes(q));
    if (f.length === 0) {
        l.innerHTML =
            '<div style="padding:10px;text-align:center;color:var(--text-muted)">No models</div>';
        return;
    }
    l.innerHTML = f
        .map((m) => {
            const p = m.id.split("/");
            return `<div class="add-model-item"><div style="overflow:hidden; flex:1;"><div style="font-weight:bold;font-size:0.85rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${
                m.id
            }</div></div><button class="add-btn" onclick="addMemberToGroup('${
                p[0]
            }','${p
                .slice(1)
                .join("/")}')"><i class="fa-solid fa-plus"></i></button></div>`;
        })
        .join("");
}
async function addMemberToGroup(pn, tm) {
    if (
        await api("/api/admin/members", "POST", {
            group_id: STATE.editingGroupId,
            provider_name: pn,
            target_model: tm,
            weight: 1,
        })
    ) {
        showToast();
        loadGroupMembers(STATE.editingGroupId);
    } else alert("Failed");
}

// --- MODELS ---
async function loadM() {
    const r = await api("/v1/models");
    if (r) {
        STATE.m.data = r.data.filter((x) => x.owned_by !== "gateway-group");
        STATE.m.filtered = STATE.m.data;
        STATE.m.page = 1;
        document.getElementById("mTotal").innerText = STATE.m.data.length;
        renderM();
    }
}
function searchM() {
    const q = document.getElementById("mSearch").value.toLowerCase();
    STATE.m.filtered = !q
        ? STATE.m.data
        : STATE.m.data.filter((m) => m.id.toLowerCase().includes(q));
    STATE.m.page = 1;
    renderM();
}
function renderM() {
    const { filtered, page, size } = STATE.m,
        l = document.getElementById("mList");
    if (filtered.length === 0) {
        l.innerHTML =
            '<tr><td colspan="3" class="text-center text-muted">No models</td></tr>';
        updatePagination("m", 0);
        return;
    }
    const v = filtered.slice((page - 1) * size, page * size);
    l.innerHTML = v
        .map((m) => {
            const p = m.id.split("/");
            return `<tr><td style="font-weight:bold;">${
                p[0]
            }</td><td onclick="copyTxt('${p
                .slice(1)
                .join("/")}')" class="text-copy">${p
                .slice(1)
                .join(
                    "/"
                )}</td><td class="col-mod-full"><span class="copy-box" onclick="copyTxt('${
                m.id
            }')">${m.id}</span></td></tr>`;
        })
        .join("");
    updatePagination("m", filtered.length);
}

// --- COMMON HELPERS ---
function updatePagination(t, tot) {
    const s = STATE[t],
        pg = Math.ceil(tot / s.size),
        el = document.getElementById(`${t}Pagination`);
    if (tot > s.size) {
        el.classList.remove("hidden");
        document.getElementById(
            `pageInfo_${t}`
        ).innerText = `Page ${s.page} / ${pg}`;
        document.getElementById(`btnPrev_${t}`).disabled = s.page === 1;
        document.getElementById(`btnNext_${t}`).disabled = s.page === pg;
    } else el.classList.add("hidden");
}
function changePage(t, st) {
    const s = STATE[t],
        nxt = s.page + st,
        pg = Math.ceil(s.filtered.length / s.size);
    if (nxt >= 1 && nxt <= pg) {
        s.page = nxt;
        if (t === "p") renderP();
        if (t === "k") renderK();
        if (t === "m") renderM();
    }
}
function tab(t) {
    document
        .querySelectorAll(".nav-btn")
        .forEach((b) => b.classList.remove("active"));
    document.getElementById(`t-${t}`).classList.add("active");
    [
        "v-overview",
        "v-config",
        "v-stats",
        "v-models",
        "v-groups",
    ].forEach((id) => document.getElementById(id).classList.add("hidden"));
    document.getElementById(`v-${t}`).classList.remove("hidden");
    if (t === "overview") loadOverview();
    if (t === "config") loadP();
    if (t === "stats") loadK();
    if (t === "models") loadM();
    if (t === "groups") loadGroups();
}
function copyTxt(t) {
    navigator.clipboard.writeText(t).then(showToast);
}
function showToast() {
    const t = document.getElementById("toast");
    t.className = "show";
    setTimeout(() => (t.className = ""), 2000);
}
async function delP(n) {
    if (confirm("Delete?")) {
        await api(`/api/admin/providers/${n}`, "DELETE");
        loadP();
    }
}
async function delK(k) {
    if (confirm("Delete?")) {
        await api(`/api/admin/keys/${k}`, "DELETE");
        loadK();
    }
}

document.getElementById("loginForm").onsubmit = async (e) => {
    e.preventDefault();
    if (
        await api("/api/auth/login", "POST", {
            master_key: document.getElementById("mk").value,
        })
    ) {
        document.getElementById("loginModal").classList.add("hidden");
        document.getElementById("app").classList.remove("hidden");
        document.getElementById("mainNav").classList.remove("hidden");
        loadOverview();
    } else document.getElementById("loginMsg").style.display = "block";
};
document.getElementById("kForm").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("/api/admin/keys", "POST", {
        name: document.getElementById("k_name").value,
        custom_key: document.getElementById("k_cust").value || null,
    });
    if (r) {
        copyTxt(r.key);
        e.target.reset();
        tab("stats");
    }
};
async function logout() {
    await api("/api/auth/logout", "POST");
    location.reload();
}
async function check() {
    if (await api("/api/admin/providers")) {
        document.getElementById("loginModal").classList.add("hidden");
        document.getElementById("app").classList.remove("hidden");
        document.getElementById("mainNav").classList.remove("hidden");
        loadOverview();
    } else document.getElementById("loginModal").classList.remove("hidden");
}
check();
