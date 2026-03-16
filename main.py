import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

if not BOT_TOKEN:
    print("❌ Токен не найден!")
    exit()

print("✅ Токен загружен")

from database import init_db
from handlers import router

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()

    servers = [
        "https://api.telegram.org",
        "https://telegram.orbitron.dev",
        "https://tg.i-c-a.su",
        "http://api.telegram.org",
    ]

    dp = Dispatcher()
    dp.include_router(router)

    for server_url in servers:
        try:
            logging.info(f"Пробуем сервер: {server_url}")
            api_server = TelegramAPIServer.from_base(server_url)
            session = AiohttpSession(api=api_server, timeout=60)
            bot = Bot(
                token=BOT_TOKEN,
                session=session,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
            await dp.start_polling(bot, skip_updates=True)
            logging.info(f"✅ Подключились к серверу {server_url}")
            return
        except Exception as e:
            logging.error(f"Сервер {server_url} не работает: {e}")
            continue
    
    logging.error("Все серверы недоступны. Запускаем без резерва.")
    session = AiohttpSession(timeout=60)
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")