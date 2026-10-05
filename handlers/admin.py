import asyncio
import logging
import re
from html import escape as e
import aiosqlite
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import db
from config import ADMINS
from kb import B, ikb, level_kb
from utils import autopost, days_txt, fmt

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.from_user.id.in_(ADMINS))
router.callback_query.filter(F.from_user.id.in_(ADMINS))
TASKS = set()
TXT = F.text & ~F.text.startswith("/")
CODE_RE = re.compile(r"^[A-Z0-9_-]{1,32}$")


class M(StatesGroup): text = State(); poster = State(); level = State(); video = State()
class S(StatesGroup): text = State(); poster = State(); level = State(); video = State()
class T(StatesGroup): title = State(); days = State(); price = State(); bprice = State()
class P(StatesGroup): code = State(); amount = State(); uses = State()
class V(StatesGroup): value = State()
class U(StatesGroup): id = State(); amount = State(); msg = State()
class C(StatesGroup): add = State()
class Bc(StatesGroup): msg = State()
class D(StatesGroup): code = State()


MOVIE_STEPS = [("code", "🔑 Kino kodi (lotin harf/raqam):"), ("title", "🎬 Nomi:"), ("lang", "🌐 Tili:"),
               ("quality", "📺 Sifati (720p/1080p):"), ("desc", "📝 Tavsif (yoki -):")]
SERIES_STEPS = [("code", "🔑 Serial kodi (mavjud kod bo'lsa, shu koddagi yangi qism qo'shiladi):"), ("title", "📺 Nomi:"),
                ("season", "🔢 Fasl raqami:"), ("episode", "🔢 Qism raqami:"), ("desc", "📝 Tavsif (yoki -):")]


async def panel_kb():
    p = await db.get_setting("premium_enabled") == "1"
    q = await db.get_setting("promo_enabled") == "1"
    return ikb(
        [B(f"💎 Premium tizimi: {'✅ YOQILGAN' if p else '⛔ O`CHIRILGAN'}", "adm:tp")],
        [B(f"🎟 Promokod tizimi: {'✅ YOQILGAN' if q else '⛔ O`CHIRILGAN'}", "adm:tq")],
        [B("🎬 Kino qo'shish", "adm:movie"), B("📺 Serial qo'shish", "adm:series")],
        [B("🗑 Kontent o'chirish", "adm:del"), B("💰 Tariflar", "adm:tariffs")],
        [B("🎟 Promokodlar", "adm:promos"), B("🎁 Referal mukofoti", "adm:reward")],
        [B("📢 Post kanali", "adm:post"), B("🔗 Majburiy kanallar", "adm:chans")],
        [B("👤 Foydalanuvchi", "adm:user"), B("💳 To'lov ma'lumoti", "adm:pay")],
        [B("📊 Statistika", "adm:stats"), B("📨 Broadcast", "adm:bc")])


async def edit(cb, text, kb=None):
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await cb.answer()


async def ask(cb, state, st, text, **data):
    await state.set_data(data)
    await state.set_state(st)
    await cb.message.answer(text + "\n\n/cancel — bekor qilish")
    await cb.answer()


@router.message(Command("admin", "cancel"))
async def admin_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("🛠 <b>Admin panel</b>", reply_markup=await panel_kb())


@router.callback_query(F.data == "adm:home")
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(cb, "🛠 <b>Admin panel</b>", await panel_kb())


@router.callback_query(F.data.in_({"adm:tp", "adm:tq"}))
async def toggle(cb: CallbackQuery):
    key = "premium_enabled" if cb.data == "adm:tp" else "promo_enabled"
    await db.set_setting(key, "0" if await db.get_setting(key) == "1" else "1")
    await edit(cb, "🛠 <b>Admin panel</b>", await panel_kb())


@router.callback_query(F.data == "adm:stats")
async def stats(cb: CallbackQuery):
    s = await db.stats()
    await edit(cb, f"📊 <b>Statistika</b>\n\n👥 Foydalanuvchilar: {s['users']} (bugun +{s['today']})\n💎 Premium: {s['premium']}\n"
                   f"🎬 Kinolar: {s['movies']}\n📺 Seriallar: {s['series']} ({s['eps']} qism)\n💰 Umumiy balans: {fmt(s['balance'])} so'm",
               ikb([B("◀️ Orqaga", "adm:home")]))


# ================= Kino / serial qo'shish =================
async def step(m: Message, state: FSMContext, steps, nxt, prompt):
    d = await state.get_data()
    i = d.get("i", 0)
    key, val = steps[i][0], m.text.strip()
    if key == "code":
        val = val.upper()
        if not CODE_RE.match(val):
            return await m.answer("❌ Kod faqat lotin harf, raqam, _ va - dan iborat bo'lsin.")
        if "movie" == d.get("kind") and await db.get_movie(val):
            return await m.answer("❌ Bu kod band. Boshqa kod kiriting.")
    if key in ("season", "episode") and not val.isdigit():
        return await m.answer("❌ Raqam kiriting.")
    if key == "desc" and val == "-":
        val = ""
    await state.update_data({key: val, "i": i + 1})
    if i + 1 < len(steps):
        await m.answer(steps[i + 1][1])
    else:
        await state.set_state(nxt)
        await m.answer(prompt)


@router.callback_query(F.data == "adm:movie")
async def movie_start(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, M.text, MOVIE_STEPS[0][1], i=0, kind="movie")


@router.callback_query(F.data == "adm:series")
async def series_start(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, S.text, SERIES_STEPS[0][1], i=0, kind="series")


@router.message(M.text, TXT)
async def m_text(m: Message, state: FSMContext):
    await step(m, state, MOVIE_STEPS, M.poster, "🖼 Poster (rasm) yuboring (yoki -):")


@router.message(S.text, TXT)
async def s_text(m: Message, state: FSMContext):
    await step(m, state, SERIES_STEPS, S.poster, "🖼 Poster (rasm) yuboring (yoki -):")


async def poster(m: Message, state: FSMContext, nxt):
    if m.photo:
        await state.update_data(poster=m.photo[-1].file_id)
    elif m.text and m.text.strip() == "-":
        await state.update_data(poster=None)
    else:
        return await m.answer("❌ Rasm yuboring yoki - yozing.")
    await state.set_state(nxt)
    await m.answer("🔐 Kirish darajasini tanlang:", reply_markup=level_kb())


@router.message(M.poster)
async def m_poster(m: Message, state: FSMContext):
    await poster(m, state, M.level)


@router.message(S.poster)
async def s_poster(m: Message, state: FSMContext):
    await poster(m, state, S.level)


@router.callback_query(M.level, F.data.startswith("lvl:"))
async def m_level(cb: CallbackQuery, state: FSMContext):
    await state.update_data(level=cb.data[4:])
    await state.set_state(M.video)
    await cb.message.answer("🎞 Endi kino videosini yuboring:")
    await cb.answer()


@router.callback_query(S.level, F.data.startswith("lvl:"))
async def s_level(cb: CallbackQuery, state: FSMContext):
    await state.update_data(level=cb.data[4:])
    await state.set_state(S.video)
    await cb.message.answer("🎞 Endi qism videosini yuboring:")
    await cb.answer()


@router.message(M.video, F.video)
async def m_video(m: Message, state: FSMContext):
    d = await state.get_data()
    try:
        await db.add_movie(d["code"], d["title"], d["lang"], d["quality"], m.video.file_id, d.get("poster"), d["level"], d["desc"])
    except aiosqlite.IntegrityError:
        return await m.answer("❌ Bu kod band. /cancel va qaytadan boshlang.")
    err = await autopost(m.bot, "movie", d["code"], d["title"], d.get("poster"), d["level"], f"🌐 {d['lang']} | 📺 {d['quality']}\n{d['desc']}")
    await state.clear()
    await m.answer("✅ Kino saqlandi!" + (f"\n⚠️ Postda xato: {e(err)}" if err else ""), reply_markup=ikb([B("🛠 Panel", "adm:home")]))


@router.message(S.video, F.video)
async def s_video(m: Message, state: FSMContext):
    d = await state.get_data()
    try:
        await db.add_episode(d["code"], d["title"], int(d["season"]), int(d["episode"]), m.video.file_id, d.get("poster"), d["level"], d["desc"])
    except aiosqlite.IntegrityError:
        return await m.answer("❌ Bu fasl/qism allaqachon mavjud.")
    err = await autopost(m.bot, "series", d["code"], f"{d['title']} — {d['season']}-fasl {d['episode']}-qism",
                         d.get("poster"), d["level"], d["desc"])
    await m.answer(f"✅ {d['season']}-fasl {d['episode']}-qism saqlandi!" + (f"\n⚠️ Postda xato: {e(err)}" if err else ""),
                   reply_markup=ikb([B("➕ Keyingi qism", "adm:nx")], [B("✅ Tugatish", "adm:home")]))


@router.callback_query(S.video, F.data == "adm:nx")
async def next_ep(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    n = int(d["episode"]) + 1
    await state.update_data(episode=str(n))
    await cb.message.answer(f"🎞 {d['season']}-fasl {n}-qism videosini yuboring:")
    await cb.answer()


# ================= Kontent o'chirish =================
@router.callback_query(F.data == "adm:del")
async def del_start(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, D.code, "🗑 O'chiriladigan kino/serial kodi:")


@router.message(D.code, TXT)
async def del_code(m: Message, state: FSMContext):
    n = await db.delete_content(m.text.strip().upper())
    await state.clear()
    await m.answer(f"🗑 O'chirildi: {n} ta yozuv." if n else "❌ Kod topilmadi.", reply_markup=ikb([B("🛠 Panel", "adm:home")]))


# ================= Tariflar =================
@router.callback_query(F.data == "adm:tariffs")
async def tariffs(cb: CallbackQuery):
    ts = await db.get_tariffs()
    txt = "💰 <b>Tariflar</b>\n\n" + ("\n".join(f"{t['id']}. {e(t['title'])} — {days_txt(t['days'])} | narx {fmt(t['price'])} | balansdan {fmt(t['balance_price'])}" for t in ts) or "Tariflar yo'q")
    await edit(cb, txt, ikb(*[[B(f"🗑 {t['title']}", f"td:{t['id']}")] for t in ts], [B("➕ Yangi tarif", "adm:tadd")], [B("◀️ Orqaga", "adm:home")]))


@router.callback_query(F.data.startswith("td:"))
async def tariff_del(cb: CallbackQuery):
    await db.del_tariff(int(cb.data[3:]))
    await tariffs(cb)


@router.callback_query(F.data == "adm:tadd")
async def tariff_add(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, T.title, "Tarif nomi (masalan: 1 oylik):")


@router.message(T.title, TXT)
async def t_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip())
    await state.set_state(T.days)
    await m.answer("Necha kun? (umrbod uchun 0):")


@router.message(T.days, TXT)
async def t_days(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ Raqam kiriting.")
    await state.update_data(days=int(m.text))
    await state.set_state(T.price)
    await m.answer("Narxi (so'm):")


@router.message(T.price, TXT)
async def t_price(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ Raqam kiriting.")
    await state.update_data(price=int(m.text))
    await state.set_state(T.bprice)
    await m.answer("Ichki balans orqali xarid narxi (so'm):")


@router.message(T.bprice, TXT)
async def t_bprice(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ Raqam kiriting.")
    d = await state.get_data()
    await db.add_tariff(d["title"], d["days"], d["price"], int(m.text))
    await state.clear()
    await m.answer("✅ Tarif qo'shildi.", reply_markup=ikb([B("💰 Tariflar", "adm:tariffs")]))


# ================= Promokodlar =================
@router.callback_query(F.data == "adm:promos")
async def promos(cb: CallbackQuery):
    ps = await db.list_promos()
    txt = "🎟 <b>Promokodlar</b>\n\n" + ("\n".join(f"<code>{e(p['code'])}</code> — {fmt(p['reward_amount'])} so'm | {p['current_uses']}/{p['max_uses']}" for p in ps) or "Hozircha yo'q")
    await edit(cb, txt, ikb(*[[B(f"🗑 {p['code']}", f"pd:{p['id']}")] for p in ps], [B("➕ Yangi promokod", "adm:padd")], [B("◀️ Orqaga", "adm:home")]))


@router.callback_query(F.data.startswith("pd:"))
async def promo_del(cb: CallbackQuery):
    await db.del_promo(int(cb.data[3:]))
    await promos(cb)


@router.callback_query(F.data == "adm:padd")
async def promo_add(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, P.code, "Promokod nomi (lotin harf/raqam):")


@router.message(P.code, TXT)
async def p_code(m: Message, state: FSMContext):
    c = m.text.strip().upper()
    if not CODE_RE.match(c):
        return await m.answer("❌ Faqat lotin harf, raqam, _ va -.")
    await state.update_data(code=c)
    await state.set_state(P.amount)
    await m.answer("Mukofot miqdori (so'm):")


@router.message(P.amount, TXT)
async def p_amount(m: Message, state: FSMContext):
    if not m.text.isdigit() or int(m.text) <= 0:
        return await m.answer("❌ Musbat raqam kiriting.")
    await state.update_data(amount=int(m.text))
    await state.set_state(P.uses)
    await m.answer("Necha kishi ishlata oladi (limit):")


@router.message(P.uses, TXT)
async def p_uses(m: Message, state: FSMContext):
    if not m.text.isdigit() or int(m.text) <= 0:
        return await m.answer("❌ Musbat raqam kiriting.")
    d = await state.get_data()
    try:
        await db.add_promo(d["code"], d["amount"], int(m.text))
    except aiosqlite.IntegrityError:
        await state.clear()
        return await m.answer("❌ Bunday promokod mavjud.")
    await state.clear()
    await m.answer(f"✅ Yaratildi: <code>{d['code']}</code> — {fmt(d['amount'])} so'm, limit {m.text}", reply_markup=ikb([B("🎟 Promokodlar", "adm:promos")]))


# ================= Sozlamalar (referal, post kanal, to'lov) =================
SETTINGS = {"adm:reward": ("referral_reward", "🎁 1 ta taklif uchun mukofot (so'm). Hozirgi: "),
            "adm:post": ("post_channel", "📢 Post kanali (@username yoki -100... ID). O'chirish uchun -. Hozirgi: "),
            "adm:pay": ("payment_info", "💳 To'lov ko'rsatmasi matni. Hozirgi:\n")}


@router.callback_query(F.data.in_(set(SETTINGS)))
async def setting_start(cb: CallbackQuery, state: FSMContext):
    key, txt = SETTINGS[cb.data]
    await ask(cb, state, V.value, txt + e(await db.get_setting(key) or "—"), key=key)


@router.message(V.value, TXT)
async def setting_save(m: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    val = m.text.strip()
    if key == "referral_reward" and not val.isdigit():
        return await m.answer("❌ Raqam kiriting.")
    if key == "post_channel":
        if val == "-":
            val = ""
        else:
            try:
                await m.bot.get_chat(int(val) if val.lstrip("-").isdigit() else val)
            except TelegramAPIError as ex:
                return await m.answer(f"❌ Kanal topilmadi yoki bot admin emas: {e(str(ex))}")
    await db.set_setting(key, val)
    await state.clear()
    await m.answer("✅ Saqlandi.", reply_markup=ikb([B("🛠 Panel", "adm:home")]))


# ================= Majburiy obuna kanallari =================
@router.callback_query(F.data == "adm:chans")
async def chans(cb: CallbackQuery):
    cs = await db.get_channels()
    await edit(cb, "🔗 <b>Majburiy kanallar</b>\n(Bot kanalda admin bo'lishi shart)\n\n" + ("\n".join(f"• {e(c['title'] or '')} ({c['chat_id']})" for c in cs) or "Yo'q"),
               ikb(*[[B(f"🗑 {c['title']}", f"cd:{c['id']}")] for c in cs], [B("➕ Kanal qo'shish", "adm:cadd")], [B("◀️ Orqaga", "adm:home")]))


@router.callback_query(F.data.startswith("cd:"))
async def chan_del(cb: CallbackQuery):
    await db.del_channel(int(cb.data[3:]))
    await chans(cb)


@router.callback_query(F.data == "adm:cadd")
async def chan_add(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, C.add, "Kanal @username yoki ID sini yuboring (bot kanalda admin bo'lsin):")


@router.message(C.add, TXT)
async def chan_save(m: Message, state: FSMContext):
    v = m.text.strip()
    try:
        chat = await m.bot.get_chat(int(v) if v.lstrip("-").isdigit() else v)
        url = f"https://t.me/{chat.username}" if chat.username else (chat.invite_link or await m.bot.export_chat_invite_link(chat.id))
    except TelegramAPIError as ex:
        return await m.answer(f"❌ Xato: {e(str(ex))}\nBot kanalda admin ekanini tekshiring.")
    await db.add_channel(chat.id, chat.title, url)
    await state.clear()
    await m.answer(f"✅ Qo'shildi: {e(chat.title or '')}", reply_markup=ikb([B("🔗 Kanallar", "adm:chans")]))


# ================= Foydalanuvchini boshqarish =================
def uinfo(u):
    import db as _d
    st = "💎 Premium" + (f" ({u['premium_expires_at']} gacha)" if u["premium_expires_at"] else " (umrbod)") if _d.is_premium(u) else "🆓 Oddiy"
    return f"👤 <b>{e(u['full_name'] or '—')}</b> (<code>{u['user_id']}</code>)\nHolat: {st}\nBalans: {fmt(u['balance'])} so'm\nQo'shilgan: {u['created_at']}"


def ukb(uid):
    return ikb([B("💎 +30 kun", f"um:pr:{uid}:30"), B("💎 +90 kun", f"um:pr:{uid}:90")],
               [B("💎 Umrbod", f"um:pr:{uid}:0"), B("❌ Premium olish", f"um:rm:{uid}")],
               [B("➕ Balans", f"um:ba:{uid}"), B("0️⃣ Balansni nol", f"um:bz:{uid}")],
               [B("✉️ Xabar yuborish", f"um:msg:{uid}")], [B("◀️ Orqaga", "adm:home")])


@router.callback_query(F.data == "adm:user")
async def user_start(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, U.id, "Foydalanuvchi ID sini yuboring:")


@router.message(U.id, TXT)
async def user_id(m: Message, state: FSMContext):
    if not m.text.strip().isdigit():
        return await m.answer("❌ Raqamli ID yuboring.")
    u = await db.get_user(int(m.text))
    if not u:
        return await m.answer("❌ Bu foydalanuvchi botda yo'q.")
    await state.clear()
    await m.answer(uinfo(u), reply_markup=ukb(u["user_id"]))


@router.callback_query(F.data.startswith("um:"))
async def um(cb: CallbackQuery, state: FSMContext):
    p = cb.data.split(":")
    act, uid = p[1], int(p[2])
    if act == "pr":
        await db.grant_premium(uid, int(p[3]))
        try:
            await cb.bot.send_message(uid, "🎉 Sizga <b>Premium</b> berildi!")
        except TelegramAPIError:
            pass
    elif act == "rm":
        await db.revoke_premium(uid)
    elif act == "bz":
        await db.set_balance(uid, 0)
    elif act == "ba":
        return await ask(cb, state, U.amount, "💵 Summa (manfiy bo'lsa ayiriladi):", uid=uid)
    elif act == "msg":
        return await ask(cb, state, U.msg, "✉️ Xabar matni:", uid=uid)
    u = await db.get_user(uid)
    await edit(cb, uinfo(u), ukb(uid))


@router.message(U.amount, TXT)
async def u_amount(m: Message, state: FSMContext):
    if not m.text.strip().lstrip("-").isdigit():
        return await m.answer("❌ Raqam kiriting.")
    uid = (await state.get_data())["uid"]
    await db.add_balance(uid, int(m.text))
    await state.clear()
    await m.answer(uinfo(await db.get_user(uid)), reply_markup=ukb(uid))


@router.message(U.msg, TXT)
async def u_msg(m: Message, state: FSMContext):
    uid = (await state.get_data())["uid"]
    await state.clear()
    try:
        await m.bot.send_message(uid, m.text)
        await m.answer("✅ Yuborildi.")
    except TelegramAPIError as ex:
        await m.answer(f"❌ Yuborib bo'lmadi: {e(str(ex))}")


# ================= Broadcast =================
@router.callback_query(F.data == "adm:bc")
async def bc_start(cb: CallbackQuery, state: FSMContext):
    await ask(cb, state, Bc.msg, "📨 Tarqatiladigan xabarni yuboring (matn/rasm/video):")


async def _send(bot, uid, chat, mid):
    try:
        await bot.copy_message(uid, chat, mid)
        return True
    except TelegramRetryAfter as ex:
        await asyncio.sleep(ex.retry_after)
        return await _send(bot, uid, chat, mid)
    except TelegramAPIError:
        return False


async def _broadcast(bot, chat, mid):
    ok = fail = 0
    for uid in await db.all_user_ids():
        if await _send(bot, uid, chat, mid):
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(0.04)
    await bot.send_message(chat, f"📨 Broadcast tugadi.\n✅ Yetkazildi: {ok}\n❌ Xato: {fail}")


@router.message(Bc.msg)
async def bc_run(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("📨 Yuborish boshlandi, tugagach xabar beraman.")
    t = asyncio.create_task(_broadcast(m.bot, m.chat.id, m.message_id))
    TASKS.add(t)
    t.add_done_callback(TASKS.discard)
