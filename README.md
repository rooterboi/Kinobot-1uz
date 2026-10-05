# Kino va Serial Bot (aiogram 3 + SQLite)

## Ishga tushirish
1. `pip install -r requirements.txt`
2. `.env.example` ni `.env` ga nusxalang, BOT_TOKEN va ADMINS (ID lar, vergul bilan) ni yozing.
3. `python main.py`
4. Telegramda `/admin` — admin panel.

## Muhim
- Post kanali va majburiy obuna kanallarida bot **admin** bo'lishi shart.
- Majburiy obuna faqat Premium bo'lmagan foydalanuvchilarga qo'llanadi.
- Premium tizimi o'chirilsa — barcha kontent bepul.
- Deep-link: `t.me/BOT?start=m_KOD` (kino), `s_KOD` (serial), `ref_ID` (referal).
- FSM xotirada (MemoryStorage): qayta ishga tushganda tugallanmagan admin jarayonlari tozalanadi.
- Fayl tuzilishi: main.py, db.py (SQLite, jadvallar), kb.py, utils.py, middlewares.py, handlers/{user,admin}.py
