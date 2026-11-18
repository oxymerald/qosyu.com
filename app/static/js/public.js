"use strict";

const PUBLIC_TRANSLATIONS = {
  ru: {
    "meta.title":"QOSYU — исследовательский прототип сбора вторсырья",
    "meta.description":"QOSYU — исследовательский прототип сбора вторсырья от МСБ. Одиночные маршруты — API 2ГИС; многоадресная маршрутизация с ограничениями проверяется в тестовом контуре.",
    "public.sub":"Бизнес подаёт заявку на сбор вторсырья, переработчик видит заявки на карте. Одиночные дорожные маршруты в основном интерфейсе строятся через API 2ГИС.",
    "public.feature2p":"Одиночные дорожные маршруты работают через API 2ГИС. Многоадресный объезд с учётом массы и временных ограничений исследуется и проверяется в отдельном тестовом контуре.",
    "public.feature3p":"Gemini помогает получать сведения о доступных вам заявках. Построение дорожных маршрутов выполняет отдельный картографический сервис.",
    "public.step2p":"Переработчик выбирает заявки на карте и проверяет одиночный маршрут через 2ГИС. Многоадресный объезд с ограничениями проверяется отдельно в тестовом контуре.",
    "pilot.title":"Оставить заявку на пилот", "pilot.company":"Название заведения", "pilot.contact":"Контакт для связи", "pilot.comment":"Комментарий",
    "pilot.privacy":"Отправляя форму, вы передаёте эти данные для рассмотрения заявки и обратной связи. Подробнее:",
    "pilot.send":"Отправить заявку", "pilot.success":"Заявка сохранена. Спасибо за интерес к пилоту!",
    "pilot.error":"Не удалось сохранить заявку. Проверьте поля и попробуйте ещё раз.", "pilot.rateLimit":"Слишком много заявок. Повторите попытку через час.",
    "contacts.title":"Контакты",
    "demo.business":"Войти как тестовый бизнес", "demo.recycler":"Войти как переработчик",
    "demo.businessName":"Демо · бизнес", "demo.recyclerName":"Демо · переработчик", "demo.point":"Демо-точка",
    "demo.hint":"Быстрый демо-вход без регистрации. Вымышленные данные хранятся только в памяти вкладки и сбрасываются при её перезагрузке.",
    "demo.notice":"Демо-режим: тестовые данные, без реального вывоза. Маршрут на карте — условная схема, не дорожная навигация.",
    "demo.unavailable":"Это действие доступно в рабочем аккаунте. В демо можно создать заявку, принять зону и отметить её завершение.",
    "demo.ai":"В демо внешние ИИ-запросы отключены. Gemini работает с доступными данными после обычного входа.",
    "demo.zoneCount":"Создано демо-зон",
  },
  en: {
    "meta.title":"QOSYU — secondary-material collection research prototype",
    "meta.description":"QOSYU is an SME secondary-material collection research prototype. Single routes use the 2GIS API; constrained multi-stop routing is evaluated in a separate test environment.",
    "public.sub":"Businesses submit collection requests and recyclers view them on a map. The main interface uses the 2GIS API for single road routes.",
    "public.feature2p":"Single road routes use the 2GIS API. Multi-stop routing with weight and time constraints is researched and evaluated in a separate test environment.",
    "public.feature3p":"Gemini helps retrieve information about requests you may access. A separate mapping service builds road routes.",
    "public.step2p":"The recycler selects requests on the map and checks a single route with 2GIS. Constrained multi-stop routing is evaluated separately in a test environment.",
    "pilot.title":"Apply for the pilot", "pilot.company":"Establishment name", "pilot.contact":"Contact details", "pilot.comment":"Comment",
    "pilot.privacy":"Submitting this form shares these details for reviewing your enquiry and responding. Learn more:",
    "pilot.send":"Send enquiry", "pilot.success":"Your enquiry has been saved. Thank you for your interest!",
    "pilot.error":"Your enquiry could not be saved. Check the fields and try again.", "pilot.rateLimit":"Too many enquiries. Please try again in an hour.",
    "contacts.title":"Contacts",
    "demo.business":"Enter as a test business", "demo.recycler":"Enter as a recycler",
    "demo.businessName":"Demo · business", "demo.recyclerName":"Demo · recycler", "demo.point":"Demo stop",
    "demo.hint":"Quick demo access without registration. Fictional data stay in tab memory and reset when the tab reloads.",
    "demo.notice":"Demo mode: test data, no physical collection. The map route is a schematic, not road navigation.",
    "demo.unavailable":"This action requires a regular account. The demo lets you create requests, accept a zone and mark it complete.",
    "demo.ai":"External AI requests are disabled in the demo. Gemini can access permitted data after regular sign-in.",
    "demo.zoneCount":"Demo zones created",
  },
  kk: {
    "meta.title":"QOSYU — қайталама шикізатты жинаудың зерттеу прототипі",
    "meta.description":"QOSYU — ШОБ-тан қайталама шикізат жинаудың зерттеу прототипі. Жеке бағыттар 2ГИС API арқылы құрылады, шектеулері бар көпнүктелі бағыттар бөлек сынақ ортасында тексеріледі.",
    "public.sub":"Бизнес шикізат жинауға өтінім береді, өңдеуші оны картадан көреді. Негізгі интерфейсте жеке жол бағыттары 2ГИС API арқылы құрылады.",
    "public.feature2p":"Жеке жол бағыттары 2ГИС API арқылы құрылады. Салмақ пен уақыт шектеулері бар көпнүктелі бағыттар бөлек сынақ ортасында зерттеліп, тексеріледі.",
    "public.feature3p":"Gemini өзіңізге қолжетімді өтінімдер туралы мәлімет алуға көмектеседі. Жол бағыттарын бөлек картографиялық сервис құрады.",
    "public.step2p":"Өңдеуші картадан өтінімдерді таңдап, 2ГИС арқылы жеке бағытты тексереді. Шектеулері бар көпнүктелі бағыт бөлек сынақ ортасында тексеріледі.",
    "pilot.title":"Пилотқа өтінім беру", "pilot.company":"Мекеме атауы", "pilot.contact":"Байланыс дерегі", "pilot.comment":"Түсініктеме",
    "pilot.privacy":"Форманы жіберу арқылы деректерді өтінімді қарау және кері байланыс үшін бересіз. Толығырақ:",
    "pilot.send":"Өтінімді жіберу", "pilot.success":"Өтінім сақталды. Қызығушылығыңызға рақмет!",
    "pilot.error":"Өтінім сақталмады. Өрістерді тексеріп, қайталап көріңіз.", "pilot.rateLimit":"Өтінім тым көп. Бір сағаттан кейін қайталап көріңіз.",
    "contacts.title":"Байланыс",
    "demo.business":"Сынақ бизнесі ретінде кіру", "demo.recycler":"Өңдеуші ретінде кіру",
    "demo.businessName":"Демо · бизнес", "demo.recyclerName":"Демо · өңдеуші", "demo.point":"Демо-нүкте",
    "demo.hint":"Тіркелусіз жылдам демо-кіру. Ойдан шығарылған деректер қойынды жадында сақталады және қайта жүктегенде өшеді.",
    "demo.notice":"Демо-режим: сынақ деректері, нақты тасымалдау жоқ. Картадағы бағыт — шартты сызба, жол навигациясы емес.",
    "demo.unavailable":"Бұл әрекетке жұмыс тіркелгісі қажет. Демода өтінім жасап, аймақты қабылдап, аяқталғанын белгілеуге болады.",
    "demo.ai":"Демода сыртқы ЖИ сұраулары өшірілген. Gemini қалыпты кіруден кейін рұқсат етілген деректермен жұмыс істейді.",
    "demo.zoneCount":"Жасалған демо-аймақтар",
  },
};
for(const lang of SUPPORTED_LANGS) Object.assign(TRANSLATIONS[lang],PUBLIC_TRANSLATIONS[lang]);

function updatePublicMetadata() {
  const locationAttribute = `data-contact-location-${getLang()}`;
  document.querySelectorAll(`[${locationAttribute}]`).forEach(element => {
    element.textContent = element.getAttribute(locationAttribute);
  });
  document.title=t("meta.title");
  document.querySelector('meta[name="description"]').content=t("meta.description");
  for(const [key,value] of Object.entries({title:t("meta.title"),description:t("meta.description"),
    locale:{ru:"ru_RU",en:"en_US",kk:"kk_KZ"}[getLang()]})) {
    const tag=document.querySelector(`meta[property="og:${key}"]`);
    if(tag) tag.content=value;
  }
  const url=new URL(location.href);
  if(getLang()==="ru") url.searchParams.delete("lang");else url.searchParams.set("lang",getLang());
  const canonical=`https://qosyu.com/${getLang()==="ru"?"":`?lang=${getLang()}`}`;
  document.querySelector('link[rel="canonical"]').href=canonical;
  document.querySelector('meta[property="og:url"]').content=canonical;
  history.replaceState(null,"",url);
  for(const kind of ["privacy","terms"]) document.getElementById(`${kind}Link`).href=`/${kind}?lang=${getLang()}`;
}

function openPilotModal() {
  openModal(`<h3>${esc(t("pilot.title"))}</h3><form id="pilotForm">
    <label for="pilotCompany">${esc(t("pilot.company"))}</label>
    <input class="field" id="pilotCompany" name="company_name" required minlength="2" maxlength="120" autocomplete="organization" />
    <label for="pilotContact">${esc(t("pilot.contact"))}</label>
    <input class="field" id="pilotContact" name="contact" required minlength="3" maxlength="160" />
    <label for="pilotComment">${esc(t("pilot.comment"))}</label>
    <textarea class="field" id="pilotComment" name="comment" maxlength="2000" rows="3"></textarea>
    <p class="meta">${esc(t("pilot.privacy"))} <a href="/privacy?lang=${getLang()}" target="_blank" rel="noopener">${esc(t("footer.privacy"))}</a></p>
    <p class="form-error" id="pilotError" role="alert"></p>
    <button class="btn btn-wine" type="submit">${esc(t("pilot.send"))}</button></form>`);
  document.getElementById("pilotForm").addEventListener("submit",async e=>{
    e.preventDefault();
    const button=e.currentTarget.querySelector('button[type="submit"]'), error=document.getElementById("pilotError");
    button.disabled=true;error.textContent="";
    try {
      await api("/public/pilot","POST",{company_name:document.getElementById("pilotCompany").value.trim(),
        contact:document.getElementById("pilotContact").value.trim(),comment:document.getElementById("pilotComment").value.trim(),language:getLang()});
      openModal(`<h3>${esc(t("pilot.title"))}</h3><p role="status">${esc(t("pilot.success"))}</p>`);
    } catch(err) {
      error.textContent=err.status===429?t("pilot.rateLimit"):t("pilot.error");
    } finally {button.disabled=false;}
  });
}

function demoButtons() {
  return `<div class="demo-options"><p class="meta">${esc(t("demo.hint"))}</p>
    <button class="btn btn-outline" type="button" data-demo="sme">${esc(t("demo.business"))}</button>
    <button class="btn btn-outline" type="button" data-demo="recycler">${esc(t("demo.recycler"))}</button></div>`;
}

function bindDemoButtons() {
  modalContent.querySelectorAll("[data-demo]").forEach(button=>button.addEventListener("click",()=>{
    const role=button.dataset.demo;
    if(!["sme","recycler"].includes(role)) return;
    setSession(null,QosyuDemo.user(role));state.demo=role;
    document.getElementById("demoNotice").classList.remove("hidden");
    closeModal();showCabinet();toast(t("demo.notice"));
  }));
}
