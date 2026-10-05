import time
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery
from config import ADMINS


class Throttle(BaseMiddleware):
    """Spamdan himoya: bitta foydalanuvchidan 0.5s da 1 ta so'rov."""
    def __init__(self, rate=0.5):
        self.rate, self.last = rate, {}

    async def __call__(self, handler, event, data):
        u = event.from_user
        if u and u.id not in ADMINS:
            t = time.monotonic()
            if t - self.last.get(u.id, 0) < self.rate:
                if isinstance(event, CallbackQuery):
                    await event.answer()
                return
            self.last[u.id] = t
            if len(self.last) > 50000:
                self.last.clear()
        return await handler(event, data)
