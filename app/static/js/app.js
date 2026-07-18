"use strict";

/* ================= Утилиты ================= */

const API_BASE = ""; // same-origin

// Экранирование ЛЮБЫХ данных перед вставкой в HTML — защита от XSS
function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function toast(message, kind = "info") {
  const root = document.getElementById("toastRoot");
  const el = document.createElement("div");
  el.className = `toast ${kind === "error" ? "error" : kind === "success" ? "success" : ""}`;
  el.textContent = message;
  root.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function api(endpoint, method = "GET", body = null) {
  const headers = {};
  if (body !== null) headers["Content-Type"] = "application/json";
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const resp = await fetch(`${API_BASE}${endpoint}`, {
    method,
    headers,
    body: body !== null ? JSON.stringify(body) : undefined,
  });
  if (resp.status === 401 && state.token) {
    setSession(null, null);
    showLanding();
    throw new Error("Сессия истекла, войдите заново");
  }
  if (!resp.ok) {
    let detail = `Ошибка ${resp.status}`;
    try {
      const data = await resp.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) detail = data.detail[0].msg;
    } catch (_) { /* не JSON */ }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

const WASTE_LABELS = { plastic: "Пластик", cardboard: "Картон", glass: "Стекло", metal: "Металл", organic: "Органика" };
const STATUS_LABELS = { pending: "ожидает", clustered: "в зоне сбора", assigned: "назначен вывоз", collected: "вывезено", verified: "подтверждено" };
const ORDER_STATUS_LABELS = { pending: "ожидает", accepted: "принят", completed: "завершён", cancelled: "отменён" };

/* ================= Состояние ================= */

const state = {
  token: localStorage.getItem("qosyu_token") || null,
  user: null,
  map: null,
  markersLayer: null,
  zonesLayer: null,
  chatWs: null,
  chatPartnerId: null,
  chatPartnerName: null,
};

function setSession(token, user) {
  state.token = token;
  state.user = user;
  if (token) localStorage.setItem("qosyu_token", token);
  else localStorage.removeItem("qosyu_token");
  renderHeader();
}

/* ================= Навигация ================= */

const landingPage = document.getElementById("landingPage");
const cabinetPage = document.getElementById("cabinetPage");
const mainFooter = document.getElementById("mainFooter");
const mainNav = document.getElementById("mainNav");

function showLanding() {
  landingPage.classList.remove("hidden");
  mainFooter.classList.remove("hidden");
  mainNav.classList.remove("hidden");
  cabinetPage.classList.add("hidden");
  closeChatSocket();
}

function showCabinet() {
  if (!state.user) { openLoginModal(); return; }
  landingPage.classList.add("hidden");
  mainFooter.classList.add("hidden");
  mainNav.classList.add("hidden");
  cabinetPage.classList.remove("hidden");
  activateTab("map");
  initMap();
  renderCabinetSidebar();
  loadMapData();
  refreshUnreadBadge();
}

document.getElementById("brandLink").addEventListener("click", (e) => {
  if (!cabinetPage.classList.contains("hidden")) { e.preventDefault(); showLanding(); }
});

/* ================= Шапка ================= */

function renderHeader() {
  const box = document.getElementById("headerActions");
  if (!state.user) {
    box.innerHTML = `
      <button class="btn btn-outline btn-sm" data-hdr="login">Вход</button>
      <button class="btn btn-wine btn-sm" data-hdr="register">Регистрация</button>`;
  } else {
    box.innerHTML = `
      <span class="header-user"><strong>${esc(state.user.company_name || state.user.email)}</strong></span>
      <button class="btn btn-wine btn-sm" data-hdr="cabinet">Кабинет</button>
      <button class="btn btn-outline btn-sm" data-hdr="logout">Выйти</button>`;
  }
}

document.getElementById("headerActions").addEventListener("click", (e) => {
  const action = e.target.closest("[data-hdr]")?.dataset.hdr;
  if (action === "login") openLoginModal();
  if (action === "register") openRegisterModal();
  if (action === "cabinet") showCabinet();
  if (action === "logout") { setSession(null, null); showLanding(); toast("Вы вышли из аккаунта"); }
});

document.querySelectorAll('[data-action="register"]').forEach((btn) =>
  btn.addEventListener("click", () => (state.user ? showCabinet() : openRegisterModal()))
);

/* ================= Модалки ================= */

const modalBackdrop = document.getElementById("modalBackdrop");
const modalContent = document.getElementById("modalContent");

function openModal(html) {
  modalContent.innerHTML = html;
  modalBackdrop.classList.remove("hidden");
}
function closeModal() {
  modalBackdrop.classList.add("hidden");
  modalContent.innerHTML = "";
}
document.getElementById("modalCloseBtn").addEventListener("click", closeModal);
modalBackdrop.addEventListener("click", (e) => { if (e.target === modalBackdrop) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function openLoginModal() {
  openModal(`
    <h3>Вход в QOSYU</h3>
    <form id="loginForm">
      <label for="loginEmail">Email</label>
      <input class="field" id="loginEmail" type="email" required autocomplete="email" />
      <label for="loginPassword">Пароль</label>
      <input class="field" id="loginPassword" type="password" required autocomplete="current-password" />
      <p class="form-error" id="loginError"></p>
      <button class="btn btn-wine" type="submit">Войти</button>
    </form>
    <button class="modal-switch" id="toRegister">Нет аккаунта? Зарегистрироваться</button>`);
  document.getElementById("toRegister").addEventListener("click", openRegisterModal);
  document.getElementById("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorBox = document.getElementById("loginError");
    errorBox.textContent = "";
    try {
      const data = await api("/auth/login", "POST", {
        email: document.getElementById("loginEmail").value.trim(),
        password: document.getElementById("loginPassword").value,
      });
      setSession(data.access_token, data.user);
      closeModal();
      toast(`Добро пожаловать, ${data.user.company_name || data.user.email}!`, "success");
      showCabinet();
    } catch (err) {
      errorBox.textContent = err.message;
    }
  });
}

function openRegisterModal() {
  openModal(`
    <h3>Регистрация</h3>
    <form id="regForm">
      <label for="regCompany">Название компании</label>
      <input class="field" id="regCompany" type="text" required minlength="2" maxlength="120" />
      <label for="regEmail">Email</label>
      <input class="field" id="regEmail" type="email" required autocomplete="email" />
      <label for="regPassword">Пароль (минимум 8 символов, буквы и цифры)</label>
      <input class="field" id="regPassword" type="password" required minlength="8" autocomplete="new-password" />
      <label for="regRole">Кто вы?</label>
      <select class="field" id="regRole">
        <option value="sme">Бизнес — сдаю вторсырьё</option>
        <option value="recycler">Переработчик — забираю вторсырьё</option>
      </select>
      <p class="form-error" id="regError"></p>
      <button class="btn btn-wine" type="submit">Создать аккаунт</button>
    </form>
    <button class="modal-switch" id="toLogin">Уже есть аккаунт? Войти</button>`);
  document.getElementById("toLogin").addEventListener("click", openLoginModal);
  document.getElementById("regForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorBox = document.getElementById("regError");
    errorBox.textContent = "";
    const email = document.getElementById("regEmail").value.trim();
    const password = document.getElementById("regPassword").value;
    try {
      await api("/auth/register", "POST", {
        email,
        password,
        company_name: document.getElementById("regCompany").value.trim(),
        role: document.getElementById("regRole").value,
      });
      const data = await api("/auth/login", "POST", { email, password });
      setSession(data.access_token, data.user);
      closeModal();
      toast("Аккаунт создан. Добро пожаловать!", "success");
      showCabinet();
    } catch (err) {
      errorBox.textContent = err.message;
    }
  });
}

/* ================= Политики ================= */

document.getElementById("privacyLink").addEventListener("click", (e) => {
  e.preventDefault();
  openModal(`<h3>Политика конфиденциальности</h3><div class="policy-text">
    <p>QOSYU собирает минимально необходимые данные: email, название компании и координаты точек сбора вторсырья.</p>
    <p>Пароли хранятся только в виде необратимого хэша (bcrypt). Данные не передаются третьим лицам и используются исключительно для организации вывоза вторсырья и формирования ESG-отчётности.</p>
    <p>Вы можете запросить удаление аккаунта и связанных данных, написав нам.</p></div>`);
});
document.getElementById("termsLink").addEventListener("click", (e) => {
  e.preventDefault();
  openModal(`<h3>Условия использования</h3><div class="policy-text">
    <p>Использование сервиса означает согласие с условиями. Пользователь несёт ответственность за достоверность информации в заявках.</p>
    <p>Платформа выступает координатором первой мили: объединяет заявки и строит маршруты, не осуществляя перевозку самостоятельно.</p></div>`);
});

/* ================= Кабинет: вкладки ================= */

const panes = { map: "pane-map", requests: "pane-requests", chat: "pane-chat", market: "pane-market" };

function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("tab-active", b.dataset.tab === name));
  Object.entries(panes).forEach(([key, id]) =>
    document.getElementById(id).classList.toggle("hidden", key !== name)
  );
  if (name === "map" && state.map) setTimeout(() => state.map.invalidateSize(), 50);
  if (name === "requests") loadRequestsHistory();
  if (name === "chat") loadChatPartners();
  if (name === "market") { loadMarketplace(); loadMyOrders(); }
}

document.getElementById("cabinetTabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab-btn")?.dataset.tab;
  if (tab) activateTab(tab);
});

/* ================= Карта ================= */

function initMap() {
  if (state.map) return;
  state.map = L.map("cabinetMap").setView([47.1167, 51.8833], 12); // Атырау
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: 19,
  }).addTo(state.map);
  state.markersLayer = L.layerGroup().addTo(state.map);
  state.zonesLayer = L.layerGroup().addTo(state.map);
}

async function loadMapData() {
  if (!state.map || !state.user) return;
  state.markersLayer.clearLayers();
  state.zonesLayer.clearLayers();
  if (state.user.role === "sme") {
    try {
      const reqs = await api("/requests/my");
      reqs.forEach((r) => {
        L.marker([r.latitude, r.longitude], {
          icon: L.divIcon({ className: "map-dot", iconSize: [14, 14] }),
        })
          .bindPopup(`Заявка #${r.id}<br>${esc(WASTE_LABELS[r.waste_type] || r.waste_type)} — ${esc(r.weight_kg)} кг`)
          .addTo(state.markersLayer);
      });
    } catch (_) { /* нет заявок — не страшно */ }
  }
  try {
    const zones = await api("/clustering/zones/open");
    zones.forEach((z) => {
      L.circle([z.centroid_lat, z.centroid_lon], {
        radius: (z.radius_km || 1) * 1000,
        color: "#990011",
        weight: 2,
        fillColor: "#FBEEEE",
        fillOpacity: 0.35,
      })
        .bindPopup(`Зона #${z.id}<br>Заявок: ${z.request_count}<br>Вес: ${esc(z.total_weight_kg)} кг`)
        .addTo(state.zonesLayer);
    });
  } catch (_) { /* зоны видны только авторизованным */ }
}

/* ================= Кабинет: боковая панель ================= */

function renderCabinetSidebar() {
  const userCard = document.getElementById("cabinetUserCard");
  const roleLabel = state.user.role === "sme" ? "Бизнес" : state.user.role === "recycler" ? "Переработчик" : "Админ";
  userCard.innerHTML = `<strong>${esc(state.user.company_name || state.user.email)}</strong><span class="role-chip">${esc(roleLabel)}</span>`;

  const box = document.getElementById("cabinetActions");
  if (state.user.role === "sme") {
    box.innerHTML = `
      <div class="side-block">
        <h3>Новая заявка</h3>
        <label for="reqType">Тип вторсырья</label>
        <select class="field" id="reqType">
          <option value="cardboard">Картон</option>
          <option value="plastic">Пластик</option>
          <option value="glass">Стекло</option>
          <option value="metal">Металл</option>
        </select>
        <label for="reqWeight">Вес, кг</label>
        <input class="field" id="reqWeight" type="number" min="1" max="50000" step="0.5" placeholder="15" />
        <p class="list-item meta" style="display:block">Точка сбора — центр карты. Передвиньте карту на адрес вашей точки.</p>
        <button class="btn btn-wine" id="createReqBtn">Создать заявку</button>
      </div>
      <div class="side-block">
        <h3>Мои заявки</h3>
        <div id="sideRequestsList" class="side-stack"></div>
      </div>
      <div class="side-block">
        <h3>ESG-отчёт</h3>
        <div id="sideEsg"></div>
      </div>`;
    document.getElementById("createReqBtn").addEventListener("click", createRequestFromMap);
    loadSmeSidebar();
  } else {
    box.innerHTML = `
      <div class="side-block">
        <h3>Открытые зоны сбора</h3>
        <div id="sideOpenZones" class="side-stack"></div>
        <button class="btn btn-outline" id="genZonesBtn">Сформировать зоны (AI)</button>
      </div>
      <div class="side-block">
        <h3>Мои зоны в работе</h3>
        <div id="sideMyZones" class="side-stack"></div>
      </div>`;
    document.getElementById("genZonesBtn").addEventListener("click", async () => {
      try {
        const res = await api("/clustering/generate-zones", "POST");
        toast(res.message, "success");
        await loadRecyclerSidebar();
        await loadMapData();
      } catch (err) { toast(err.message, "error"); }
    });
    loadRecyclerSidebar();
  }
}

async function createRequestFromMap() {
  const weight = parseFloat(document.getElementById("reqWeight").value);
  if (!weight || weight <= 0) { toast("Укажите вес заявки", "error"); return; }
  const center = state.map.getCenter();
  try {
    await api("/requests/create", "POST", {
      waste_type: document.getElementById("reqType").value,
      weight_kg: weight,
      latitude: center.lat,
      longitude: center.lng,
    });
    toast("Заявка создана — AI объединит её с соседними", "success");
    document.getElementById("reqWeight").value = "";
    await loadSmeSidebar();
    await loadMapData();
  } catch (err) { toast(err.message, "error"); }
}

async function loadSmeSidebar() {
  try {
    const reqs = await api("/requests/my?limit=8");
    const box = document.getElementById("sideRequestsList");
    box.innerHTML = reqs.length
      ? reqs.map((r) => `
          <div class="list-item">
            <span>${esc(WASTE_LABELS[r.waste_type] || r.waste_type)} · ${esc(r.weight_kg)} кг</span>
            <span class="status-chip ${r.status === "collected" || r.status === "verified" ? "ok" : ""}">${esc(STATUS_LABELS[r.status] || r.status)}</span>
          </div>`).join("")
      : `<p class="meta">Заявок пока нет</p>`;
    const esg = await api("/analytics/esg/sme");
    document.getElementById("sideEsg").innerHTML = `
      <div class="list-item"><span>Передано на переработку</span><strong>${esc(esg.total_recycled_kg)} кг</strong></div>
      <div class="list-item"><span>CO₂ сэкономлено</span><strong>${esc(esg.co2_saved_kg)} кг</strong></div>
      <div class="list-item"><span>Эквивалент деревьев</span><strong>${esc(esg.equivalent_trees)}</strong></div>`;
  } catch (err) { toast(err.message, "error"); }
}

async function loadRecyclerSidebar() {
  try {
    const open = await api("/clustering/zones/open");
    const openBox = document.getElementById("sideOpenZones");
    openBox.innerHTML = open.length
      ? open.map((z) => `
          <div class="list-item">
            <span>Зона #${z.id}<br /><span class="meta">${z.request_count} заявок · ${esc(z.total_weight_kg)} кг</span></span>
            <button class="btn btn-outline btn-sm" data-assign="${z.id}">Взять</button>
          </div>`).join("")
      : `<p class="meta">Открытых зон нет. Сформируйте зоны из накопленных заявок.</p>`;
    openBox.querySelectorAll("[data-assign]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/recycler/zones/${btn.dataset.assign}/assign`, "POST");
          toast("Зона закреплена за вами", "success");
          await loadRecyclerSidebar();
          await loadMapData();
        } catch (err) { toast(err.message, "error"); }
      })
    );

    const mine = await api("/recycler/zones/my");
    const myBox = document.getElementById("sideMyZones");
    myBox.innerHTML = mine.length
      ? mine.map((z) => `
          <div class="list-item">
            <span>Зона #${z.id}<br /><span class="meta">${z.request_count} заявок · ${esc(z.total_weight_kg)} кг</span></span>
            <button class="btn btn-wine btn-sm" data-complete="${z.id}">Завершить</button>
          </div>`).join("")
      : `<p class="meta">Нет зон в работе</p>`;
    myBox.querySelectorAll("[data-complete]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/recycler/zones/${btn.dataset.complete}/complete`, "POST");
          toast("Зона завершена, ESG-метрики обновлены", "success");
          await loadRecyclerSidebar();
          await loadMapData();
        } catch (err) { toast(err.message, "error"); }
      })
    );
  } catch (err) { toast(err.message, "error"); }
}

/* ================= История заявок ================= */

async function loadRequestsHistory() {
  const box = document.getElementById("requestsHistoryList");
  try {
    const reqs = await api("/requests/my?limit=100");
    box.innerHTML = reqs.length
      ? reqs.map((r) => `
          <div class="list-item">
            <span><strong>${esc(WASTE_LABELS[r.waste_type] || r.waste_type)}</strong> — ${esc(r.weight_kg)} кг
              <br /><span class="meta">${esc((r.created_at || "").slice(0, 10))}</span></span>
            <span style="display:flex;gap:.5rem;align-items:center">
              <span class="status-chip ${r.status === "collected" || r.status === "verified" ? "ok" : ""}">${esc(STATUS_LABELS[r.status] || r.status)}</span>
              ${r.status === "pending" ? `<button class="btn btn-outline btn-sm" data-cancel="${r.id}">Отменить</button>` : ""}
            </span>
          </div>`).join("")
      : `<p class="meta">Заявок пока нет</p>`;
    box.querySelectorAll("[data-cancel]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/requests/${btn.dataset.cancel}`, "DELETE");
          toast("Заявка отменена");
          loadRequestsHistory();
        } catch (err) { toast(err.message, "error"); }
      })
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

/* ================= Чат ================= */

async function refreshUnreadBadge() {
  try {
    const { unread } = await api("/chat/unread-count");
    const badge = document.getElementById("chatUnreadBadge");
    badge.textContent = unread;
    badge.classList.toggle("hidden", !unread);
  } catch (_) { /* не критично */ }
}

async function loadChatPartners() {
  const box = document.getElementById("chatPartnersList");
  try {
    const [conversations, partners] = await Promise.all([
      api("/chat/conversations"),
      api("/chat/partners"),
    ]);
    const known = new Set(conversations.map((c) => c.user_id));
    const items = [
      ...conversations.map((c) => ({ ...c, existing: true })),
      ...partners.filter((p) => !known.has(p.user_id)).map((p) => ({ ...p, existing: false })),
    ];
    box.innerHTML = items.length
      ? items.map((item) => `
          <button class="list-item" style="width:100%;text-align:left;cursor:pointer;border:none"
                  data-chat="${item.user_id}" data-name="${esc(item.name)}">
            <span><strong>${esc(item.name)}</strong>
              ${item.existing ? `<br /><span class="meta">${esc((item.last_message || "").slice(0, 40))}</span>` : `<br /><span class="meta">Начать диалог</span>`}
            </span>
            ${item.unread ? `<span class="badge">${item.unread}</span>` : ""}
          </button>`).join("")
      : `<p class="meta">Пока не с кем начать диалог</p>`;
    box.querySelectorAll("[data-chat]").forEach((btn) =>
      btn.addEventListener("click", () => openChat(parseInt(btn.dataset.chat, 10), btn.dataset.name))
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

function closeChatSocket() {
  if (state.chatWs) {
    state.chatWs.onclose = null;
    state.chatWs.close();
    state.chatWs = null;
  }
  state.chatPartnerId = null;
}

function appendChatBubble(msg, own) {
  const box = document.getElementById("chatMessages");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${own ? "own" : ""}`;
  const time = msg.time ? new Date(msg.time).toLocaleString("ru-RU", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";
  bubble.innerHTML = `${esc(msg.message)}<time>${esc(time)}</time>`;
  box.appendChild(bubble);
  box.scrollTop = box.scrollHeight;
}

async function openChat(partnerId, partnerName) {
  closeChatSocket();
  state.chatPartnerId = partnerId;
  state.chatPartnerName = partnerName;
  document.getElementById("chatHead").textContent = partnerName;
  document.getElementById("chatForm").classList.remove("hidden");
  const box = document.getElementById("chatMessages");
  box.innerHTML = "";
  try {
    const history = await api(`/chat/history/${partnerId}?limit=50`);
    history.messages.forEach((m) => appendChatBubble(m, m.from === state.user.id));
  } catch (err) { toast(err.message, "error"); }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/chat/ws/${partnerId}?token=${encodeURIComponent(state.token)}`);
  state.chatWs = ws;
  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      if (data.type === "message") appendChatBubble(data, Boolean(data.own));
      else if (data.type === "error") toast(data.detail, "error");
      refreshUnreadBadge();
    } catch (_) { /* игнорируем мусор */ }
  };
  ws.onclose = () => {
    if (state.chatPartnerId === partnerId) {
      setTimeout(() => { if (state.chatPartnerId === partnerId) openChat(partnerId, partnerName); }, 3000);
    }
  };
}

document.getElementById("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("chatInput");
  const text = input.value.trim();
  if (!text || !state.chatWs || state.chatWs.readyState !== WebSocket.OPEN) return;
  state.chatWs.send(JSON.stringify({ message: text }));
  input.value = "";
});

/* ================= Маркетплейс ================= */

async function loadMarketplace() {
  const box = document.getElementById("marketplaceListings");
  try {
    const listings = await api("/marketplace/listings");
    box.innerHTML = listings.length
      ? listings.map((l) => `
          <article class="market-card">
            <div class="head">
              <span class="type">${esc(WASTE_LABELS[l.waste_type] || l.waste_type)}</span>
              <span class="price">${esc(l.price_per_kg)} ₸/кг</span>
            </div>
            <p class="desc">${esc(l.description || "Без описания")}</p>
            <p class="meta">Мин. партия: ${esc(l.min_kg)} кг${l.available_kg != null ? ` · Доступно: ${esc(l.available_kg)} кг` : ""}</p>
            ${l.user_id !== state.user.id
              ? `<button class="btn btn-wine btn-sm" data-order="${l.id}" data-min="${esc(l.min_kg)}">Заказать</button>`
              : `<p class="meta">Ваше объявление</p>`}
          </article>`).join("")
      : `<p class="meta">Объявлений пока нет — создайте первое!</p>`;
    box.querySelectorAll("[data-order]").forEach((btn) =>
      btn.addEventListener("click", () => openOrderModal(parseInt(btn.dataset.order, 10), parseFloat(btn.dataset.min)))
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

function openOrderModal(listingId, minKg) {
  openModal(`
    <h3>Оформить заказ</h3>
    <form id="orderForm">
      <label for="orderQty">Количество, кг (мин. ${esc(minKg || 0)})</label>
      <input class="field" id="orderQty" type="number" min="${esc(minKg || 0.1)}" step="0.5" required />
      <p class="form-error" id="orderError"></p>
      <button class="btn btn-wine" type="submit">Отправить заказ</button>
    </form>`);
  document.getElementById("orderForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/marketplace/orders", "POST", {
        listing_id: listingId,
        quantity_kg: parseFloat(document.getElementById("orderQty").value),
      });
      closeModal();
      toast(`Заказ создан на сумму ${res.total} ₸. Ожидайте подтверждения.`, "success");
      loadMarketplace();
      loadMyOrders();
    } catch (err) {
      document.getElementById("orderError").textContent = err.message;
    }
  });
}

document.getElementById("addListingBtn").addEventListener("click", () => {
  openModal(`
    <h3>Новое объявление</h3>
    <form id="listingForm">
      <label for="lstType">Тип вторсырья</label>
      <select class="field" id="lstType">
        <option value="cardboard">Картон</option>
        <option value="plastic">Пластик</option>
        <option value="glass">Стекло</option>
        <option value="metal">Металл</option>
      </select>
      <label for="lstPrice">Цена, ₸/кг</label>
      <input class="field" id="lstPrice" type="number" min="1" step="1" required />
      <label for="lstMin">Минимальная партия, кг</label>
      <input class="field" id="lstMin" type="number" min="0" step="1" value="0" />
      <label for="lstAvail">Доступный объём, кг (необязательно)</label>
      <input class="field" id="lstAvail" type="number" min="1" step="1" />
      <label for="lstDesc">Описание</label>
      <input class="field" id="lstDesc" type="text" maxlength="2000" />
      <p class="form-error" id="lstError"></p>
      <button class="btn btn-wine" type="submit">Опубликовать</button>
    </form>`);
  document.getElementById("listingForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const avail = document.getElementById("lstAvail").value;
    try {
      await api("/marketplace/listings", "POST", {
        waste_type: document.getElementById("lstType").value,
        price_per_kg: parseFloat(document.getElementById("lstPrice").value),
        min_kg: parseFloat(document.getElementById("lstMin").value) || 0,
        available_kg: avail ? parseFloat(avail) : null,
        description: document.getElementById("lstDesc").value.trim() || null,
      });
      closeModal();
      toast("Объявление опубликовано", "success");
      loadMarketplace();
    } catch (err) {
      document.getElementById("lstError").textContent = err.message;
    }
  });
});

async function loadMyOrders() {
  const box = document.getElementById("myOrdersList");
  try {
    const orders = await api("/marketplace/orders/my");
    box.innerHTML = orders.length
      ? orders.map((o) => {
          const actions = [];
          if (o.is_seller && o.status === "pending") {
            actions.push(`<button class="btn btn-wine btn-sm" data-ostatus="accepted" data-oid="${o.id}">Принять</button>`);
            actions.push(`<button class="btn btn-outline btn-sm" data-ostatus="cancelled" data-oid="${o.id}">Отклонить</button>`);
          }
          if (o.is_seller && o.status === "accepted") {
            actions.push(`<button class="btn btn-wine btn-sm" data-ostatus="completed" data-oid="${o.id}">Завершить</button>`);
          }
          if (!o.is_seller && o.status === "pending") {
            actions.push(`<button class="btn btn-outline btn-sm" data-ostatus="cancelled" data-oid="${o.id}">Отменить</button>`);
          }
          return `
            <div class="list-item">
              <span><strong>Заказ #${o.id}</strong> · ${esc(WASTE_LABELS[o.waste_type] || o.waste_type)} · ${esc(o.quantity_kg)} кг · ${esc(o.total_price)} ₸
                <br /><span class="meta">${o.is_seller ? "Вы продавец" : "Вы покупатель"} · ${esc((o.created_at || "").slice(0, 10))}</span></span>
              <span style="display:flex;gap:.4rem;align-items:center">
                <span class="status-chip ${o.status === "completed" ? "ok" : o.status === "cancelled" ? "warn" : ""}">${esc(ORDER_STATUS_LABELS[o.status] || o.status)}</span>
                ${actions.join("")}
              </span>
            </div>`;
        }).join("")
      : `<p class="meta">Заказов пока нет</p>`;
    box.querySelectorAll("[data-ostatus]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/marketplace/orders/${btn.dataset.oid}/status`, "PUT", { status: btn.dataset.ostatus });
          toast("Статус заказа обновлён", "success");
          loadMyOrders();
          loadMarketplace();
        } catch (err) { toast(err.message, "error"); }
      })
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

/* ================= Старт ================= */

(async function init() {
  renderHeader();
  if (state.token) {
    try {
      state.user = await api("/auth/me");
      renderHeader();
    } catch (_) {
      setSession(null, null);
    }
  }
})();
