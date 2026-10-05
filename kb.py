from aiogram.types import (InlineKeyboardButton as IB, InlineKeyboardMarkup as IM,
                           KeyboardButton as KB, ReplyKeyboardMarkup as RM)


def B(text, cb=None, url=None):
    return IB(text=text, callback_data=cb, url=url)


def ikb(*rows):
    return IM(inline_keyboard=[list(r) for r in rows])


def main_menu():
    return RM(keyboard=[[KB(text="💎 Premium sotib olish"), KB(text="💰 Mening balansim")],
                        [KB(text="🎟 Promokod"), KB(text="🎁 Do'stlarni taklif qilish")]], resize_keyboard=True)


def sub_kb(channels, code=""):
    return ikb(*[[B(f"📢 {c['title'] or 'Kanal'}", url=c["url"])] for c in channels], [B("✅ Tekshirish", f"chk:{code}")])


def level_kb():
    return ikb([B("🎬 Barchaga", "lvl:all"), B("🆓 Faqat Oddiy", "lvl:free")], [B("🔒 Faqat Premium", "lvl:premium")])
