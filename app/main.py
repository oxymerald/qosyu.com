from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from routers import auth, requests, recycler, clustering, analytics, chat, marketplace
from routers import telegram_bot
from database import engine
from models import Base
import asyncio

app = FastAPI(title="QOSYU Backend")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Инициализация БД ---
@app.on_event("startup")
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- Статика ---
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")

# --- Роутеры API ---
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(requests.router, prefix="/requests", tags=["requests"])
app.include_router(recycler.router, prefix="/recycler", tags=["recycler"])
app.include_router(clustering.router, prefix="/clustering", tags=["clustering"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(chat.router)
app.include_router(marketplace.router)

# --- Запуск Telegram-бота (через asyncio.create_task) ---
async def run_bot():
    """Асинхронный запуск бота в главном event loop"""
    try:
        print("🚀 Запуск Telegram-бота...")
        bot_app = telegram_bot.setup_bot()
        
        # Инициализация и запуск бота
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        
        print("✅ Telegram-бот запущен и слушает сообщения!")
        
        # Держим бота активным
        while True:
            await asyncio.sleep(60)
    except Exception as e:
        print(f"❌ Ошибка в работе Telegram-бота: {e}")

@app.on_event("startup")
async def startup_telegram_bot():
    # Запускаем бота в фоновой задаче (не блокируя FastAPI)
    asyncio.create_task(run_bot())