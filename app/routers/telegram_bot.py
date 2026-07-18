import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session_maker
from models import User, WasteRequest, RequestStatus, WasteType
from schemas import WasteRequestCreate
from auth import get_password_hash, create_access_token
from sqlalchemy import select, func
import os

# --- Конфигурация ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8682827104:AAEIWbKlGlhq53A7kPwX2ZRjDXLAdggfZR0")

# --- Состояния для диалога создания заявки ---
WASTE_TYPE, WEIGHT, LOCATION = range(3)

# --- Клавиатуры ---
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Создать заявку", callback_data="create")],
        [InlineKeyboardButton("📋 Мои заявки", callback_data="my")],
        [InlineKeyboardButton("🌱 ESG-отчёт", callback_data="esg")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_waste_type_keyboard():
    keyboard = [
        [InlineKeyboardButton("♻️ Пластик", callback_data="plastic")],
        [InlineKeyboardButton("📦 Картон", callback_data="cardboard")],
        [InlineKeyboardButton("🍾 Стекло", callback_data="glass")],
        [InlineKeyboardButton("🔩 Металл", callback_data="metal")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Функции для работы с API ---
async def api_call(endpoint: str, method: str = "GET", body: dict = None, token: str = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    url = f"{API_BASE}{endpoint}"
    async with httpx.AsyncClient() as client:
        if method == "GET":
            resp = await client.get(url, headers=headers)
        elif method == "POST":
            resp = await client.post(url, json=body, headers=headers)
        else:
            return None
    if resp.status_code == 200:
        return resp.json()
    return None

async def register_user(email: str, password: str, company_name: str, role: str):
    """Регистрация пользователя через API"""
    data = {
        "email": email,
        "password": password,
        "company_name": company_name,
        "role": role
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/auth/register", json=data)
        if resp.status_code == 200:
            return resp.json()
    return None

async def login_user(email: str, password: str):
    """Логин через API"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/auth/login?email={email}&password={password}")
        if resp.status_code == 200:
            return resp.json()
    return None

async def create_request(token: str, waste_type: str, weight_kg: float, latitude: float, longitude: float):
    """Создание заявки через API"""
    data = {
        "waste_type": waste_type,
        "weight_kg": weight_kg,
        "latitude": latitude,
        "longitude": longitude
    }
    return await api_call("/requests/create", "POST", data, token)

async def get_my_requests(token: str):
    """Получить свои заявки"""
    return await api_call("/requests/my", "GET", token=token)

async def get_esg(token: str):
    """Получить ESG-отчёт"""
    return await api_call("/analytics/esg/sme", "GET", token=token)

# --- Хендлеры команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user = update.effective_user
    welcome_text = (
        f"👋 Привет, {user.first_name}!\n\n"
        "🤖 Я бот QOSYU — AI-агрегатор сбора отходов.\n\n"
        "📌 Что я умею:\n"
        "• 📝 Создавать заявки на вывоз отходов\n"
        "• 📋 Показывать список ваших заявок\n"
        "• 🌱 Показывать ESG-отчёт\n"
        "• 🔔 Уведомлять об изменениях статуса заявок\n\n"
        "❗️ Сначала зарегистрируйтесь или войдите.\n"
        "Используйте /register для регистрации.\n"
        "Используйте /login для входа."
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())

# --- Регистрация через бота ---
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало регистрации"""
    context.user_data["register_step"] = "email"
    await update.message.reply_text(
        "📝 Регистрация нового пользователя\n\n"
        "Введите ваш email:"
    )
    return 1

async def register_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение email"""
    context.user_data["email"] = update.message.text.strip()
    context.user_data["register_step"] = "company"
    await update.message.reply_text(
        f"✅ Email: {context.user_data['email']}\n\n"
        "Введите название вашей компании:"
    )
    return 1

async def register_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия компании"""
    context.user_data["company_name"] = update.message.text.strip()
    context.user_data["register_step"] = "password"
    await update.message.reply_text(
        f"✅ Компания: {context.user_data['company_name']}\n\n"
        "Введите пароль (минимум 6 символов):"
    )
    return 1

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение пароля и завершение регистрации"""
    password = update.message.text.strip()
    if len(password) < 6:
        await update.message.reply_text("❌ Пароль должен быть не менее 6 символов. Попробуйте снова:")
        return 1
    
    email = context.user_data["email"]
    company = context.user_data["company_name"]
    role = "sme"  # по умолчанию SME
    
    # Регистрация через API
    result = await register_user(email, password, company, role)
    
    if result:
        context.user_data["user_id"] = result["id"]
        await update.message.reply_text(
            f"✅ Регистрация успешна!\n\n"
            f"👤 Пользователь: {email}\n"
            f"🏢 Компания: {company}\n"
            f"📌 Роль: {role}\n\n"
            "Теперь выполните /login для входа."
        )
    else:
        await update.message.reply_text(
            "❌ Ошибка регистрации. Возможно, такой email уже существует.\n"
            "Попробуйте другой email."
        )
    context.user_data.clear()
    return ConversationHandler.END

# --- Логин через бота ---
async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало логина"""
    context.user_data["login_step"] = "email"
    await update.message.reply_text(
        "🔐 Вход в систему\n\n"
        "Введите ваш email:"
    )
    return 1

async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение email для логина"""
    context.user_data["login_email"] = update.message.text.strip()
    context.user_data["login_step"] = "password"
    await update.message.reply_text(
        f"✅ Email: {context.user_data['login_email']}\n\n"
        "Введите пароль:"
    )
    return 1

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение пароля и выполнение логина"""
    password = update.message.text.strip()
    email = context.user_data["login_email"]
    
    result = await login_user(email, password)
    
    if result and "access_token" in result:
        context.user_data["token"] = result["access_token"]
        await update.message.reply_text(
            f"✅ Вход успешен!\n\n"
            f"👤 Добро пожаловать, {email}!\n"
            "Теперь вы можете создавать заявки и управлять ими.",
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ Ошибка входа. Проверьте email и пароль."
        )
    context.user_data.clear()
    return ConversationHandler.END

# --- Создание заявки (через кнопки) ---
async def create_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания заявки"""
    query = update.callback_query
    await query.answer()
    
    if "token" not in context.user_data:
        await query.edit_message_text(
            "❌ Вы не авторизованы.\n"
            "Используйте /login для входа."
        )
        return
    
    await query.edit_message_text(
        "📝 Создание заявки на вывоз отходов\n\n"
        "Выберите тип отходов:",
        reply_markup=get_waste_type_keyboard()
    )
    return WASTE_TYPE

async def select_waste_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор типа отходов"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel":
        await query.edit_message_text(
            "❌ Создание заявки отменено.",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END
    
    context.user_data["waste_type"] = query.data
    await query.edit_message_text(
        f"✅ Тип: {query.data}\n\n"
        "Введите вес отходов в килограммах:"
    )
    return WEIGHT

async def enter_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод веса"""
    try:
        weight = float(update.message.text.strip())
        if weight <= 0:
            raise ValueError
        context.user_data["weight"] = weight
        await update.message.reply_text(
            f"✅ Вес: {weight} кг\n\n"
            "Введите координаты (широта, долгота) через пробел\n"
            "Например: 43.2567 76.9286"
        )
        return LOCATION
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число (больше 0). Попробуйте снова:"
        )
        return WEIGHT

async def enter_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ввод координат и создание заявки"""
    try:
        parts = update.message.text.strip().split()
        if len(parts) != 2:
            raise ValueError
        latitude = float(parts[0])
        longitude = float(parts[1])
        
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            raise ValueError
        
        # Создание заявки через API
        token = context.user_data.get("token")
        waste_type = context.user_data.get("waste_type")
        weight = context.user_data.get("weight")
        
        result = await create_request(token, waste_type, weight, latitude, longitude)
        
        if result:
            await update.message.reply_text(
                f"✅ Заявка успешно создана!\n\n"
                f"📋 ID: {result['id']}\n"
                f"♻️ Тип: {result['waste_type']}\n"
                f"📦 Вес: {result['weight_kg']} кг\n"
                f"📍 Координаты: {latitude}, {longitude}\n"
                f"📌 Статус: {result['status']}",
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                "❌ Ошибка создания заявки. Попробуйте позже."
            )
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Неверный формат координат.\n"
            "Введите два числа через пробел, например:\n"
            "43.2567 76.9286"
        )
        return LOCATION
    
    context.user_data.clear()
    return ConversationHandler.END

# --- Мои заявки ---
async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать мои заявки"""
    query = update.callback_query
    await query.answer()
    
    if "token" not in context.user_data:
        await query.edit_message_text(
            "❌ Вы не авторизованы.\nИспользуйте /login для входа.",
            reply_markup=get_main_keyboard()
        )
        return
    
    result = await get_my_requests(context.user_data["token"])
    
    if result:
        if not result:
            await query.edit_message_text(
                "📋 У вас пока нет заявок.\n\n"
                "Создайте первую заявку через кнопку 'Создать заявку'.",
                reply_markup=get_main_keyboard()
            )
            return
        
        text = "📋 Ваши заявки:\n\n"
        for req in result[-10:]:  # последние 10
            status_emoji = "✅" if req["status"] == "collected" else "⏳"
            text += f"{status_emoji} #{req['id']} {req['waste_type']} — {req['weight_kg']} кг ({req['status']})\n"
        await query.edit_message_text(text, reply_markup=get_main_keyboard())
    else:
        await query.edit_message_text(
            "❌ Ошибка загрузки заявок.",
            reply_markup=get_main_keyboard()
        )

# --- ESG-отчёт ---
async def esg_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать ESG-отчёт"""
    query = update.callback_query
    await query.answer()
    
    if "token" not in context.user_data:
        await query.edit_message_text(
            "❌ Вы не авторизованы.\nИспользуйте /login для входа.",
            reply_markup=get_main_keyboard()
        )
        return
    
    result = await get_esg(context.user_data["token"])
    
    if result:
        text = (
            "🌱 <b>Ваш ESG-отчёт</b>\n\n"
            f"♻️ Собрано отходов: <b>{result['total_recycled_kg']} кг</b>\n"
            f"🌍 CO₂ сэкономлено: <b>{result['co2_saved_kg']} кг</b>\n"
            f"🌳 Эквивалент деревьев: <b>{result['equivalent_trees']}</b>\n"
        )
        await query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
    else:
        await query.edit_message_text(
            "❌ Ошибка загрузки ESG-отчёта.",
            reply_markup=get_main_keyboard()
        )

# --- Обработка отмены ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    await update.message.reply_text(
        "❌ Действие отменено.",
        reply_markup=get_main_keyboard()
    )
    context.user_data.clear()
    return ConversationHandler.END

# --- Кнопка "Назад" (по callback) ---
async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📌 Главное меню",
        reply_markup=get_main_keyboard()
    )

# --- Обработка неизвестных команд ---
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Неизвестная команда.\n"
        "Используйте /help для списка команд."
    )

# --- Help ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🤖 <b>QOSYU Bot — помощь</b>\n\n"
        "📌 <b>Доступные команды:</b>\n"
        "/start — Начать работу\n"
        "/register — Зарегистрироваться\n"
        "/login — Войти в систему\n"
        "/help — Эта справка\n\n"
        "📌 <b>Что я умею:</b>\n"
        "• Создавать заявки на вывоз отходов\n"
        "• Показывать список ваших заявок\n"
        "• Показывать ESG-отчёт\n\n"
        "Связь: @ваш_канал"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")

# --- Обработка callback-запросов ---
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общая обработка callback-запросов"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "main_menu":
        await query.edit_message_text(
            "📌 Главное меню",
            reply_markup=get_main_keyboard()
        )
        return
    
    if query.data == "create":
        # Запускаем диалог создания заявки
        if "token" not in context.user_data:
            await query.edit_message_text(
                "❌ Вы не авторизованы.\nИспользуйте /login для входа."
            )
            return
        
        await query.edit_message_text(
            "📝 Создание заявки на вывоз отходов\n\n"
            "Выберите тип отходов:",
            reply_markup=get_waste_type_keyboard()
        )
        return WASTE_TYPE
    
    if query.data == "my":
        await my_requests(update, context)
        return
    
    if query.data == "esg":
        await esg_report(update, context)
        return
    
    if query.data in ["plastic", "cardboard", "glass", "metal", "organic"]:
        # Выбор типа отходов для создания заявки
        context.user_data["waste_type"] = query.data
        await query.edit_message_text(
            f"✅ Тип: {query.data}\n\n"
            "Введите вес отходов в килограммах (число):"
        )
        return WEIGHT

def setup_bot():
    """Создание и настройка бота"""
    # Создаём приложение с отключённой обработкой сигналов
    application = Application.builder().token(BOT_TOKEN).build()
    
    # ОТКЛЮЧАЕМ ОБРАБОТКУ СИГНАЛОВ (для работы в фоновом потоке)
    # Это ключевое исправление!
    application._check_signals = False
    
    # Регистрация ConversationHandler для создания заявки
    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(create_request_start, pattern="^create$"),
        ],
        states={
            WASTE_TYPE: [CallbackQueryHandler(select_waste_type, pattern="^(plastic|cardboard|glass|metal|organic|cancel)$")],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_weight)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_location)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Регистрация ConversationHandler для регистрации
    register_conv = ConversationHandler(
        entry_points=[CommandHandler("register", register)],
        states={
            1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_email),
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_company),
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_password),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Регистрация ConversationHandler для логина
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("login", login)],
        states={
            1: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_email),
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_password),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    
    # Добавление обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(register_conv)
    application.add_handler(login_conv)
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(handle_callback, pattern="^(plastic|cardboard|glass|metal|organic|cancel|main_menu|create|my|esg)$"))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    
    return application

# --- Функция для отправки уведомлений ---
async def send_notification(chat_id: int, text: str):
    """Отправить уведомление пользователю"""
    bot_token = BOT_TOKEN
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)