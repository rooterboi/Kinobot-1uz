import logging
from datetime import datetime, timedelta
import aiosqlite
from config import DB_PATH

log = logging.getLogger(__name__)
FMT = "%Y-%m-%d %H:%M:%S"
LV = "CHECK(access_level IN ('all','free','premium'))"

SCHEMA = f"""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT,
 balance INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'free', premium_expires_at TEXT,
 referrer_id INTEGER, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')));
CREATE INDEX IF NOT EXISTS ix_ref ON users(referrer_id);
CREATE TABLE IF NOT EXISTS movies(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
 language TEXT, quality TEXT, file_id TEXT NOT NULL, poster_id TEXT, access_level TEXT NOT NULL DEFAULT 'all' {LV}, description TEXT);
CREATE TABLE IF NOT EXISTS series(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, title TEXT NOT NULL,
 season INTEGER NOT NULL, episode INTEGER NOT NULL, file_id TEXT NOT NULL, poster_id TEXT, description TEXT,
 access_level TEXT NOT NULL DEFAULT 'all' {LV}, UNIQUE(code,season,episode));
CREATE INDEX IF NOT EXISTS ix_series_code ON series(code);
CREATE TABLE IF NOT EXISTS promocodes(id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
 reward_amount INTEGER NOT NULL, max_uses INTEGER NOT NULL, current_uses INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS promo_usage(user_id INTEGER NOT NULL, promo_id INTEGER NOT NULL REFERENCES promocodes(id) ON DELETE CASCADE,
 PRIMARY KEY(user_id,promo_id));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS channels(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER UNIQUE NOT NULL, title TEXT, url TEXT);
CREATE TABLE IF NOT EXISTS tariffs(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, days INTEGER NOT NULL,
 price INTEGER NOT NULL, balance_price INTEGER NOT NULL);
"""
DEFAULTS = {"premium_enabled": "1", "promo_enabled": "1", "referral_reward": "1000", "post_channel": "",
            "payment_info": "💳 To'lov uchun admin bilan bog'laning va chekni yuboring."}


def now():
    return datetime.now().strftime(FMT)


def connect():
    return aiosqlite.connect(DB_PATH, timeout=30)


async def run(sql, args=(), fetch=None):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        cur = await db.execute(sql, args)
        res = cur.rowcount
        if fetch == "one":
            res = await cur.fetchone()
        elif fetch == "all":
            res = await cur.fetchall()
        await db.commit()
        return res


async def init_db():
    async with connect() as db:
        await db.executescript(SCHEMA)
        for k, v in DEFAULTS.items():
            await db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
        if (await (await db.execute("SELECT COUNT(*) FROM tariffs")).fetchone())[0] == 0:
            await db.executemany("INSERT INTO tariffs(title,days,price,balance_price) VALUES(?,?,?,?)",
                                 [("1 oylik", 30, 20000, 20000), ("3 oylik", 90, 50000, 50000), ("Umrbod", 0, 150000, 150000)])
        await db.commit()


# ---- settings
async def get_setting(key):
    r = await run("SELECT value FROM settings WHERE key=?", (key,), "one")
    return r["value"] if r else DEFAULTS.get(key, "")


async def set_setting(key, value):
    await run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ---- users
async def add_user(uid, name, username, ref=None):
    return await run("INSERT OR IGNORE INTO users(user_id,full_name,username,referrer_id) VALUES(?,?,?,?)",
                     (uid, name, username, ref)) == 1


async def get_user(uid):
    return await run("SELECT * FROM users WHERE user_id=?", (uid,), "one")


def is_premium(u):
    if not u or u["status"] != "premium":
        return False
    return u["premium_expires_at"] is None or u["premium_expires_at"] > now()


async def add_balance(uid, amount):
    await run("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    await run("UPDATE users SET balance=MAX(0,balance+?) WHERE user_id=?", (amount, uid))


async def set_balance(uid, amount):
    await run("UPDATE users SET balance=? WHERE user_id=?", (amount, uid))


async def count_refs(uid):
    return (await run("SELECT COUNT(*) c FROM users WHERE referrer_id=?", (uid,), "one"))["c"]


async def all_user_ids():
    return [r["user_id"] for r in await run("SELECT user_id FROM users", fetch="all")]


async def _grant(db, uid, days):
    await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
    cur = await (await db.execute("SELECT status,premium_expires_at FROM users WHERE user_id=?", (uid,))).fetchone()
    exp = None
    if days:
        base = datetime.now()
        if cur["status"] == "premium":
            if cur["premium_expires_at"] is None:
                return
            old = datetime.strptime(cur["premium_expires_at"], FMT)
            base = max(base, old)
        exp = (base + timedelta(days=days)).strftime(FMT)
    await db.execute("UPDATE users SET status='premium',premium_expires_at=? WHERE user_id=?", (exp, uid))


async def grant_premium(uid, days):
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        await _grant(db, uid, days)
        await db.commit()


async def revoke_premium(uid):
    await run("UPDATE users SET status='free',premium_expires_at=NULL WHERE user_id=?", (uid,))


async def buy_tariff(uid, tid):
    """Atomik: balansdan yechish + premium berish. -> ok / low / none"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            t = await (await db.execute("SELECT * FROM tariffs WHERE id=?", (tid,))).fetchone()
            if not t:
                await db.rollback()
                return "none"
            cur = await db.execute("UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
                                   (t["balance_price"], uid, t["balance_price"]))
            if cur.rowcount == 0:
                await db.rollback()
                return "low"
            await _grant(db, uid, t["days"])
            await db.commit()
            return "ok"
        except Exception:
            await db.rollback()
            raise


# ---- content
async def add_movie(code, title, lang, quality, file_id, poster, level, desc):
    await run("INSERT INTO movies(code,title,language,quality,file_id,poster_id,access_level,description) VALUES(?,?,?,?,?,?,?,?)",
              (code, title, lang, quality, file_id, poster, level, desc))


async def get_movie(code):
    return await run("SELECT * FROM movies WHERE code=?", (code,), "one")


async def add_episode(code, title, season, ep, file_id, poster, level, desc):
    await run("INSERT INTO series(code,title,season,episode,file_id,poster_id,access_level,description) VALUES(?,?,?,?,?,?,?,?)",
              (code, title, season, ep, file_id, poster, level, desc))


async def get_series(code):
    return await run("SELECT * FROM series WHERE code=? ORDER BY season,episode", (code,), "all")


async def get_episode(eid):
    return await run("SELECT * FROM series WHERE id=?", (eid,), "one")


async def delete_content(code):
    a = await run("DELETE FROM movies WHERE code=?", (code,))
    b = await run("DELETE FROM series WHERE code=?", (code,))
    return a + b


# ---- promo
async def add_promo(code, amount, uses):
    await run("INSERT INTO promocodes(code,reward_amount,max_uses) VALUES(?,?,?)", (code, amount, uses))


async def list_promos():
    return await run("SELECT * FROM promocodes ORDER BY id DESC LIMIT 30", fetch="all")


async def del_promo(pid):
    await run("DELETE FROM promocodes WHERE id=?", (pid,))


async def use_promo(uid, code):
    """-> (status, reward): ok / notfound / limit / used"""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute("BEGIN IMMEDIATE")
        try:
            p = await (await db.execute("SELECT * FROM promocodes WHERE code=?", (code,))).fetchone()
            if not p:
                await db.rollback()
                return "notfound", 0
            if p["current_uses"] >= p["max_uses"]:
                await db.rollback()
                return "limit", 0
            try:
                await db.execute("INSERT INTO promo_usage(user_id,promo_id) VALUES(?,?)", (uid, p["id"]))
            except aiosqlite.IntegrityError:
                await db.rollback()
                return "used", 0
            await db.execute("UPDATE promocodes SET current_uses=current_uses+1 WHERE id=?", (p["id"],))
            await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (uid,))
            await db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (p["reward_amount"], uid))
            await db.commit()
            return "ok", p["reward_amount"]
        except Exception:
            await db.rollback()
            raise


# ---- tariffs / channels
async def get_tariffs():
    return await run("SELECT * FROM tariffs ORDER BY days=0, days", fetch="all")


async def add_tariff(title, days, price, bprice):
    await run("INSERT INTO tariffs(title,days,price,balance_price) VALUES(?,?,?,?)", (title, days, price, bprice))


async def del_tariff(tid):
    await run("DELETE FROM tariffs WHERE id=?", (tid,))


async def get_channels():
    return await run("SELECT * FROM channels", fetch="all")


async def add_channel(chat_id, title, url):
    await run("INSERT OR REPLACE INTO channels(chat_id,title,url) VALUES(?,?,?)", (chat_id, title, url))


async def del_channel(cid):
    await run("DELETE FROM channels WHERE id=?", (cid,))


async def stats():
    q = lambda s, a=(): run(s, a, "one")
    n = now()
    return {
        "users": (await q("SELECT COUNT(*) c FROM users"))["c"],
        "premium": (await q("SELECT COUNT(*) c FROM users WHERE status='premium' AND (premium_expires_at IS NULL OR premium_expires_at>?)", (n,)))["c"],
        "today": (await q("SELECT COUNT(*) c FROM users WHERE date(created_at)=date('now','localtime')"))["c"],
        "movies": (await q("SELECT COUNT(*) c FROM movies"))["c"],
        "series": (await q("SELECT COUNT(DISTINCT code) c FROM series"))["c"],
        "eps": (await q("SELECT COUNT(*) c FROM series"))["c"],
        "balance": (await q("SELECT COALESCE(SUM(balance),0) c FROM users"))["c"],
    }
