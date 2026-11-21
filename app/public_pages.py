"""Server-rendered, crawlable metadata and legal pages for the three locales."""
import html
import re
from pathlib import Path

from config import settings

ROOT = Path(__file__).resolve().parent / "static"
ORIGIN = "https://qosyu.com"
COPY = {
    "ru": {
        "title": "QOSYU — исследовательский прототип сбора вторсырья",
        "description": "QOSYU — исследовательский прототип сбора вторсырья от МСБ. Одиночные маршруты — API 2ГИС; многоадресная маршрутизация с ограничениями проверяется в тестовом контуре.",
        "privacy": "Политика конфиденциальности", "terms": "Условия использования", "home": "На главную",
        "privacy_text": [
            "QOSYU обрабатывает email, название организации и данные учётной записи, а также адреса, координаты, массу, вид сырья и статусы заявок. Пароли хранятся как хэши bcrypt.",
            "Форма пилота доступна без регистрации. Название заведения, контакт и комментарий сохраняются в базе для рассмотрения заявки и обратной связи. Не отправляйте лишние персональные или конфиденциальные сведения.",
            "При обращении к ИИ-помощнику текст запроса, история диалога и необходимые для ответа данные доступных пользователю заявок передаются внешнему AI-провайдеру Google через Gemini API. Если оператор настроил альтернативного провайдера, обработку выполняет Anthropic API. Пароли и ключи API в диалог не включаются. Не вводите конфиденциальные сведения в чат с ИИ.",
            "Для карт, поиска адресов и дорожных маршрутов соответствующие координаты и адресные запросы могут передаваться 2ГИС, OpenStreetMap и OSRM. Фактический провайдер зависит от настроек и доступности сервиса.",
            "В браузере сохраняются выбранный язык и токен входа. Отдельный демо-режим использует вымышленные данные в памяти вкладки и не создаёт реальных заявок на вывоз.",
            "Для запроса об исправлении или удалении данных используйте опубликованный контакт оператора.",
        ],
        "terms_text": [
            "QOSYU предоставляется как исследовательский прототип для проверки организации сбора вторичного сырья. Демонстрационные данные не подтверждают фактический вывоз или измеренное сокращение выбросов.",
            "Бизнес подаёт заявки, переработчик принимает их и отмечает выполнение. Платформа координирует взаимодействие и сама не осуществляет перевозку. Стоимость, время и условия согласуются сторонами отдельно; гарантированные сроки и платные тарифы пока не предлагаются.",
            "В основном веб-интерфейсе одиночные дорожные маршруты строятся через API 2ГИС. Многоадресный объезд с учётом ограничений исследуется и проверяется в отдельном тестовом контуре. Расчёт времени является оценкой.",
            "Пользователь отвечает за достоверность отправленных данных и наличие права их передавать. Нельзя использовать платформу для спама, незаконных действий или доступа к чужим данным. Ответы ИИ необходимо проверять перед практическим применением.",
            "Заявка на пилот выражает интерес к участию и не является заказом перевозки или гарантией включения в пилот. В демо-режиме действия изменяют только тестовые данные текущей вкладки.",
        ],
    },
    "en": {
        "title": "QOSYU — secondary-material collection research prototype",
        "description": "QOSYU is an SME secondary-material collection research prototype. Single routes use the 2GIS API; constrained multi-stop routing is evaluated in a separate test environment.",
        "privacy": "Privacy policy", "terms": "Terms of use", "home": "Back to home",
        "privacy_text": [
            "QOSYU processes email, organisation and account details, plus collection addresses, coordinates, material type, weight and request statuses. Passwords are stored as bcrypt hashes.",
            "The pilot form requires no account. Establishment name, contact and comment are stored in the database to review your enquiry and respond. Do not submit unnecessary personal or confidential information.",
            "When you use the AI assistant, your request text, conversation history and relevant data from requests you may access are sent to the external AI provider Google through the Gemini API. If an alternative provider is configured, processing uses the Anthropic API. Passwords and API keys are excluded from the conversation. Do not enter confidential information in AI chat.",
            "Coordinates and address searches may be sent to 2GIS, OpenStreetMap and OSRM for maps and road routes. The actual provider depends on configuration and availability.",
            "Your browser stores your language preference and sign-in token. The separate demo uses fictional data in tab memory and does not create real collection requests.",
            "For data correction or deletion, use the published operator contact.",
        ],
        "terms_text": [
            "QOSYU is a research prototype for evaluating secondary-material collection coordination. Demo data do not establish physical collection or measured emissions reductions.",
            "Businesses submit requests; recyclers accept and mark them complete. The platform coordinates the parties and does not transport material itself. Price, time and conditions are agreed separately. Paid plans and guaranteed deadlines are not currently offered.",
            "The main web interface uses the 2GIS API for single road routes. Constrained multi-stop routing is researched and evaluated in a separate test environment. Travel times are estimates.",
            "Users are responsible for accurate submissions and the right to share their data. Spam, unlawful use and access to other users' private data are prohibited. Check AI responses before acting on them.",
            "A pilot enquiry expresses interest and is neither a collection order nor a guarantee of participation. Demo actions change only the test data in the current tab.",
        ],
    },
    "kk": {
        "title": "QOSYU — қайталама шикізатты жинаудың зерттеу прототипі",
        "description": "QOSYU — ШОБ-тан қайталама шикізат жинаудың зерттеу прототипі. Жеке бағыттар 2ГИС API арқылы құрылады, шектеулері бар көпнүктелі бағыттар бөлек сынақ ортасында тексеріледі.",
        "privacy": "Құпиялылық саясаты", "terms": "Пайдалану шарттары", "home": "Басты бетке",
        "privacy_text": [
            "QOSYU email, ұйым атауы мен тіркелгі деректерін, сондай-ақ жинау мекенжайларын, координаттарды, шикізат түрін, салмағын және өтінім мәртебесін өңдейді. Құпиясөздер bcrypt хэші түрінде сақталады.",
            "Пилотқа өтінім беру үшін тіркелу қажет емес. Мекеме атауы, байланыс дерегі және түсініктеме өтінімді қарау және кері байланыс үшін дерекқорда сақталады. Артық жеке немесе құпия мәліметтерді жібермеңіз.",
            "ЖИ көмекшісіне жүгінгенде сұрау мәтіні, диалог тарихы және пайдаланушыға қолжетімді өтінімдердің жауапқа қажетті деректері Gemini API арқылы сыртқы AI-провайдер Google-ға беріледі. Оператор балама провайдерді баптаса, Anthropic API қолданылады. Құпиясөздер мен API кілттері диалогқа қосылмайды. ЖИ чатына құпия мәлімет енгізбеңіз.",
            "Карталар мен жол бағыттарын құру үшін координаттар мен мекенжай сұраулары 2ГИС, OpenStreetMap және OSRM сервистеріне берілуі мүмкін. Қолданылатын сервис баптаулар мен қолжетімділікке байланысты.",
            "Браузер таңдалған тілді және кіру токенін сақтайды. Бөлек демо-режим қойынды жадындағы ойдан шығарылған деректерді пайдаланады және нақты тасымалдау өтінімдерін жасамайды.",
            "Деректерді түзету немесе жою үшін оператордың жарияланған байланысын пайдаланыңыз.",
        ],
        "terms_text": [
            "QOSYU қайталама шикізат жинауды үйлестіруді тексеруге арналған зерттеу прототипі ретінде ұсынылады. Демо деректер нақты тасымалдауды немесе шығарындылардың өлшенген азаюын растамайды.",
            "Бизнес өтінім береді, өңдеуші оны қабылдап, орындалуын белгілейді. Платформа тараптардың өзара әрекетін үйлестіреді және өзі тасымалдамайды. Баға, уақыт пен шарттар бөлек келісіледі. Ақылы тарифтер мен кепілді мерзімдер әзірге ұсынылмайды.",
            "Негізгі веб-интерфейсте жеке жол бағыттары 2ГИС API арқылы құрылады. Шектеулері бар көпнүктелі бағыттар бөлек сынақ ортасында зерттеліп, тексеріледі. Жол уақыты шамамен есептеледі.",
            "Пайдаланушы деректердің дұрыстығына және оларды беруге құқығы бар екеніне жауапты. Спамға, заңсыз әрекеттерге және бөтен деректерге рұқсатсыз қол жеткізуге тыйым салынады. ЖИ жауаптарын қолданар алдында тексеру қажет.",
            "Пилотқа өтінім қатысуға қызығушылықты білдіреді, тасымалдауға тапсырыс немесе қатысу кепілдігі болып саналмайды. Демо әрекеттер тек ағымдағы қойындының сынақ деректерін өзгертеді.",
        ],
    },
}


def locale(lang: str) -> str:
    return lang if lang in COPY else "ru"


def metadata(lang: str, path: str = "/", title: str | None = None) -> str:
    lang = locale(lang)
    title = title or COPY[lang]["title"]
    desc = html.escape(COPY[lang]["description"], quote=True)
    url = ORIGIN + path + (f"?lang={lang}" if lang != "ru" else "")
    alternates = "".join(f'<link rel="alternate" hreflang="{code}" href="{ORIGIN}{path}?lang={code}" />' for code in COPY)
    return f'''<title>{html.escape(title)}</title>
  <meta name="description" content="{desc}" />
  <meta property="og:title" content="{html.escape(title, quote=True)}" />
  <meta property="og:description" content="{desc}" />
  <meta property="og:type" content="website" />
  <meta property="og:site_name" content="QOSYU" />
  <meta property="og:image" content="https://qosyu.com/static/brand/qosyu-wordmark.png" />
  <meta property="og:url" content="{html.escape(url, quote=True)}" />
  <meta property="og:locale" content="{dict(ru='ru_RU', en='en_US', kk='kk_KZ')[lang]}" />
  <link rel="canonical" href="{html.escape(url, quote=True)}" />{alternates}'''


def contact_links(lang: str) -> str:
    links = []
    locations = {
        "ru": settings.CONTACT_LOCATION.strip(),
        "en": settings.CONTACT_LOCATION_EN.strip(),
        "kk": settings.CONTACT_LOCATION_KK.strip(),
    }
    fallback = next((value for value in locations.values() if value), "")
    if fallback:
        locations = {code: value or fallback for code, value in locations.items()}
        variants = " ".join(
            f'data-contact-location-{code}="{html.escape(value, quote=True)}"'
            for code, value in locations.items()
        )
        links.append(f'<span {variants}>{html.escape(locations[lang])}</span>')

    def add_link(label: str, url: str, external: bool = False) -> None:
        attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
        links.append(f'<a href="{html.escape(url, quote=True)}"{attrs}>{html.escape(label)}</a>')

    if settings.CONTACT_PHONE:
        number = re.sub(r"[^+0-9]", "", settings.CONTACT_PHONE)
        add_link(settings.CONTACT_PHONE, f"tel:{number}")
    if settings.CONTACT_EMAIL:
        add_link(settings.CONTACT_EMAIL, f"mailto:{settings.CONTACT_EMAIL}")
    for setting, service, base in (
        (settings.CONTACT_INSTAGRAM, "Instagram", "https://www.instagram.com/{}/"),
        (settings.CONTACT_TIKTOK, "TikTok", "https://www.tiktok.com/@{}"),
        (settings.CONTACT_TELEGRAM, "Telegram", "https://t.me/{}"),
    ):
        if setting:
            handle = setting.lstrip("@")
            add_link(f"{service}: @{handle}", base.format(handle), external=True)
    if settings.CONTACT_WHATSAPP:
        add_link("WhatsApp", f"https://wa.me/{settings.CONTACT_WHATSAPP.lstrip('+')}", external=True)
    if not links:
        return ""
    title = {"ru": "Контакты", "en": "Contacts", "kk": "Байланыс"}[lang]
    return (f'<div class="public-contacts"><p><strong data-i18n="contacts.title">{title}</strong></p>'
            f'<div class="footer-contacts">{"".join(links)}</div></div>')


def frontend(lang: str) -> str:
    lang = locale(lang)
    markup = (ROOT / "index.html").read_text(encoding="utf-8")
    markup = markup.replace('<html lang="ru">', f'<html lang="{lang}">')
    markup = re.sub(r'<meta name="description"[^>]+>\s*<title>.*?</title>', metadata(lang), markup, count=1, flags=re.S)
    return markup.replace("<!-- PUBLIC_CONTACTS -->", contact_links(lang))


def legal(kind: str, lang: str) -> str:
    lang = locale(lang)
    content = COPY[lang]
    title = content[kind]
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in content[f"{kind}_text"])
    languages = " · ".join(f'<a href="/{kind}?lang={code}" lang="{code}">{code.upper()}</a>' for code in COPY)
    email = html.escape(str(settings.CONTACT_EMAIL), quote=True)
    contact = f'<p>Email: <a href="mailto:{email}">{email}</a></p>' if email else ""
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
{metadata(lang, '/' + kind, title + ' — QOSYU')}
<link rel="icon" type="image/png" href="/static/brand/qosyu-symbol.png" />
<link rel="stylesheet" href="/static/css/app.css?v=20261121-clean" /></head><body class="legal-page">
<main class="section"><p><a href="/?lang={lang}">{content['home']}</a> · {languages}</p>
<article class="card policy-text"><h1>{title}</h1>{paragraphs}
{contact}</article>
<p><a href="/privacy?lang={lang}">{content['privacy']}</a> · <a href="/terms?lang={lang}">{content['terms']}</a></p>
</main></body></html>'''
