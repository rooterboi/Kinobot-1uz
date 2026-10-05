import logging
from html import escape as e
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import db
from config import ADMINS
from kb import B, ikb, main_menu, sub_kb
from utils import days_txt, fmt, unsubscribed

log = logging.getLogger(__name__)
router = Router()


class PromoS(StatesGroup):
    code = State()


async def can_view(uid, level):
    if uid in ADMINS or level != "premium" or await db.get_setting("premium_enabled") != "1":
        return True
    return db.is_premium(await db.get_user(uid))


async def deny(bot, chat_id):
    r = await db.get_setting("referral_reward")
    await bot.send_message(
        chat_id, "🔒 Bu kontent faqat <b>Premium</b> foydalanuvchilar uchun.\n\n"
        f"💎 Premium sotib oling yoki do'stlaringizni taklif qilib (har biri uchun {fmt(r)} so'm) "
        "va promokodlar orqali balans yig'ing.",
        reply_markup=ikb([B("💎 Premium tariflari", "prem")], [B("🎁 Taklif havolasi", "refl")]))


async def open_code(bot, chat_id, uid, code):
    code = code.strip().upper()
    if uid not in ADMINS and not db.is_premium(await db.get_user(uid)):
        missing = await unsubscribed(bot, uid)
        if missing:
            return await bot.send_message(chat_id, "📢 Davom etish uchun homiy kanallarga obuna bo'ling:",
                                          reply_markup=sub_kb(missing, code))
    mv = await db.get_movie(code)
    if mv:
        if not await can_view(uid, mv["access_level"]):
            return await deny(bot, chat_id)
        cap = f"🎬 <b>{e(mv['title'])}</b>\n"
        if mv["language"]:
            cap += f"🌐 Til: {e(mv['language'])}\n"
        if mv["quality"]:
            cap += f"📺 Sifat: {e(mv['quality'])}\n"
        if mv["description"]:
            cap += f"\n{e(mv['description'])}\n"
        cap += f"\n🔑 Kod: {mv['code']}"
        try:
            return await bot.send_video(chat_id, mv["file_id"], caption=cap[:1024])
        except TelegramAPIError as ex:
            log.error("send_video: %s", ex)
            return await bot.send_message(chat_id, "❌ Faylni yuborib bo'lmadi. Keyinroq urinib ko'ring.")
    eps = await db.get_series(code)
    if eps:
        if not await can_view(uid, eps[0]["access_level"]):
            return await deny(bot, chat_id)
        seasons = sorted({x["season"] for x in eps})
        rows = [B(f"{s}-fasl", f"sn:{code}:{s}") for s in seasons]
        return await bot.send_message(chat_id, f"📺 <b>{e(eps[0]['title'])}</b>\nFaslni tanlang:",
                                      reply_markup=ikb(*[rows[i:i + 3] for i in range(0, len(rows), 3)]))
    await bot.send_message(chat_id, "❌ Bunday kodli kino yoki serial topilmadi.")


@router.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    arg, u = command.args or "", m.from_user
    ref = int(arg[4:]) if arg.startswith("ref_") and arg[4:].isdigit() else None
    if ref == u.id or (ref and not await db.get_user(ref)):
        ref = None
    if await db.add_user(u.id, u.full_name, u.username, ref) and ref:
        reward = int(await db.get_setting("referral_reward") or 0)
        if reward:
            await db.add_balance(ref, reward)
            try:
                await m.bot.send_message(ref, f"🎉 Do'stingiz qo'shildi! Balansingizga <b>{fmt(reward)}</b> so'm qo'shildi.")
            except TelegramAPIError:
                pass
    await m.answer(f"👋 Salom, <b>{e(u.first_name)}</b>!\n\n🎬 Kino yoki serial <b>kodini</b> yuboring.", reply_markup=main_menu())
    if arg[:2] in ("m_", "s_"):
        await open_code(m.bot, m.chat.id, u.id, arg[2:])


@router.callback_query(F.data.startswith("chk:"))
async def chk(cb: CallbackQuery):
    await cb.answer()
    try:
        await cb.message.delete()
    except TelegramAPIError:
        pass
    code = cb.data[4:]
    if code:
        await open_code(cb.bot, cb.message.chat.id, cb.from_user.id, code)
    else:
        await cb.message.answer("✅ Rahmat! Endi kod yuborishingiz mumkin.")


@router.callback_query(F.data.startswith("sn:"))
async def season(cb: CallbackQuery):
    _, code, s = cb.data.split(":")
    eps = [x for x in await db.get_series(code) if x["season"] == int(s)]
    if not eps:
        return await cb.answer("Topilmadi", show_alert=True)
    btn = [B(f"{x['episode']}-qism", f"ep:{x['id']}") for x in eps]
    rows = [btn[i:i + 4] for i in range(0, len(btn), 4)] + [[B("◀️ Fasllar", f"sr:{code}")]]
    await cb.message.edit_text(f"📺 <b>{e(eps[0]['title'])}</b> — {s}-fasl\nQismni tanlang:", reply_markup=ikb(*rows))
    await cb.answer()


@router.callback_query(F.data.startswith("sr:"))
async def seasons_back(cb: CallbackQuery):
    await cb.answer()
    await open_code(cb.bot, cb.message.chat.id, cb.from_user.id, cb.data[3:])


@router.callback_query(F.data.startswith("ep:"))
async def episode(cb: CallbackQuery):
    ep = await db.get_episode(int(cb.data[3:]))
    if not ep:
        return await cb.answer("Topilmadi", show_alert=True)
    if not await can_view(cb.from_user.id, ep["access_level"]):
        await cb.answer()
        return await deny(cb.bot, cb.message.chat.id)
    await cb.answer()
    try:
        await cb.bot.send_video(cb.message.chat.id, ep["file_id"],
                                caption=f"📺 <b>{e(ep['title'])}</b>\n{ep['season']}-fasl, {ep['episode']}-qism")
    except TelegramAPIError as ex:
        log.error("episode send: %s", ex)
        await cb.message.answer("❌ Faylni yuborib bo'lmadi.")


# ---------- Premium / balans / referal
async def premium_page(uid):
    if await db.get_setting("premium_enabled") != "1":
        return "🎉 Premium tizimi hozir o'chirilgan — barcha kontent hamma uchun <b>bepul</b>!", None
    u = await db.get_user(uid)
    prem = db.is_premium(u)
    st = "🆓 Oddiy"
    if prem:
        st = "💎 Premium " + (f"({u['premium_expires_at']} gacha)" if u["premium_expires_at"] else "(umrbod)")
    ts = await db.get_tariffs()
    txt = f"💎 <b>Premium tariflar</b>\nHolatingiz: {st}\nBalans: <b>{fmt(u['balance'] if u else 0)}</b> so'm\n\n"
    txt += "\n".join(f"▫️ {e(t['title'])} ({days_txt(t['days'])}) — <b>{fmt(t['price'])}</b> so'm" for t in ts)
    txt += "\n\n" + e(await db.get_setting("payment_info"))
    rows = [[B(f"🛒 {t['title']} — {fmt(t['balance_price'])} so'm (balansdan)", f"buy:{t['id']}")] for t in ts]
    return txt, ikb(*rows, [B("🎁 Balans to'ldirish (taklif)", "refl")])


async def ref_page(bot, uid):
    me = await bot.me()
    r = await db.get_setting("referral_reward")
    return (f"🎁 <b>Do'stlarni taklif qiling!</b>\nHar bir yangi do'st uchun <b>{fmt(r)}</b> so'm.\n\n"
            f"👥 Takliflaringiz: <b>{await db.count_refs(uid)}</b>\n🔗 Havolangiz:\n"
            f"<code>https://t.me/{me.username}?start=ref_{uid}</code>")


@router.message(F.text == "💎 Premium sotib olish")
async def prem_m(m: Message):
    await db.add_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    t, k = await premium_page(m.from_user.id)
    await m.answer(t, reply_markup=k)


@router.callback_query(F.data == "prem")
async def prem_c(cb: CallbackQuery):
    t, k = await premium_page(cb.from_user.id)
    await cb.message.answer(t, reply_markup=k)
    await cb.answer()


@router.message(F.text == "💰 Mening balansim")
async def bal(m: Message):
    await db.add_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    u = await db.get_user(m.from_user.id)
    st = "💎 Premium" if db.is_premium(u) else "🆓 Oddiy"
    await m.answer(f"💰 Balans: <b>{fmt(u['balance'])}</b> so'm\n👤 Holat: {st}\n\n" + await ref_page(m.bot, m.from_user.id))


@router.message(F.text == "🎁 Do'stlarni taklif qilish")
async def ref_m(m: Message):
    await m.answer(await ref_page(m.bot, m.from_user.id))


@router.callback_query(F.data == "refl")
async def ref_c(cb: CallbackQuery):
    await cb.message.answer(await ref_page(cb.bot, cb.from_user.id))
    await cb.answer()


@router.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery):
    if await db.get_setting("premium_enabled") != "1":
        return await cb.answer("Premium tizimi o'chirilgan", show_alert=True)
    res = await db.buy_tariff(cb.from_user.id, int(cb.data[4:]))
    if res == "ok":
        await cb.answer("✅ Premium faollashtirildi!", show_alert=True)
        t, k = await premium_page(cb.from_user.id)
        try:
            await cb.message.edit_text(t, reply_markup=k)
        except TelegramAPIError:
            pass
    elif res == "low":
        await cb.answer("❌ Balans yetarli emas. Do'st taklif qiling yoki promokod kiriting.", show_alert=True)
    else:
        await cb.answer("Tarif topilmadi", show_alert=True)


# ---------- Promokod
@router.message(Command("promo"))
@router.message(F.text == "🎟 Promokod")
async def promo_start(m: Message, state: FSMContext):
    if await db.get_setting("promo_enabled") != "1":
        return await m.answer("⛔ Promokod bo'limi vaqtincha nofaol.")
    await state.set_state(PromoS.code)
    await m.answer("🎟 Promokodni kiriting (bekor qilish: /start):")


@router.message(PromoS.code, F.text, ~F.text.startswith("/"))
async def promo_code(m: Message, state: FSMContext):
    await state.clear()
    if await db.get_setting("promo_enabled") != "1":
        return await m.answer("⛔ Promokod bo'limi vaqtincha nofaol.")
    await db.add_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    st, amount = await db.use_promo(m.from_user.id, m.text.strip().upper())
    await m.answer({"ok": f"✅ Tabriklaymiz! Balansingizga <b>{fmt(amount)}</b> so'm qo'shildi.",
                    "notfound": "❌ Promokod noto'g'ri.", "limit": "⌛ Bu promokod limiti tugagan.",
                    "used": "⚠️ Siz bu promokodni allaqachon ishlatgansiz."}[st])


# ---------- Kod bo'yicha qidiruv (eng oxirida)
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def by_code(m: Message):
    await db.add_user(m.from_user.id, m.from_user.full_name, m.from_user.username)
    await open_code(m.bot, m.chat.id, m.from_user.id, m.text)
