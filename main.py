import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

import db
from config import ADMINS, BOT_TOKEN
from handlers import admin, user
from middlewares import Throttle


async def on_error(event: ErrorEvent):
    logging.error("Handler xatosi: %s", event.exception, exc_info=event.exception)
    return True


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN topilmadi (.env faylni tekshiring)")
    if not ADMINS:
        logging.warning("ADMINS bo'sh — admin panel ishlamaydi!")
    await db.init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(Throttle())
    dp.callback_query.outer_middleware(Throttle())
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.errors.register(on_error)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
