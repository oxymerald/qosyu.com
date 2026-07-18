"use strict";

/* ================= Утилиты ================= */

const API_BASE = "";

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
    throw new Error(t("toast.sessionExpired"));
  }
  if (!resp.ok) {
    let detail = `Error ${resp.status}`;
    try {
      const data = await resp.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) detail = data.detail[0].msg;
    } catch (_) {}
    const err = new Error(detail);
    err.status = resp.status;
    throw err;
  }
  if (resp.status === 204) return null;
  return resp.json();
}

const wasteLabel = (v) => t(`waste.${v}`) === `waste.${v}` ? v : t(`waste.${v}`);
const statusLabel = (v) => (t(`status.${v}`) === `status.${v}` ? v : t(`status.${v}`));
const orderStatusLabel = (v) => (t(`order.${v}`) === `order.${v}` ? v : t(`order.${v}`));

/* ================= Состояние ================= */

const state = {
  token: localStorage.getItem("qosyu_token") || null,
  user: null,
  map: null,
  markersLayer: null,
  zonesLayer: null,
  routeLayer: null,
  chatWs: null,
  chatPartnerId: null,
  chatPartnerName: null,
  leafletLoading: null,
};

function setSession(token, user) {
  state.token = token;
  state.user = user;
  if (token) localStorage.setItem("qosyu_token", token);
  else localStorage.removeItem("qosyu_token");
  renderHeader();
  updateRoleTabs();
}

/* ================= Ленивая загрузка Leaflet ================= */

function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (state.leafletLoading) return state.leafletLoading;
  state.leafletLoading = new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    css.integrity = "sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=";
    css.crossOrigin = "";
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
    js.integrity = "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=";
    js.crossOrigin = "";
    js.onload = () => resolve();
    js.onerror = () => reject(new Error("Leaflet failed to load"));
    document.body.appendChild(js);
  });
  return state.leafletLoading;
}

/* ================= Навигация ================= */

const landingPage = document.getElementById("landingPage");
const cabinetPage = document.getElementById("cabinetPage");
const mainFooter = document.getElementById("mainFooter");
const mainNav = document.getElementById("mainNav");

function showLanding() {
  landingPage.classList.remove("hidden");
  mainFooter.classList.remove("hidden");
  cabinetPage.classList.add("hidden");
  closeChatSocket();
}

async function showCabinet() {
  if (!state.user) { openLoginModal(); return; }
  landingPage.classList.add("hidden");
  mainFooter.classList.add("hidden");
  cabinetPage.classList.remove("hidden");
  updateRoleTabs();
  activateTab("map");
  await initMap();
  renderCabinetSidebar();
  loadMapData();
  refreshUnreadBadge();
}

document.getElementById("brandLink").addEventListener("click", (e) => {
  if (!cabinetPage.classList.contains("hidden")) { e.preventDefault(); showLanding(); }
});

/* ================= Мобильное меню ================= */

const navToggle = document.getElementById("navToggle");
navToggle.addEventListener("click", () => {
  const open = mainNav.classList.toggle("nav-open");
  navToggle.classList.toggle("active", open);
  navToggle.setAttribute("aria-expanded", String(open));
});
mainNav.addEventListener("click", (e) => {
  if (e.target.tagName === "A") {
    mainNav.classList.remove("nav-open");
    navToggle.classList.remove("active");
    navToggle.setAttribute("aria-expanded", "false");
  }
});

/* ================= Язык ================= */

const langSwitch = document.getElementById("langSwitch");
function markActiveLang() {
  langSwitch.querySelectorAll("[data-lang]").forEach((b) =>
    b.classList.toggle("lang-active", b.dataset.lang === getLang())
  );
}
langSwitch.addEventListener("click", (e) => {
  const lang = e.target.closest("[data-lang]")?.dataset.lang;
  if (lang) { setLang(lang); markActiveLang(); }
});
document.addEventListener("langchange", () => {
  renderHeader();
  if (!cabinetPage.classList.contains("hidden")) {
    renderCabinetSidebar();
    const active = document.querySelector(".tab-btn.tab-active")?.dataset.tab;
    if (active) activateTab(active);
  }
});

/* ================= Шапка ================= */

function renderHeader() {
  const box = document.getElementById("headerActions");
  if (!state.user) {
    box.innerHTML = `
      <button class="btn btn-outline btn-sm" data-hdr="login">${esc(t("header.login"))}</button>
      <button class="btn btn-wine btn-sm" data-hdr="register">${esc(t("header.register"))}</button>`;
  } else {
    box.innerHTML = `
      <span class="header-user"><strong>${esc(state.user.company_name || state.user.email)}</strong></span>
      <button class="btn btn-wine btn-sm" data-hdr="cabinet">${esc(t("header.cabinet"))}</button>
      <button class="btn btn-outline btn-sm" data-hdr="logout">${esc(t("header.logout"))}</button>`;
  }
}

document.getElementById("headerActions").addEventListener("click", (e) => {
  const action = e.target.closest("[data-hdr]")?.dataset.hdr;
  if (action === "login") openLoginModal();
  if (action === "register") openRegisterModal();
  if (action === "cabinet") showCabinet();
  if (action === "logout") { setSession(null, null); showLanding(); toast(t("toast.loggedOut")); }
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
    <h3>${esc(t("modal.loginTitle"))}</h3>
    <form id="loginForm">
      <label for="loginEmail">${esc(t("modal.email"))}</label>
      <input class="field" id="loginEmail" type="email" required autocomplete="email" />
      <label for="loginPassword">${esc(t("modal.password"))}</label>
      <input class="field" id="loginPassword" type="password" required autocomplete="current-password" />
      <p class="form-error" id="loginError"></p>
      <button class="btn btn-wine" type="submit">${esc(t("modal.loginBtn"))}</button>
    </form>
    <button class="modal-switch" id="toRegister">${esc(t("modal.toRegister"))}</button>`);
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
      toast(`${t("toast.welcome")}, ${data.user.company_name || data.user.email}!`, "success");
      showCabinet();
    } catch (err) {
      errorBox.textContent = err.message;
    }
  });
}

function openRegisterModal() {
  openModal(`
    <h3>${esc(t("modal.registerTitle"))}</h3>
    <form id="regForm">
      <label for="regCompany">${esc(t("modal.company"))}</label>
      <input class="field" id="regCompany" type="text" required minlength="2" maxlength="120" />
      <label for="regEmail">${esc(t("modal.email"))}</label>
      <input class="field" id="regEmail" type="email" required autocomplete="email" />
      <label for="regPassword">${esc(t("modal.passwordHint"))}</label>
      <input class="field" id="regPassword" type="password" required minlength="8" autocomplete="new-password" />
      <label for="regRole">${esc(t("modal.whoAreYou"))}</label>
      <select class="field" id="regRole">
        <option value="sme">${esc(t("modal.roleSme"))}</option>
        <option value="recycler">${esc(t("modal.roleRecycler"))}</option>
      </select>
      <p class="form-error" id="regError"></p>
      <button class="btn btn-wine" type="submit">${esc(t("modal.createAccount"))}</button>
    </form>
    <button class="modal-switch" id="toLogin">${esc(t("modal.toLogin"))}</button>`);
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
      toast(t("toast.accountCreated"), "success");
      showCabinet();
    } catch (err) {
      errorBox.textContent = err.message;
    }
  });
}

/* ================= Политики ================= */

document.getElementById("privacyLink").addEventListener("click", (e) => {
  e.preventDefault();
  openModal(`<h3>${esc(t("footer.privacy"))}</h3><div class="policy-text">
    <p>QOSYU собирает минимально необходимые данные: email, название компании и координаты точек сбора вторсырья.</p>
    <p>Пароли хранятся только в виде необратимого хэша (bcrypt). Данные не передаются третьим лицам и используются исключительно для организации вывоза вторсырья и формирования ESG-отчётности.</p></div>`);
});
document.getElementById("termsLink").addEventListener("click", (e) => {
  e.preventDefault();
  openModal(`<h3>${esc(t("footer.terms"))}</h3><div class="policy-text">
    <p>Использование сервиса означает согласие с условиями. Пользователь несёт ответственность за достоверность информации в заявках.</p>
    <p>Платформа выступает координатором первой мили: объединяет заявки и строит маршруты, не осуществляя перевозку самостоятельно.</p></div>`);
});

/* ================= Вкладки кабинета ================= */

const panes = {
  map: "pane-map",
  requests: "pane-requests",
  chat: "pane-chat",
  market: "pane-market",
  assistant: "pane-assistant",
  admin: "pane-admin",
};

function updateRoleTabs() {
  const isAdmin = state.user?.role === "admin";
  document.getElementById("tabAdminBtn").classList.toggle("hidden", !isAdmin);
  // AI-помощник показываем всем авторизованным (виджет сам сообщит, если ключ не задан)
  document.getElementById("tabAssistantBtn").classList.toggle("hidden", !state.user);
}

function activateTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("tab-active", b.dataset.tab === name));
  Object.entries(panes).forEach(([key, id]) =>
    document.getElementById(id).classList.toggle("hidden", key !== name)
  );
  if (name === "map" && state.map) setTimeout(() => state.map.invalidateSize(), 60);
  if (name === "requests") loadRequestsHistory();
  if (name === "chat") loadChatPartners();
  if (name === "market") { loadMarketplace(); loadMyOrders(); }
  if (name === "assistant") initAssistant();
  if (name === "admin") loadAdmin();
}

document.getElementById("cabinetTabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".tab-btn")?.dataset.tab;
  if (tab) activateTab(tab);
});

/* ================= Карта ================= */

async function initMap() {
  if (state.map) return;
  await loadLeaflet();
  state.map = L.map("cabinetMap").setView([47.1167, 51.8833], 12);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    maxZoom: 19,
  }).addTo(state.map);
  state.markersLayer = L.layerGroup().addTo(state.map);
  state.zonesLayer = L.layerGroup().addTo(state.map);
  state.routeLayer = L.layerGroup().addTo(state.map);
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
          .bindPopup(`#${r.id} · ${esc(wasteLabel(r.waste_type))} — ${esc(r.weight_kg)} кг`)
          .addTo(state.markersLayer);
      });
    } catch (_) {}
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
        .bindPopup(`#${z.id} · ${z.request_count} · ${esc(z.total_weight_kg)} кг`)
        .addTo(state.zonesLayer);
    });
  } catch (_) {}
}

/* ================= Боковая панель кабинета ================= */

function renderCabinetSidebar() {
  if (!state.user) return;
  const userCard = document.getElementById("cabinetUserCard");
  const roleLabel = state.user.role === "sme" ? t("benefit.business") : state.user.role === "recycler" ? t("benefit.recycler") : "Admin";
  userCard.innerHTML = `<strong>${esc(state.user.company_name || state.user.email)}</strong><span class="role-chip">${esc(roleLabel)}</span>`;

  const box = document.getElementById("cabinetActions");
  if (state.user.role === "sme") {
    box.innerHTML = `
      <div class="side-block">
        <h3>${esc(t("cab.newRequest"))}</h3>
        <label for="reqType">${esc(t("cab.wasteType"))}</label>
        <select class="field" id="reqType">
          <option value="cardboard">${esc(t("waste.cardboard"))}</option>
          <option value="plastic">${esc(t("waste.plastic"))}</option>
          <option value="glass">${esc(t("waste.glass"))}</option>
          <option value="metal">${esc(t("waste.metal"))}</option>
        </select>
        <label for="reqWeight">${esc(t("cab.weight"))}</label>
        <input class="field" id="reqWeight" type="number" min="1" max="50000" step="0.5" placeholder="15" />
        <p class="list-item meta" style="display:block">${esc(t("cab.pointHint"))}</p>
        <button class="btn btn-wine" id="createReqBtn">${esc(t("cab.createRequest"))}</button>
      </div>
      <div class="side-block">
        <h3>${esc(t("cab.myRequests"))}</h3>
        <div id="sideRequestsList" class="side-stack"></div>
      </div>
      <div class="side-block">
        <h3>${esc(t("cab.esgReport"))}</h3>
        <div id="sideEsg"></div>
      </div>
      <div class="side-block" id="telegramBlock"></div>`;
    document.getElementById("createReqBtn").addEventListener("click", createRequestFromMap);
    loadSmeSidebar();
    renderTelegramBlock();
  } else if (state.user.role === "recycler") {
    box.innerHTML = `
      <div class="side-block">
        <h3>${esc(t("cab.openZones"))}</h3>
        <div id="sideOpenZones" class="side-stack"></div>
        <button class="btn btn-outline" id="genZonesBtn">${esc(t("cab.genZones"))}</button>
      </div>
      <div class="side-block">
        <h3>${esc(t("cab.myZones"))}</h3>
        <div id="sideMyZones" class="side-stack"></div>
      </div>
      <div class="side-block" id="telegramBlock"></div>`;
    document.getElementById("genZonesBtn").addEventListener("click", async () => {
      try {
        const res = await api("/clustering/generate-zones", "POST");
        toast(res.message, "success");
        await loadRecyclerSidebar();
        await loadMapData();
      } catch (err) { toast(err.message, "error"); }
    });
    loadRecyclerSidebar();
    renderTelegramBlock();
  } else {
    box.innerHTML = `<div class="side-block"><p class="meta">${esc(t("admin.title"))} → ${esc(t("tab.admin"))}</p></div>`;
  }
}

/* ================= Telegram-привязка ================= */

function renderTelegramBlock() {
  const block = document.getElementById("telegramBlock");
  if (!block) return;
  if (state.user.telegram_linked) {
    block.innerHTML = `<h3>${esc(t("cab.telegram"))}</h3><p class="status-chip ok" style="font-size:.9rem">${esc(t("cab.telegram.linked"))}</p>`;
    return;
  }
  block.innerHTML = `
    <h3>${esc(t("cab.telegram"))}</h3>
    <p class="meta" style="margin-bottom:.6rem">${esc(t("cab.telegram.hint"))}</p>
    <button class="btn btn-outline" id="tgLinkBtn">${esc(t("cab.telegram.btn"))}</button>`;
  document.getElementById("tgLinkBtn").addEventListener("click", async () => {
    try {
      const { code } = await api("/auth/telegram-link-code", "POST");
      openModal(`
        <h3>${esc(t("modal.tgTitle"))}</h3>
        <div class="policy-text">
          <p>${esc(t("modal.tgStep1"))} <strong>@QosyuBot</strong></p>
          <p>${esc(t("modal.tgStep2"))}</p>
          <div class="tg-code">/link ${esc(code)}</div>
          <p class="meta">${esc(t("modal.tgCodeHint"))}</p>
        </div>`);
    } catch (err) { toast(err.message, "error"); }
  });
}

async function createRequestFromMap() {
  const weight = parseFloat(document.getElementById("reqWeight").value);
  if (!weight || weight <= 0) { toast(t("toast.needWeight"), "error"); return; }
  const center = state.map.getCenter();
  try {
    await api("/requests/create", "POST", {
      waste_type: document.getElementById("reqType").value,
      weight_kg: weight,
      latitude: center.lat,
      longitude: center.lng,
    });
    toast(t("toast.requestCreated"), "success");
    document.getElementById("reqWeight").value = "";
    await loadSmeSidebar();
    await loadMapData();
  } catch (err) { toast(err.message, "error"); }
}

async function loadSmeSidebar() {
  try {
    const reqs = await api("/requests/my?limit=8");
    document.getElementById("sideRequestsList").innerHTML = reqs.length
      ? reqs.map((r) => `
          <div class="list-item">
            <span>${esc(wasteLabel(r.waste_type))} · ${esc(r.weight_kg)} кг</span>
            <span class="status-chip ${r.status === "collected" || r.status === "verified" ? "ok" : ""}">${esc(statusLabel(r.status))}</span>
          </div>`).join("")
      : `<p class="meta">${esc(t("cab.noRequests"))}</p>`;
    const eng = await api("/analytics/esg/sme");
    document.getElementById("sideEsg").innerHTML = `
      <div class="list-item"><span>${esc(t("cab.esg.recycled"))}</span><strong>${esc(eng.total_recycled_kg)} кг</strong></div>
      <div class="list-item"><span>${esc(t("cab.esg.co2"))}</span><strong>${esc(eng.co2_saved_kg)} кг</strong></div>
      <div class="list-item"><span>${esc(t("cab.esg.trees"))}</span><strong>${esc(eng.equivalent_trees)}</strong></div>`;
  } catch (err) { toast(err.message, "error"); }
}

async function loadRecyclerSidebar() {
  try {
    const open = await api("/clustering/zones/open");
    const openBox = document.getElementById("sideOpenZones");
    openBox.innerHTML = open.length
      ? open.map((z) => `
          <div class="list-item">
            <span>#${z.id}<br /><span class="meta">${z.request_count} · ${esc(z.total_weight_kg)} кг</span></span>
            <button class="btn btn-outline btn-sm" data-assign="${z.id}">${esc(t("cab.take"))}</button>
          </div>`).join("")
      : `<p class="meta">${esc(t("cab.noOpenZones"))}</p>`;
    openBox.querySelectorAll("[data-assign]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/recycler/zones/${btn.dataset.assign}/assign`, "POST");
          toast(t("toast.zoneTaken"), "success");
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
            <span>#${z.id}<br /><span class="meta">${z.request_count} · ${esc(z.total_weight_kg)} кг</span></span>
            <span style="display:flex;gap:.35rem">
              <button class="btn btn-outline btn-sm" data-route="${z.id}">${esc(t("cab.route"))}</button>
              <button class="btn btn-wine btn-sm" data-complete="${z.id}">${esc(t("cab.complete"))}</button>
            </span>
          </div>`).join("")
      : `<p class="meta">${esc(t("cab.noMyZones"))}</p>`;
    myBox.querySelectorAll("[data-complete]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/recycler/zones/${btn.dataset.complete}/complete`, "POST");
          toast(t("toast.zoneDone"), "success");
          clearRoute();
          await loadRecyclerSidebar();
          await loadMapData();
        } catch (err) { toast(err.message, "error"); }
      })
    );
    myBox.querySelectorAll("[data-route]").forEach((btn) =>
      btn.addEventListener("click", () => showZoneRoute(btn.dataset.route))
    );
  } catch (err) { toast(err.message, "error"); }
}

/* ================= Маршрут ================= */

function clearRoute() {
  if (state.routeLayer) state.routeLayer.clearLayers();
  document.getElementById("routePanel").classList.add("hidden");
}

async function showZoneRoute(zoneId) {
  try {
    const route = await api(`/recycler/zones/${zoneId}/route`);
    activateTab("map");
    await initMap();
    state.routeLayer.clearLayers();

    if (route.geometry?.length) {
      L.polyline(route.geometry, { color: "#990011", weight: 4, opacity: 0.85 }).addTo(state.routeLayer);
    }
    // Депо
    L.marker([route.start.lat, route.start.lon], {
      icon: L.divIcon({ className: "route-depot", html: "★", iconSize: [26, 26] }),
    }).bindPopup("Депо").addTo(state.routeLayer);
    // Точки по порядку
    route.stops.forEach((s) => {
      L.marker([s.lat, s.lon], {
        icon: L.divIcon({ className: "route-stop", html: String(s.order), iconSize: [26, 26] }),
      })
        .bindPopup(`${s.order}. ${esc(s.company || "")}<br>${esc(wasteLabel(s.waste_type))} — ${esc(s.weight_kg)} кг`)
        .addTo(state.routeLayer);
    });
    const bounds = L.latLngBounds(route.geometry.length ? route.geometry : route.stops.map((s) => [s.lat, s.lon]));
    if (bounds.isValid()) state.map.fitBounds(bounds, { padding: [40, 40] });

    const srcLabel = route.source === "osrm" ? t("route.source.osrm") : t("route.source.heuristic");
    const panel = document.getElementById("routePanel");
    panel.innerHTML = `
      <div class="route-head">
        <strong>${esc(t("route.title"))} #${esc(route.zone_id)}</strong>
        <button id="routeClose" aria-label="close">×</button>
      </div>
      <div class="route-metrics">
        <div><span>${esc(t("route.distance"))}</span><b>${esc(route.distance_km)} ${esc(t("common.km"))}</b></div>
        <div><span>${esc(t("route.eta"))}</span><b>${esc(route.duration_min)} ${esc(t("common.min"))}</b></div>
        <div><span>${esc(t("route.stops"))}</span><b>${route.stops.length}</b></div>
      </div>
      <ol class="route-list">
        ${route.stops.map((s) => `<li><span class="route-num">${s.order}</span> ${esc(s.company || "—")} · ${esc(wasteLabel(s.waste_type))} ${esc(s.weight_kg)} кг</li>`).join("")}
      </ol>
      <p class="meta route-src">${esc(srcLabel)}</p>`;
    panel.classList.remove("hidden");
    document.getElementById("routeClose").addEventListener("click", clearRoute);
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
            <span><strong>${esc(wasteLabel(r.waste_type))}</strong> — ${esc(r.weight_kg)} кг
              <br /><span class="meta">${esc((r.created_at || "").slice(0, 10))}</span></span>
            <span style="display:flex;gap:.5rem;align-items:center">
              <span class="status-chip ${r.status === "collected" || r.status === "verified" ? "ok" : ""}">${esc(statusLabel(r.status))}</span>
              ${r.status === "pending" ? `<button class="btn btn-outline btn-sm" data-cancel="${r.id}">${esc(t("cab.cancel"))}</button>` : ""}
            </span>
          </div>`).join("")
      : `<p class="meta">${esc(t("cab.noRequests"))}</p>`;
    box.querySelectorAll("[data-cancel]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/requests/${btn.dataset.cancel}`, "DELETE");
          toast(t("toast.requestCancelled"));
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
  } catch (_) {}
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
              ${item.existing ? `<br /><span class="meta">${esc((item.last_message || "").slice(0, 40))}</span>` : `<br /><span class="meta">${esc(t("chat.startDialog"))}</span>`}
            </span>
            ${item.unread ? `<span class="badge">${item.unread}</span>` : ""}
          </button>`).join("")
      : `<p class="meta">${esc(t("chat.noPartners"))}</p>`;
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
  const time = msg.time ? new Date(msg.time).toLocaleString(getLang(), { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" }) : "";
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
    } catch (_) {}
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
              <span class="type">${esc(wasteLabel(l.waste_type))}</span>
              <span class="price">${esc(l.price_per_kg)} ₸/кг</span>
            </div>
            <p class="desc">${esc(l.description || t("market.noDesc"))}</p>
            <p class="meta">${esc(t("market.minLot"))}: ${esc(l.min_kg)} кг${l.available_kg != null ? ` · ${esc(t("market.available"))}: ${esc(l.available_kg)} кг` : ""}</p>
            ${l.user_id !== state.user.id
              ? `<button class="btn btn-wine btn-sm" data-order="${l.id}" data-min="${esc(l.min_kg)}">${esc(t("market.order"))}</button>`
              : `<p class="meta">${esc(t("market.yourListing"))}</p>`}
          </article>`).join("")
      : `<p class="meta">${esc(t("market.noListings"))}</p>`;
    box.querySelectorAll("[data-order]").forEach((btn) =>
      btn.addEventListener("click", () => openOrderModal(parseInt(btn.dataset.order, 10), parseFloat(btn.dataset.min)))
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

function openOrderModal(listingId, minKg) {
  openModal(`
    <h3>${esc(t("modal.orderTitle"))}</h3>
    <form id="orderForm">
      <label for="orderQty">${esc(t("modal.qty"))} (${esc(t("market.minLot"))} ${esc(minKg || 0)})</label>
      <input class="field" id="orderQty" type="number" min="${esc(minKg || 0.1)}" step="0.5" required />
      <p class="form-error" id="orderError"></p>
      <button class="btn btn-wine" type="submit">${esc(t("modal.sendOrder"))}</button>
    </form>`);
  document.getElementById("orderForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/marketplace/orders", "POST", {
        listing_id: listingId,
        quantity_kg: parseFloat(document.getElementById("orderQty").value),
      });
      closeModal();
      toast(`${t("toast.orderPlaced")} ${res.total} ₸`, "success");
      loadMarketplace();
      loadMyOrders();
    } catch (err) {
      document.getElementById("orderError").textContent = err.message;
    }
  });
}

document.getElementById("addListingBtn").addEventListener("click", () => {
  openModal(`
    <h3>${esc(t("modal.listingTitle"))}</h3>
    <form id="listingForm">
      <label for="lstType">${esc(t("cab.wasteType"))}</label>
      <select class="field" id="lstType">
        <option value="cardboard">${esc(t("waste.cardboard"))}</option>
        <option value="plastic">${esc(t("waste.plastic"))}</option>
        <option value="glass">${esc(t("waste.glass"))}</option>
        <option value="metal">${esc(t("waste.metal"))}</option>
      </select>
      <label for="lstPrice">${esc(t("modal.pricePerKg"))}</label>
      <input class="field" id="lstPrice" type="number" min="1" step="1" required />
      <label for="lstMin">${esc(t("modal.minLot"))}</label>
      <input class="field" id="lstMin" type="number" min="0" step="1" value="0" />
      <label for="lstAvail">${esc(t("modal.availVol"))}</label>
      <input class="field" id="lstAvail" type="number" min="1" step="1" />
      <label for="lstDesc">${esc(t("modal.description"))}</label>
      <input class="field" id="lstDesc" type="text" maxlength="2000" />
      <p class="form-error" id="lstError"></p>
      <button class="btn btn-wine" type="submit">${esc(t("modal.publish"))}</button>
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
      toast(t("toast.listingPublished"), "success");
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
            actions.push(`<button class="btn btn-wine btn-sm" data-ostatus="accepted" data-oid="${o.id}">${esc(t("order.accept"))}</button>`);
            actions.push(`<button class="btn btn-outline btn-sm" data-ostatus="cancelled" data-oid="${o.id}">${esc(t("order.reject"))}</button>`);
          }
          if (o.is_seller && o.status === "accepted") {
            actions.push(`<button class="btn btn-wine btn-sm" data-ostatus="completed" data-oid="${o.id}">${esc(t("order.complete"))}</button>`);
          }
          if (!o.is_seller && o.status === "pending") {
            actions.push(`<button class="btn btn-outline btn-sm" data-ostatus="cancelled" data-oid="${o.id}">${esc(t("cab.cancel"))}</button>`);
          }
          return `
            <div class="list-item">
              <span><strong>#${o.id}</strong> · ${esc(wasteLabel(o.waste_type))} · ${esc(o.quantity_kg)} кг · ${esc(o.total_price)} ₸
                <br /><span class="meta">${o.is_seller ? esc(t("market.seller")) : esc(t("market.buyer"))} · ${esc((o.created_at || "").slice(0, 10))}</span></span>
              <span style="display:flex;gap:.4rem;align-items:center">
                <span class="status-chip ${o.status === "completed" ? "ok" : o.status === "cancelled" ? "warn" : ""}">${esc(orderStatusLabel(o.status))}</span>
                ${actions.join("")}
              </span>
            </div>`;
        }).join("")
      : `<p class="meta">${esc(t("market.noOrders"))}</p>`;
    box.querySelectorAll("[data-ostatus]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          await api(`/marketplace/orders/${btn.dataset.oid}/status`, "PUT", { status: btn.dataset.ostatus });
          toast(t("toast.orderUpdated"), "success");
          loadMyOrders();
          loadMarketplace();
        } catch (err) { toast(err.message, "error"); }
      })
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

/* ================= AI-помощник ================= */

let assistantReady = false;
async function initAssistant() {
  const log = document.getElementById("assistantLog");
  if (assistantReady) return;
  assistantReady = true;
  try {
    const status = await api("/ai/status");
    if (!status.available) {
      log.innerHTML = `<div class="assistant-msg bot">${esc(t("assistant.unavailable"))}</div>`;
      document.getElementById("assistantInput").disabled = true;
      return;
    }
  } catch (_) {}
  log.innerHTML = `<div class="assistant-msg bot">${esc(t("assistant.greeting"))}</div>`;
}

const assistantHistory = [];
document.getElementById("assistantForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("assistantInput");
  const text = input.value.trim();
  if (!text) return;
  const log = document.getElementById("assistantLog");
  log.insertAdjacentHTML("beforeend", `<div class="assistant-msg user">${esc(text)}</div>`);
  input.value = "";
  log.scrollTop = log.scrollHeight;
  const typing = document.createElement("div");
  typing.className = "assistant-msg bot typing";
  typing.textContent = "…";
  log.appendChild(typing);
  log.scrollTop = log.scrollHeight;
  try {
    const res = await api("/ai/assistant", "POST", { message: text, history: assistantHistory.slice(-8) });
    typing.remove();
    log.insertAdjacentHTML("beforeend", `<div class="assistant-msg bot">${esc(res.reply)}</div>`);
    assistantHistory.push({ role: "user", content: text }, { role: "assistant", content: res.reply });
  } catch (err) {
    typing.remove();
    log.insertAdjacentHTML("beforeend", `<div class="assistant-msg bot">${esc(err.message)}</div>`);
  }
  log.scrollTop = log.scrollHeight;
});

/* ================= Админ-панель ================= */

function barChart(items, valueKey, labelKey, unit) {
  const max = Math.max(...items.map((i) => i[valueKey]), 1);
  return `<div class="bar-chart">${items
    .map((i) => {
      const pct = Math.round((i[valueKey] / max) * 100);
      return `<div class="bar-row" title="${esc(i[labelKey])}: ${esc(i[valueKey])}${unit}">
        <span class="bar-label">${esc(i[labelKey])}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
        <span class="bar-val">${esc(i[valueKey])}</span>
      </div>`;
    })
    .join("")}</div>`;
}

async function loadAdmin() {
  try {
    const s = await api("/admin/stats");
    document.getElementById("adminStats").innerHTML = `
      <div class="admin-tile"><span class="tile-num">${s.users.total}</span><span class="tile-cap">${esc(t("admin.users"))}</span></div>
      <div class="admin-tile"><span class="tile-num">${s.users.recycler}</span><span class="tile-cap">${esc(t("admin.recyclers"))}</span></div>
      <div class="admin-tile"><span class="tile-num">${s.requests.total}</span><span class="tile-cap">${esc(t("admin.requestsTotal"))}</span></div>
      <div class="admin-tile"><span class="tile-num">${s.esg.collected_kg}</span><span class="tile-cap">${esc(t("admin.collected"))}</span></div>
      <div class="admin-tile"><span class="tile-num">${s.esg.co2_saved_kg}</span><span class="tile-cap">${esc(t("admin.co2"))}</span></div>
      <div class="admin-tile"><span class="tile-num">${s.zones.open}</span><span class="tile-cap">${esc(t("admin.openZones"))}</span></div>`;

    // Серия за 14 дней — SVG-линия
    document.getElementById("adminChartSeries").innerHTML = lineChartSVG(s.requests_series_14d);
    // Распределение по типам — бары
    const waste = s.waste_distribution.map((w) => ({ label: wasteLabel(w.waste_type), value: w.weight_kg }));
    document.getElementById("adminChartWaste").innerHTML = waste.length
      ? barChart(waste, "value", "label", " кг")
      : `<p class="meta">—</p>`;

    const insights = await api("/ai/insights");
    document.getElementById("adminInsights").innerHTML = insights.recommendations
      .map((r) => `<li>${esc(r)}</li>`)
      .join("");
  } catch (err) { toast(err.message, "error"); }
  loadAdminUsers();
}

function lineChartSVG(series) {
  const w = 560, h = 160, pad = 24;
  const counts = series.map((d) => d.count);
  const max = Math.max(...counts, 1);
  const stepX = (w - pad * 2) / Math.max(series.length - 1, 1);
  const points = series.map((d, i) => {
    const x = pad + i * stepX;
    const y = h - pad - (d.count / max) * (h - pad * 2);
    return [x, y];
  });
  const path = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${path} L${points[points.length - 1][0].toFixed(1)},${h - pad} L${pad},${h - pad} Z`;
  const dots = points.map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="#990011" />`).join("");
  const labels = series
    .map((d, i) => (i % 2 === 0 ? `<text x="${(pad + i * stepX).toFixed(1)}" y="${h - 6}" font-size="9" fill="#706A6B" text-anchor="middle">${d.date.slice(5)}</text>` : ""))
    .join("");
  return `<svg viewBox="0 0 ${w} ${h}" class="line-chart" role="img">
    <path d="${area}" fill="#FBEEEE" />
    <path d="${path}" fill="none" stroke="#990011" stroke-width="2" />
    ${dots}${labels}
  </svg>`;
}

let adminSearchTimer = null;
document.getElementById("adminUserSearch").addEventListener("input", (e) => {
  clearTimeout(adminSearchTimer);
  const q = e.target.value.trim();
  adminSearchTimer = setTimeout(() => loadAdminUsers(q), 300);
});

async function loadAdminUsers(search = "") {
  const box = document.getElementById("adminUsersList");
  try {
    const users = await api(`/admin/users?limit=50${search ? `&search=${encodeURIComponent(search)}` : ""}`);
    box.innerHTML = users
      .map((u) => `
        <div class="list-item">
          <span><strong>${esc(u.company_name || u.email)}</strong> <span class="role-chip">${esc(u.role)}</span>
            ${u.telegram_linked ? "✈️" : ""}
            <br /><span class="meta">${esc(u.email)} · ${esc((u.created_at || "").slice(0, 10))}</span>
            ${!u.is_active ? `<br /><span class="status-chip warn">${esc(t("admin.blocked"))}</span>` : ""}</span>
          ${u.role !== "admin"
            ? `<button class="btn btn-sm ${u.is_active ? "btn-outline" : "btn-wine"}" data-toggle="${u.id}" data-active="${u.is_active ? "0" : "1"}">${u.is_active ? esc(t("admin.block")) : esc(t("admin.unblock"))}</button>`
            : ""}
        </div>`)
      .join("");
    box.querySelectorAll("[data-toggle]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        try {
          const activate = btn.dataset.active === "1";
          await api(`/admin/users/${btn.dataset.toggle}`, "PATCH", { is_active: activate });
          toast(activate ? t("toast.userUnblocked") : t("toast.userBlocked"), "success");
          loadAdminUsers(search);
        } catch (err) { toast(err.message, "error"); }
      })
    );
  } catch (err) { box.innerHTML = `<p class="meta">${esc(err.message)}</p>`; }
}

/* ================= Scroll-анимации ================= */

function initReveal() {
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const items = document.querySelectorAll(".reveal");
  if (reduce || !("IntersectionObserver" in window)) {
    items.forEach((el) => el.classList.add("revealed"));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("revealed");
          io.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.12 }
  );
  items.forEach((el) => io.observe(el));
}

/* ================= Старт ================= */

(async function init() {
  applyTranslations();
  markActiveLang();
  renderHeader();
  updateRoleTabs();
  initReveal();
  if (state.token) {
    try {
      state.user = await api("/auth/me");
      setSession(state.token, state.user);
    } catch (_) {
      setSession(null, null);
    }
  }
})();
