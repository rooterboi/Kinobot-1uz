import asyncio
import logging
from html import escape as e
from aiogram.exceptions import TelegramAPIError
import db
from kb import ikb, B

log = logging.getLogger(__name__)
LEVEL = {"all": "🎬 Barcha uchun", "free": "🆓 Faqat oddiy", "premium": "🔒 Faqat Premium"}


def fmt(n):
    return f"{int(n):,}".replace(",", " ")


def days_txt(d):
    return "Umrbod" if int(d) == 0 else f"{d} kun"


async def _member(bot, ch, uid):
    try:
        m = await bot.get_chat_member(ch["chat_id"], uid)
        return m.status in ("left", "kicked")
    except TelegramAPIError as ex:  # bot kanalda admin emas -> bloklamaymiz
        log.warning("Obuna tekshirib bo'lmadi %s: %s", ch["chat_id"], ex)
        return False


async def unsubscribed(bot, uid):
    chs = await db.get_channels()
    res = await asyncio.gather(*[_member(bot, c, uid) for c in chs])
    return [c for c, bad in zip(chs, res) if bad]


async def autopost(bot, kind, code, title, poster_id, level, info=""):
    """Post kanaliga chiroyli post. Xato bo'lsa matn qaytaradi."""
    ch = (await db.get_setting("post_channel")).strip()
    if not ch:
        return None
    try:
        me = await bot.me()
        link = f"https://t.me/{me.username}?start={'m' if kind == 'movie' else 's'}_{code}"
        icon = "🎬" if kind == "movie" else "📺"
        cap = (f"{icon} <b>{e(title)}</b>\n{e(info)}\n\n🔑 Kod: <code>{e(code)}</code>\n"
               f"📌 {LEVEL[level]}\n\n👇 Tomosha qilish uchun bosing")[:1024]
        kb = ikb([B("▶️ Botda ko'rish", url=link)])
        chat = int(ch) if ch.lstrip("-").isdigit() else ch
        if poster_id:
            await bot.send_photo(chat, poster_id, caption=cap, reply_markup=kb)
        else:
            await bot.send_message(chat, cap, reply_markup=kb)
    except TelegramAPIError as ex:
        log.error("Autopost xato: %s", ex)
        return str(ex)
    return None
