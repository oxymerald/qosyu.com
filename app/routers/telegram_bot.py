"""Telegram-бот QOSYU.

Принципы безопасности:
- токен берётся ТОЛЬКО из переменной окружения TELEGRAM_BOT_TOKEN;
- никакие пароли в переписке не запрашиваются и не хранятся:
  аккаунт привязывается к telegram_chat_id;
- бот работает с БД напрямую, без HTTP-запросов к собственному API.
"""

import asyncio
import logging
import secrets

import httpx
from sqlalchemy import func, select
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from auth import get_password_hash
from config import settings
from database import async_session_maker
from models import RequestStatus, User, UserRole, WasteRequest, WasteType
from services.esg import calculate_co2_saved

logger = logging.getLogger("qosyu.bot")

# Состояния диалогов
REG_COMPANY = 0
REQ_TYPE, REQ_WEIGHT, REQ_LOCATION = range(1, 4)

WASTE_LABELS = {
    "plastic": "♻️ Пластик",
    "cardboard": "📦 Картон",
    "glass": "🍾 Стекло",
    "metal": "🔩 Металл",
}

STATUS_LABELS = {
    "pending": "⏳ ожидает",
    "clustered": "🧩 в зоне сбора",
    "assigned": "🚚 назначен вывоз",
    "collected": "✅ вывезено",
    "verified": "✔️ подтверждено",
}


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📝 Создать заявку", callback_data="create")],
            [InlineKeyboardButton("📋 Мои заявки", callback_data="my")],
            [InlineKeyboardButton("🌱 ESG-отчёт", callback_data="esg")],
        ]
    )


def waste_type_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=value)]
        for value, label in WASTE_LABELS.items()
    ]
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)


async def get_bot_user(chat_id: int) -> User | None:
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.telegram_chat_id == chat_id))
        return result.scalar_one_or_none()


# ---------- /start и регистрация ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_bot_user(update.effective_chat.id)
    if user:
        await update.message.reply_text(
            f"👋 С возвращением, {user.company_name}!\n\n"
            "QOSYU — цифровая первая миля переработки.\n"
            "Создавайте заявки на вывоз вторсырья за 20 секунд.",
            reply_markup=main_keyboard(),
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "👋 Здравствуйте! Это бот QOSYU — цифровой платформы первой мили "
        "экологической логистики.\n\n"
        "Мы объединяем небольшие партии вторсырья от бизнеса в выгодные "
        "маршруты для переработчиков.\n\n"
        "Как называется ваша компания (кафе, магазин, офис)?"
    )
    return REG_COMPANY


async def register_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    company = " ".join(update.message.text.split())[:120]
    if len(company) < 2:
        await update.message.reply_text("Название слишком короткое, попробуйте ещё раз:")
        return REG_COMPANY
    chat_id = update.effective_chat.id
    async with async_session_maker() as db:
        result = await db.execute(select(User).where(User.telegram_chat_id == chat_id))
        if result.scalar_one_or_none() is None:
            # Синтетический email и случайный пароль: вход только через Telegram
            db.add(
                User(
                    email=f"tg-{chat_id}@telegram.qosyu.kz",
                    hashed_password=get_password_hash(secrets.token_urlsafe(24)),
                    company_name=company,
                    role=UserRole.SME,
                    telegram_chat_id=chat_id,
                )
            )
            await db.commit()
    await update.message.reply_text(
        f"✅ Готово! Компания «{company}» зарегистрирована.\n\n"
        "Теперь вы можете создавать заявки на вывоз вторсырья.",
        reply_markup=main_keyboard(),
    )
    return ConversationHandler.END


# ---------- Создание заявки ----------

async def create_request_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = await get_bot_user(update.effective_chat.id)
    if not user:
        await query.edit_message_text("Сначала зарегистрируйтесь: отправьте /start")
        return ConversationHandler.END
    await query.edit_message_text(
        "📝 Новая заявка на вывоз.\n\nВыберите тип вторсырья:",
        reply_markup=waste_type_keyboard(),
    )
    return REQ_TYPE


async def select_waste_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("Создание заявки отменено.", reply_markup=main_keyboard())
        return ConversationHandler.END
    context.user_data["waste_type"] = query.data
    await query.edit_message_text(
        f"Тип: {WASTE_LABELS.get(query.data, query.data)}\n\n"
        "Введите вес в килограммах (например: 15):"
    )
    return REQ_WEIGHT


async def enter_weight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        weight = float(update.message.text.strip().replace(",", "."))
        if not (0 < weight <= 50_000):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Введите число от 1 до 50000:")
        return REQ_WEIGHT
    context.user_data["weight"] = weight
    location_kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        f"Вес: {weight} кг\n\n"
        "Отправьте геолокацию точки сбора кнопкой ниже\n"
        "или введите координаты текстом: широта долгота\n"
        "(например: 47.1167 51.8833)",
        reply_markup=location_kb,
    )
    return REQ_LOCATION


async def enter_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        latitude = update.message.location.latitude
        longitude = update.message.location.longitude
    else:
        try:
            parts = update.message.text.strip().split()
            latitude, longitude = float(parts[0]), float(parts[1])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError
        except (ValueError, IndexError):
            await update.message.reply_text(
                "Неверный формат. Отправьте геолокацию или два числа через пробел:"
            )
            return REQ_LOCATION

    user = await get_bot_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text("Сначала зарегистрируйтесь: /start")
        return ConversationHandler.END

    waste_type = context.user_data.get("waste_type", "cardboard")
    weight = context.user_data.get("weight", 1.0)
    async with async_session_maker() as db:
        new_req = WasteRequest(
            sme_id=user.id,
            waste_type=WasteType(waste_type),
            weight_kg=weight,
            latitude=latitude,
            longitude=longitude,
            location_geom=func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326),
            status=RequestStatus.PENDING,
        )
        db.add(new_req)
        await db.commit()
        await db.refresh(new_req)

    await update.message.reply_text(
        "✅ Заявка создана!\n\n"
        f"📋 Номер: #{new_req.id}\n"
        f"♻️ Тип: {WASTE_LABELS.get(waste_type, waste_type)}\n"
        f"⚖️ Вес: {weight} кг\n\n"
        "AI объединит вашу заявку с соседними в общий маршрут — "
        "мы сообщим дату вывоза.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
    context.user_data.clear()
    return ConversationHandler.END


# ---------- Мои заявки и ESG ----------

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = await get_bot_user(update.effective_chat.id)
    if not user:
        await query.edit_message_text("Сначала зарегистрируйтесь: отправьте /start")
        return
    async with async_session_maker() as db:
        result = await db.execute(
            select(WasteRequest)
            .where(WasteRequest.sme_id == user.id)
            .order_by(WasteRequest.created_at.desc())
            .limit(10)
        )
        reqs = result.scalars().all()
    if not reqs:
        await query.edit_message_text(
            "У вас пока нет заявок. Создайте первую!", reply_markup=main_keyboard()
        )
        return
    lines = ["📋 Ваши последние заявки:\n"]
    for r in reqs:
        status = STATUS_LABELS.get(r.status.value, r.status.value)
        label = WASTE_LABELS.get(r.waste_type.value, r.waste_type.value)
        lines.append(f"#{r.id} · {label} · {r.weight_kg} кг · {status}")
    await query.edit_message_text("\n".join(lines), reply_markup=main_keyboard())


async def esg_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = await get_bot_user(update.effective_chat.id)
    if not user:
        await query.edit_message_text("Сначала зарегистрируйтесь: отправьте /start")
        return
    async with async_session_maker() as db:
        result = await db.execute(
            select(func.coalesce(func.sum(WasteRequest.weight_kg), 0.0)).where(
                WasteRequest.sme_id == user.id,
                WasteRequest.status.in_([RequestStatus.COLLECTED, RequestStatus.VERIFIED]),
            )
        )
        total = float(result.scalar() or 0.0)
    co2 = calculate_co2_saved(total)
    await query.edit_message_text(
        "🌱 Ваш ESG-отчёт\n\n"
        f"♻️ Передано на переработку: {round(total, 1)} кг\n"
        f"🌍 CO₂ сэкономлено: {round(co2, 1)} кг\n"
        f"🌳 Эквивалент деревьев: {round(co2 / 22.0, 1)}\n\n"
        "Полная отчётность доступна в личном кабинете на сайте.",
        reply_markup=main_keyboard(),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.", reply_markup=main_keyboard())
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 QOSYU Bot\n\n"
        "/start — регистрация и главное меню\n"
        "/help — эта справка\n"
        "/cancel — отменить текущее действие\n\n"
        "Заявка на вывоз вторсырья создаётся за 20 секунд:\n"
        "тип → вес → геолокация. Остальное сделает платформа."
    )


def setup_bot() -> Application:
    application = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

    registration = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={REG_COMPANY: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_company)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    request_creation = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_request_start, pattern="^create$")],
        states={
            REQ_TYPE: [
                CallbackQueryHandler(
                    select_waste_type, pattern="^(plastic|cardboard|glass|metal|cancel)$"
                )
            ],
            REQ_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_weight)],
            REQ_LOCATION: [
                MessageHandler(
                    (filters.TEXT & ~filters.COMMAND) | filters.LOCATION, enter_location
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(registration)
    application.add_handler(request_creation)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(my_requests, pattern="^my$"))
    application.add_handler(CallbackQueryHandler(esg_report, pattern="^esg$"))
    return application


async def run_bot():
    """Запускается фоновой задачей из lifespan FastAPI."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    try:
        application = setup_bot()
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram-бот запущен")
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("Останавливаю Telegram-бота...")
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
            raise
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Ошибка Telegram-бота (бот отключён, API продолжает работать)")


async def send_notification(chat_id: int, text: str):
    """Служебная отправка уведомления пользователю."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={"chat_id": chat_id, "text": text})
    except httpx.HTTPError:
        logger.warning("Не удалось отправить Telegram-уведомление chat_id=%s", chat_id)
