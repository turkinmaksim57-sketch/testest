import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "thermo_bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables (.env)")