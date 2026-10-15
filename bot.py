import asyncio
import logging
import os
import sqlite3
import time
from io import BytesIO
from openpyxl import Workbook

import qrcode
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
)
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_PATH = os.getenv("DATABASE_PATH", "lotereya.db")
HOLD_SECONDS = 3600

if not TOKEN:
    raise RuntimeError("BOT_TOKEN .env yoki Render Environment ichida kiritilmagan.")
if not ADMIN_IDS:
    logging.warning("ADMIN_IDS kiritilmagan: operator paneli ishlamaydi.")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
bot = Bot(TOKEN)
dp = Dispatcher()

class Registration(StatesGroup):
    name = State()
    phone = State()

class Buying(StatesGroup):
    number = State()
    receipt = State()

class Support(StatesGroup):
    message = State()

class Operator(StatesGroup):
    price = State()
    card = State()
    broadcast = State()
    reply = State()


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con



def build_round_excel(round_id: int):
    """Joriy o'yinda chipta yozuvi bor foydalanuvchilarni Excelga chiqaradi."""
    with connect() as c:
        rows = c.execute(
            """SELECT t.number, t.user_id, u.name, u.phone
               FROM tickets AS t
               LEFT JOIN users AS u ON u.user_id = t.user_id
               WHERE t.round_id = ?
               ORDER BY t.created_at ASC, t.id ASC""",
            (round_id,),
        ).fetchall()
    if not rows:
        return None, 0

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Chipta egalari"
    sheet.append(["Ism-familiya", "Telefon raqami", "Telegram ID", "Chipta raqami"])
    for row in rows:
        sheet.append([
            row["name"] or "",
            row["phone"] or "",
            row["user_id"],
            row["number"],
        ])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in {"A": 28, "B": 20, "C": 18, "D": 18}.items():
        sheet.column_dimensions[column].width = width

    output = BytesIO()
    workbook.save(output)
    return BufferedInputFile(
        output.getvalue(),
        filename=f"lotereya_{round_id}_chipta_egalari.xlsx",
    ), len(rows)

def init_db():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL,
            created_at INTEGER NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS rounds(
            id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL,
            created_at INTEGER NOT NULL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS tickets(
            id INTEGER PRIMARY KEY AUTOINCREMENT, round_id INTEGER NOT NULL,
            number TEXT NOT NULL, user_id INTEGER NOT NULL, status TEXT NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER, receipt_file_id TEXT,
            UNIQUE(round_id, number, status))""")
        c.execute("""CREATE TABLE IF NOT EXISTS support_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            message TEXT, created_at INTEGER NOT NULL)""")
        if not c.execute("SELECT id FROM rounds WHERE status='active'").fetchone():
            c.execute("INSERT INTO rounds(status,created_at) VALUES('active',?)", (int(time.time()),))
        for key, value in {"ticket_price": "10000", "card_number": "ADMIN_KIRITADI", "buying_open": "1"}.items():
            c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))


def get_setting(key, default=""):
    with connect() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with connect() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def active_round_id():
    with connect() as c:
        row = c.execute("SELECT id FROM rounds WHERE status='active' ORDER BY id DESC LIMIT 1").fetchone()
        return row["id"] if row else None


def expire_holds():
    now = int(time.time())
    with connect() as c:
        c.execute("UPDATE tickets SET status='expired' WHERE status IN ('reserved','pending') AND expires_at IS NOT NULL AND expires_at < ?", (now,))


def is_operator(user_id):
    return user_id in ADMIN_IDS


def user_menu(user_id):
    rows = [
        [KeyboardButton(text="🎟 Mening chiptalarim"), KeyboardButton(text="🎫 Chipta olish")],
        [KeyboardButton(text="💬 Adminga yozish")],
    ]
    if is_operator(user_id):
        rows.append([KeyboardButton(text="⚙️ Operator paneli")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def operator_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Chipta narxi", callback_data="op:price"), InlineKeyboardButton(text="💳 Karta raqami", callback_data="op:card")],
        [InlineKeyboardButton(text="⛔ Chipta olishni to‘xtatish", callback_data="op:stop"), InlineKeyboardButton(text="✅ Chipta olishni ochish", callback_data="op:open")],
        [InlineKeyboardButton(text="📣 Hammaga xabar", callback_data="op:broadcast")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="op:stats")],
        [InlineKeyboardButton(text="🧹 Joriy o‘yin chiptalarini o‘chirish", callback_data="op:clear")],
        [InlineKeyboardButton(text="🆕 Yangi o‘yin boshlash", callback_data="op:newround")],
    ])


def get_user(user_id):
    with connect() as c:
        return c.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def ticket_taken(number):
    expire_holds()
    with connect() as c:
        row = c.execute("""SELECT id FROM tickets WHERE round_id=? AND number=?
          AND status IN ('reserved','pending','confirmed') LIMIT 1""", (active_round_id(), number)).fetchone()
        return row is not None


def make_qr(text):
    image = qrcode.make(text)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return BufferedInputFile(buf.getvalue(), filename="tolov_qr.png")


async def broadcast_all(text, photo_id=None):
    with connect() as c:
        users = c.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for row in users:
        try:
            if photo_id:
                await bot.send_photo(row["user_id"], photo_id, caption=text)
            else:
                await bot.send_message(row["user_id"], text)
            sent += 1
            await asyncio.sleep(0.04)
        except Exception:
            pass
    return sent


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    user = get_user(message.from_user.id)
    if user:
        await message.answer(f"Assalomu alaykum, {user['name']}! Lotereya botiga xush kelibsiz.", reply_markup=user_menu(message.from_user.id))
        return
    await message.answer(
        "🎟 Lotereya botiga xush kelibsiz!\n\n"
        "Ro‘yxatdan o‘tish uchun ism-familiyangizni kiriting.\n\n"
        "Telefon raqami aloqa va sovrinni topshirish masalalarida bog‘lanish uchun kerak. "
        "Ma’lumotlaringizni to‘g‘ri kiriting."
    )
    await state.set_state(Registration.name)


@dp.message(Registration.name)
async def registration_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 80:
        await message.answer("Iltimos, ism-familiyangizni to‘g‘ri kiriting.")
        return
    await state.update_data(name=name)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)],
        [KeyboardButton(text="Raqamni qo‘lda kiritish")],
    ], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Telefon raqamingizni yuboring yoki qo‘lda kiriting. Masalan: +998901234567", reply_markup=kb)
    await state.set_state(Registration.phone)


@dp.message(Registration.phone)
async def registration_phone(message: Message, state: FSMContext):
    if message.contact:
        if message.contact.user_id and message.contact.user_id != message.from_user.id:
            await message.answer("Iltimos, o‘zingizning telefon raqamingizni yuboring.")
            return
        phone = message.contact.phone_number
    else:
        raw = (message.text or "").strip()
        if raw == "Raqamni qo‘lda kiritish":
            await message.answer("Telefon raqamingizni xalqaro formatda kiriting. Masalan: +998901234567")
            return
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not 9 <= len(digits) <= 15:
            await message.answer("Telefon raqami noto‘g‘ri. Masalan: +998901234567")
            return
        phone = raw
    data = await state.get_data()
    with connect() as c:
        c.execute("INSERT OR REPLACE INTO users(user_id,name,phone,created_at) VALUES(?,?,?,?)",
                  (message.from_user.id, data["name"], phone, int(time.time())))
    await state.clear()
    await message.answer("✅ Ro‘yxatdan o‘tish yakunlandi!", reply_markup=user_menu(message.from_user.id))


@dp.message(F.text == "🎟 Mening chiptalarim")
async def my_tickets(message: Message):
    if not get_user(message.from_user.id):
        await message.answer("Avval /start orqali ro‘yxatdan o‘ting.")
        return
    expire_holds()
    with connect() as c:
        rows = c.execute("""SELECT number,status,expires_at FROM tickets WHERE user_id=? AND round_id=?
        AND status IN ('confirmed','reserved','pending') ORDER BY number""", (message.from_user.id, active_round_id())).fetchall()
    if not rows:
        await message.answer("Hozircha joriy o‘yinda chiptalaringiz yo‘q.")
        return
    labels = {"confirmed": "✅ Tasdiqlangan", "reserved": "⏳ To‘lov kutilmoqda", "pending": "🔎 Tekshirilmoqda"}
    await message.answer("🎟 Mening chiptalarim:\n" + "\n".join(f"• {r['number']} — {labels.get(r['status'], r['status'])}" for r in rows))


@dp.message(F.text == "🎫 Chipta olish")
async def buy_start(message: Message, state: FSMContext):
    if not get_user(message.from_user.id):
        await message.answer("Avval /start orqali ro‘yxatdan o‘ting.")
        return
    if get_setting("buying_open", "1") != "1":
        await message.answer("⛔ Chipta olish tugadi. Yangi o‘yin e’lon qilinishini kuting.")
        return
    await message.answer("1–6 xonali chipta raqamini kiriting. Masalan: 123456")
    await state.set_state(Buying.number)


@dp.message(Buying.number)
async def choose_number(message: Message, state: FSMContext):
    number = (message.text or "").strip()
    if not number.isdigit() or not 1 <= len(number) <= 6:
        await message.answer("Faqat 1–6 xonali son kiriting.")
        return
    if get_setting("buying_open", "1") != "1":
        await state.clear()
        await message.answer("⛔ Chipta olish tugadi.")
        return
    expire_holds()
    rid = active_round_id()
    now = int(time.time())
    # BEGIN IMMEDIATE prevents two users reserving the same number simultaneously.
    with connect() as c:
        c.execute("BEGIN IMMEDIATE")
        existing = c.execute("SELECT id FROM tickets WHERE round_id=? AND number=? AND status IN ('reserved','pending','confirmed')", (rid, number)).fetchone()
        if existing:
            c.rollback()
            await message.answer("❌ Bu raqam bor. Boshqa raqam kiriting.")
            return
        c.execute("INSERT INTO tickets(round_id,number,user_id,status,created_at,expires_at) VALUES(?,?,?,?,?,?)",
                  (rid, number, message.from_user.id, "reserved", now, now + HOLD_SECONDS))
        c.commit()
    await state.update_data(ticket_number=number)
    price = get_setting("ticket_price", "10000")
    card = get_setting("card_number", "ADMIN_KIRITADI")
    payment_text = (f"🎟 Chipta: {number}\n💵 Narxi: {price} so‘m\n\n💳 To‘lov uchun karta:\n{card}\n\n"
                    "To‘lov qilgach, «To‘ladim» tugmasini bosing va chek rasmini yuboring. "
                    "Chipta raqami 1 soatga band qilinadi.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ To‘ladim", callback_data="paid")]])
    try:
        await message.answer_photo(make_qr(card), caption=payment_text, reply_markup=kb)
    except Exception:
        await message.answer(payment_text, reply_markup=kb)
    await state.set_state(Buying.receipt)


@dp.callback_query(F.data == "paid")
async def paid(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("ticket_number"):
        await call.answer("Chipta tanlanmagan. Qaytadan boshlang.", show_alert=True)
        return
    await call.answer()
    await call.message.answer("To‘lov chekini rasm sifatida yuboring.")


@dp.message(Buying.receipt, F.photo)
async def receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    number = data.get("ticket_number")
    if not number:
        await message.answer("Chipta topilmadi. Qaytadan boshlang.")
        await state.clear()
        return
    expire_holds()
    with connect() as c:
        row = c.execute("SELECT id FROM tickets WHERE round_id=? AND number=? AND user_id=? AND status='reserved' ORDER BY id DESC LIMIT 1",
                        (active_round_id(), number, message.from_user.id)).fetchone()
        if not row:
            await message.answer("⏰ Band qilish muddati tugagan yoki chipta mavjud emas. Qaytadan urinib ko‘ring.")
            await state.clear()
            return
        c.execute("UPDATE tickets SET status='pending',receipt_file_id=? WHERE id=?", (message.photo[-1].file_id, row["id"]))
    user = get_user(message.from_user.id)
    caption = (f"🧾 TO‘LOVNI TEKSHIRISH\nIsm: {user['name']}\nTelefon: {user['phone']}\n"
               f"Telegram ID: {message.from_user.id}\nChipta: {number}\nNarx: {get_setting('ticket_price')} so‘m")
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha, tushdi", callback_data=f"approve:{row['id']}"),
        InlineKeyboardButton(text="❌ Yo‘q, tushmadi", callback_data=f"reject:{row['id']}")]])
    for aid in ADMIN_IDS:
        try:
            await bot.send_photo(aid, message.photo[-1].file_id, caption=caption, reply_markup=kb)
        except Exception as exc:
            log.warning("Admin xabari yuborilmadi: %s", exc)
    await message.answer("✅ Chek operatorga yuborildi. To‘lov tekshirilmoqda.", reply_markup=user_menu(message.from_user.id))
    await state.clear()


@dp.callback_query(F.data.startswith("approve:"))
async def approve(call: CallbackQuery):
    if not is_operator(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True); return
    tid = int(call.data.split(":", 1)[1])
    with connect() as c:
        row = c.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
        if not row or row["status"] != "pending":
            await call.answer("To‘lov avval ko‘rib chiqilgan.", show_alert=True); return
        if row["expires_at"] and row["expires_at"] < int(time.time()):
            c.execute("UPDATE tickets SET status='expired' WHERE id=?", (tid,))
            await call.answer("Bir soatlik muddat tugagan.", show_alert=True); return
        c.execute("UPDATE tickets SET status='confirmed',expires_at=NULL WHERE id=?", (tid,))
    await bot.send_message(row["user_id"], f"✅ To‘lov tasdiqlandi! {row['number']} raqamli chipta «Mening chiptalarim» bo‘limiga qo‘shildi.", reply_markup=user_menu(row["user_id"]))
    await call.message.edit_caption((call.message.caption or "") + "\n\n✅ TO‘LOV TASDIQLANDI", reply_markup=None)
    await call.answer("Tasdiqlandi")


@dp.callback_query(F.data.startswith("reject:"))
async def reject(call: CallbackQuery):
    if not is_operator(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True); return
    tid = int(call.data.split(":", 1)[1])
    with connect() as c:
        row = c.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
        if not row or row["status"] != "pending":
            await call.answer("To‘lov avval ko‘rib chiqilgan.", show_alert=True); return
        c.execute("UPDATE tickets SET status='rejected',expires_at=NULL WHERE id=?", (tid,))
    await bot.send_message(row["user_id"], f"❌ {row['number']} raqamli chipta to‘lovi rad etildi. Operator bilan bog‘laning yoki qaytadan urinib ko‘ring.", reply_markup=user_menu(row["user_id"]))
    await call.message.edit_caption((call.message.caption or "") + "\n\n❌ TO‘LOV RAD ETILDI", reply_markup=None)
    await call.answer("Rad etildi")


@dp.message(F.text == "💬 Adminga yozish")
async def support_start(message: Message, state: FSMContext):
    await message.answer("Muammoingizni matn yoki rasm bilan yuboring. Operatorga yetkazamiz.")
    await state.set_state(Support.message)


@dp.message(Support.message)
async def support_send(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Avval /start orqali ro‘yxatdan o‘ting."); await state.clear(); return
    body = message.caption or message.text or "[Rasm yoki fayl]"
    with connect() as c:
        c.execute("INSERT INTO support_messages(user_id,message,created_at) VALUES(?,?,?)", (message.from_user.id, body, int(time.time())))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Javob berish", callback_data=f"reply:{message.from_user.id}")]])
    info = f"💬 FOYDALANUVCHI XABARI\nIsm: {user['name']}\nTelefon: {user['phone']}\nTelegram ID: {message.from_user.id}\n\n{body}"
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, info, reply_markup=kb)
            if message.photo:
                await bot.send_photo(aid, message.photo[-1].file_id, caption="Foydalanuvchi yuborgan rasm")
            elif message.document:
                await bot.send_document(aid, message.document.file_id)
        except Exception:
            pass
    await message.answer("✅ Xabaringiz operatorga yuborildi.", reply_markup=user_menu(message.from_user.id))
    await state.clear()


@dp.callback_query(F.data.startswith("reply:"))
async def reply_start(call: CallbackQuery, state: FSMContext):
    if not is_operator(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True); return
    await state.update_data(reply_uid=int(call.data.split(":", 1)[1]))
    await call.message.answer("Foydalanuvchiga yuboriladigan javob matnini yoki rasmini yuboring.")
    await state.set_state(Operator.reply)
    await call.answer()


@dp.message(Operator.reply)
async def reply_user(message: Message, state: FSMContext):
    if not is_operator(message.from_user.id):
        await state.clear(); return
    uid = (await state.get_data()).get("reply_uid")
    try:
        if message.photo:
            await bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption or "📩 Operator javobi")
        elif message.document:
            await bot.send_document(uid, message.document.file_id, caption=message.caption or "📩 Operator javobi")
        else:
            await bot.send_message(uid, "📩 Operator javobi:\n\n" + (message.text or ""))
        await message.answer("✅ Javob yuborildi.")
    except Exception as exc:
        await message.answer(f"Xabar yuborilmadi: {exc}")
    await state.clear()


@dp.message(F.text == "⚙️ Operator paneli")
async def panel(message: Message):
    if not is_operator(message.from_user.id):
        return
    await message.answer(f"⚙️ OPERATOR PANELI\nChipta narxi: {get_setting('ticket_price')} so‘m\nKarta: {get_setting('card_number')}\nChipta olish: {'OCHIQ' if get_setting('buying_open') == '1' else 'YOPIQ'}", reply_markup=operator_menu())


@dp.callback_query(F.data.startswith("op:"))
async def op_action(call: CallbackQuery, state: FSMContext):
    if not is_operator(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True); return
    action = call.data.split(":", 1)[1]
    if action == "price":
        await call.message.answer("Yangi chipta narxini so‘mda kiriting:"); await state.set_state(Operator.price)
    elif action == "card":
        await call.message.answer("Karta raqamini/rekvizitini kiriting:"); await state.set_state(Operator.card)
    elif action == "stop":
        set_setting("buying_open", "0")
        round_id = active_round_id()
        report, count = build_round_excel(round_id)
        if report:
            await bot.send_document(
                call.from_user.id,
                report,
                caption=f"⛔ {round_id}-o‘yin: chipta egalari ({count} ta chipta).",
            )
            await call.message.answer("⛔ Chipta olish yopildi. Excel operatorga yuborildi.")
        else:
            await call.message.answer("⛔ Chipta olish yopildi. Bu o‘yinda hali chipta yo‘q.")
    elif action == "open":
        set_setting("buying_open", "1"); await call.message.answer("✅ Chipta olish ochildi.")
    elif action == "broadcast":
        await call.message.answer("Barcha foydalanuvchilarga yuboriladigan matn yoki rasmni yuboring."); await state.set_state(Operator.broadcast)
    elif action == "stats":
        with connect() as c:
            users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            confirmed = c.execute("SELECT COUNT(*) n FROM tickets WHERE round_id=? AND status='confirmed'", (active_round_id(),)).fetchone()["n"]
            pending = c.execute("SELECT COUNT(*) n FROM tickets WHERE round_id=? AND status='pending'", (active_round_id(),)).fetchone()["n"]
        await call.message.answer(f"📊 Foydalanuvchilar: {users}\nTasdiqlangan chiptalar: {confirmed}\nTekshirilayotgan to‘lovlar: {pending}")
    elif action == "clear":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ha, o‘chirish", callback_data="confirm:clear"), InlineKeyboardButton(text="Bekor qilish", callback_data="confirm:cancel")]])
        await call.message.answer("Joriy o‘yin chiptalari o‘chiriladi. Tasdiqlaysizmi?", reply_markup=kb)
    elif action == "newround":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Ha, yangi o‘yin", callback_data="confirm:new"), InlineKeyboardButton(text="Bekor qilish", callback_data="confirm:cancel")]])
        await call.message.answer("Yangi o‘yin boshlash va hammaga xabar yuborishni tasdiqlaysizmi?", reply_markup=kb)
    await call.answer()


@dp.message(Operator.price)
async def price_set(message: Message, state: FSMContext):
    if not is_operator(message.from_user.id): return
    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("Narxni musbat son bilan kiriting."); return
    set_setting("ticket_price", raw)
    await message.answer(f"✅ Chipta narxi {int(raw):,} so‘m qilib saqlandi.".replace(",", " "))
    await state.clear()


@dp.message(Operator.card)
async def card_set(message: Message, state: FSMContext):
    if not is_operator(message.from_user.id): return
    value = (message.text or "").strip()
    if len(value) < 4:
        await message.answer("Karta rekvizitini to‘g‘ri kiriting."); return
    set_setting("card_number", value)
    await message.answer("✅ Karta rekviziti saqlandi. QR-kod kiritilgan rekvizit matnini ko‘rsatadi; bu avtomatik to‘lov emas.")
    await state.clear()


@dp.message(Operator.broadcast)
async def broadcast(message: Message, state: FSMContext):
    if not is_operator(message.from_user.id): return
    text = message.caption or message.text or "📣 Operator xabari"
    photo_id = message.photo[-1].file_id if message.photo else None
    await message.answer("Xabar yuborilmoqda...")
    count = await broadcast_all(text, photo_id)
    await message.answer(f"✅ Xabar {count} ta foydalanuvchiga yuborildi.")
    await state.clear()


@dp.callback_query(F.data.startswith("confirm:"))
async def confirm_action(call: CallbackQuery):
    if not is_operator(call.from_user.id):
        await call.answer("Ruxsat yo‘q.", show_alert=True); return
    action = call.data.split(":", 1)[1]
    if action == "cancel":
        await call.message.answer("Amal bekor qilindi.")
    elif action == "clear":
        with connect() as c:
            c.execute("DELETE FROM tickets WHERE round_id=?", (active_round_id(),))
        await call.message.answer("🧹 Joriy o‘yin chiptalari o‘chirildi.")
    elif action == "new":
        old_round_id = active_round_id()
        report, count = build_round_excel(old_round_id)
        if report:
            await bot.send_document(
                call.from_user.id,
                report,
                caption=f"🆕 {old_round_id}-o‘yin chipta egalari ({count} ta chipta).",
            )
        with connect() as c:
            c.execute("UPDATE rounds SET status='closed' WHERE status='active'")
            c.execute("INSERT INTO rounds(status,created_at) VALUES('active',?)", (int(time.time()),))
        set_setting("buying_open", "1")
        count = await broadcast_all("🎟 Yangi lotereya o‘yini boshlandi! Botga kirib, chipta tanlang.")
        await call.message.answer(f"🆕 Yangi o‘yin boshlandi. {count} foydalanuvchiga xabar yuborildi.")
    await call.answer()


@dp.message(Command("id"))
async def show_id(message: Message):
    await message.answer(f"Telegram ID: {message.from_user.id}")


async def health_check(request: web.Request):
    return web.Response(text="OK - OMADLI BILET bot ishlayapti", status=200)


async def start_web_server():
    # Render Web Service uchun PORT muhit o'zgaruvchisida beriladi.
    port = int(os.getenv("PORT", "10000"))
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    log.info("HTTP health server 0.0.0.0:%s portida ishga tushdi", port)
    return runner


async def main():
    init_db()
    runner = await start_web_server()
    log.info("Lotereya bot ishga tushdi")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
