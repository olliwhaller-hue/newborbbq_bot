import os
import sqlite3
import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from pathlib import Path

# ЗАГРУЗКА .env
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_TG_ID = int(os.getenv("ADMIN_TG_ID", 0))

# Настройки
DB_NAME = "/tmp/bbq.db"
SLOTS = ["10-12", "12-14", "14-16", "16-18", "18-20", "20-22"]

# Предустановленные данные о домах
HOUSES = {
    "Небесная 16": {
        "подъезды": ["1", "2", "3", "4", "5"],
        "квартиры": {
            "1": [f"{i}" for i in range(1, 21)],
            "2": [f"{i}" for i in range(21, 41)],
            "3": [f"{i}" for i in range(41, 61)],
            "4": [f"{i}" for i in range(61, 81)],
            "5": [f"{i}" for i in range(81, 101)],
        }
    },
    "Миля 3": {
        "подъезды": ["1", "2", "3", "4", "5"],
        "квартиры": {
            "1": [f"{i}" for i in range(1, 55)],
            "2": [f"{i}" for i in range(56, 90)],
            "3": [f"{i}" for i in range(91, 125)],
            "4": [f"{i}" for i in range(126, 166)],
            "5": [f"{i}" for i in range(167, 197)],
        }
    }
}

# --- База данных ---
def init_db():
    """Создать таблицу, если её нет"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            date TEXT, slot TEXT, user_id INTEGER, username TEXT,
            house TEXT, entrance TEXT, flat TEXT, booked_at TEXT,
            PRIMARY KEY (date, slot)
        )
    """)
    conn.commit()
    conn.close()

def get_bookings(date_str: str):
    """Получить слоты за дату"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT slot, username FROM bookings WHERE date = ?", (date_str,))
    result = dict(c.fetchall())
    conn.close()
    return result

def book_slot(date_str: str, slot: str, user_id: int, username: str, house: str, entrance: str, flat: str) -> bool:
    """Забронировать слот"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO bookings (date, slot, user_id, username, house, entrance, flat, booked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (date_str, slot, user_id, username, house, entrance, flat, datetime.datetime.now().isoformat()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def cancel_slot(date_str: str, slot: str, user_id: int):
    """Отменить свою бронь"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM bookings WHERE date = ? AND slot = ? AND user_id = ?", (date_str, slot, user_id))
    conn.commit()
    conn.close()

def get_user_bookings(user_id: int):
    """Получить все брони пользователя"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT date, slot, house, entrance, flat FROM bookings WHERE user_id = ? ORDER BY date, slot", (user_id,))
    result = c.fetchall()
    conn.close()
    return result

# --- Календарь ---
def calendar_markup(year: int, month: int):
    """Создать inline-клавиатуру-календарь"""
    keyboard = []
    keyboard.append([
        InlineKeyboardButton("⬅️", callback_data=f"nav_{year}_{month}_prev"),
        InlineKeyboardButton(f"{month:02}/{year}", callback_data="ignore"),
        InlineKeyboardButton("➡️", callback_data=f"nav_{year}_{month}_next")
    ])
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(d, callback_data="ignore") for d in days])
    
    first_day = datetime.date(year, month, 1)
    if month == 12:
        next_month = datetime.date(year + 1, 1, 1)
    else:
        next_month = datetime.date(year, month + 1, 1)
    last_day = next_month - datetime.timedelta(days=1)
    
    row = []
    for _ in range(first_day.weekday()):
        row.append(InlineKeyboardButton(" ", callback_data="ignore"))
    
    for day in range(1, last_day.day + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        
        # Определяем, доступна ли дата для выбора
        today = datetime.date.today()
        current_date = datetime.date(year, month, day)
        is_available = current_date >= today
        
        # Показываем индикаторы для всех дат
        bookings = get_bookings(date_str)
        taken = len(bookings)
        emoji = "◼" if taken == len(SLOTS) else "◻" if taken > 0 else ""
        
        # Если дата недоступна (прошлая), делаем кнопку неактивной
        if not is_available:
            row.append(InlineKeyboardButton(" ", callback_data="ignore"))
        else:
            row.append(InlineKeyboardButton(f"{emoji} {day}", callback_data=f"date_{date_str}"))
        
        if len(row) == 7:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)

# --- Клавиатура ---
def get_main_keyboard():
    """Главная ReplyKeyboard"""
    keyboard = [
        ["📅 Календарь", "📋 Мои брони"],
        ["❌ Отменить бронь"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- Обработчики ---
async def start_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /start с клавиатурой"""
    welcome = (
        "🔥 Бот для бронирования BBQ\n\n"
        "• Нажмите «📅 Календарь» чтобы выбрать дату\n"
        "• Нажмите «📋 Мои брони» чтобы посмотреть свои записи\n"
        "• Нажмите «❌ Отменить мою бронь» чтобы отменить запись"
    )
    await update.message.reply_text(welcome, reply_markup=get_main_keyboard())

async def bbq_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Команда /bbq – показать календарь"""
    now = datetime.datetime.now()
    await update.message.reply_text("📅 Выберите дату:", reply_markup=calendar_markup(now.year, now.month))

async def my_bookings_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать мои активные брони"""
    user_id = update.message.from_user.id
    bookings = get_user_bookings(user_id)
    
    if not bookings:
        await update.message.reply_text("❌ У вас нет активных бронирований.")
        return
    
    text = "📋 Ваши брони:\n" + "\n".join([f"• {d} {s}\n  🏠 {h}, п.{e}, кв.{f}" for d, s, h, e, f in bookings])
    await update.message.reply_text(text)

async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Показать мои брони для отмены"""
    user_id = update.message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT date, slot, house, entrance, flat FROM bookings WHERE user_id = ? ORDER BY date, slot", (user_id,))
    bookings = c.fetchall()
    conn.close()
    
    if not bookings:
        await update.message.reply_text("❌ У вас нет активных бронирований.")
        return
    
    keyboard = [[InlineKeyboardButton(f"{d} {s}", callback_data=f"del_{d}_{s}")] for d, s, h, e, f in bookings]
    await update.message.reply_text("Выберите слот для отмены:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Обработка всех нажатий на inline-кнопки"""
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "ignore":
        return
    
    if data.startswith("nav_"):
        _, year, month, direction = data.split("_")
        year, month = int(year), int(month)
        if direction == "prev":
            month -= 1
            if month < 1:
                month, year = 12, year - 1
        else:
            month += 1
            if month > 12:
                month, year = 1, year + 1
        await query.edit_message_reply_markup(reply_markup=calendar_markup(year, month))
        return
    
    if data == "back":
        now = datetime.datetime.now()
        await query.edit_message_reply_markup(reply_markup=calendar_markup(now.year, now.month))
        return
    
    if data.startswith("date_"):
        date_str = data.split("_", 1)[1]
        bookings = get_bookings(date_str)
        keyboard = []
        for slot in SLOTS:
            if slot in bookings:
                keyboard.append([InlineKeyboardButton(f"❌ {slot} (занято)", callback_data="ignore")])
            else:
                keyboard.append([InlineKeyboardButton(f"✅ {slot}", callback_data=f"slot_{date_str}_{slot}")])
        # КНОПКА "НАЗАД"  ПОСЛЕ ВСЕХ СЛОТОВ
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back")])
        await query.edit_message_text(f"📅 {date_str} – выберите слот:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if data.startswith("slot_"):
        _, date_str, slot = data.split("_", 2)
        ctx.user_data['booking'] = {'date': date_str, 'slot': slot}
        
        keyboard = [[InlineKeyboardButton(house, callback_data=f"house_{date_str}_{slot}_{house}")] for house in HOUSES.keys()]
        await query.edit_message_text(f"📅 {date_str} {slot}\n\n🏠 С какого Вы Выберит дома?", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if data.startswith("house_"):
        _, date_str, slot, house = data.split("_", 3)
        ctx.user_data['booking'].update({'house': house})
        
        keyboard = [[InlineKeyboardButton(f"Подъезд {e}", callback_data=f"entrance_{date_str}_{slot}_{house}_{e}")] for e in HOUSES[house]["подъезды"]]
        await query.edit_message_text(f"📅 {date_str} {slot}\n🏠 {house}\n\n🚪 Напомните подъезд:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if data.startswith("entrance_"):
        _, date_str, slot, house, entrance = data.split("_", 4)
        ctx.user_data['booking'].update({'entrance': entrance})
        
        flats = HOUSES[house]["квартиры"][entrance]
        keyboard = []
        row = []
        for flat in flats:
            row.append(InlineKeyboardButton(f"Кв.{flat}", callback_data=f"flat_{date_str}_{slot}_{house}_{entrance}_{flat}"))
            if len(row) == 5:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        await query.edit_message_text(f"📅 {date_str} {slot}\n🏠 {house}, подъезд {entrance}\n\n🏢 Выберите свою квартиру:", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    if data.startswith("flat_"):
        _, date_str, slot, house, entrance, flat = data.split("_", 5)
        user = query.from_user
        
        if book_slot(date_str, slot, user.id, user.username or "Без_ника", house, entrance, flat):
            await query.edit_message_text(f"✅ Забронировано:\n📅 {date_str} {slot}\n🏠 {house}, подъезд {entrance}, кв. {flat}")
            
            if query.message.chat.type != "private":
                await ctx.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"🔥 @{user.username} забронировал BBQ на {date_str} {slot}\n🏠 {house}"
                )
        else:
            await query.edit_message_text("❌ Слот уже занят!")
        
        ctx.user_data.clear()
        return

# Обработка текста (кнопки ReplyKeyboard)
async def text_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ловим нажатия на кнопки ReplyKeyboard"""
    text = update.message.text
    if text == "📅 Календарь":
        await bbq_cmd(update, ctx)
    elif text == "📋 Мои брони":
        await my_bookings_cmd(update, ctx)
    elif text == "❌ Отменить бронь":
        await cancel_cmd(update, ctx)

async def del_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, date_str, slot = query.data.split("_", 2)
    cancel_slot(date_str, slot, query.from_user.id)
    await query.edit_message_text(f"✅ Отменено: {date_str} {slot}")
    if query.message.chat.type != "private":
        await ctx.bot.send_message(query.message.chat_id, f"📅 Освободился слот: {date_str} {slot}")

# --- Старт ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("bbq", bbq_cmd))
    app.add_handler(CommandHandler("my_bookings", my_bookings_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(CallbackQueryHandler(del_callback, pattern="^del_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_msg))
    
    print("✅ Бот запущен. Нажми Ctrl+C для остановки.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()