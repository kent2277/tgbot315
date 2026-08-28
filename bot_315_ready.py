import asyncio
import logging
import json
import os
import sqlite3
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext


TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "group_data.json"
ADMIN_IDS = [1097147969, 1204401699]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

if not TOKEN:
    raise RuntimeError(
        "Не найден BOT_TOKEN. "
        "Задай токен через переменную окружения BOT_TOKEN."
    )

bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================
# КЛАВИАТУРЫ
# =========================

student_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="👉 Завтра")],
        [KeyboardButton(text="📋 Вся неделя"), KeyboardButton(text="⏭ Следующая неделя")],
        [KeyboardButton(text="📚 Полезные материалы")]
    ],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="👉 Завтра")],
        [KeyboardButton(text="📋 Вся неделя"), KeyboardButton(text="⏭ Следующая неделя")],
        [KeyboardButton(text="📚 Полезные материалы")],
        [KeyboardButton(text="💊 Главврач")]
    ],
    resize_keyboard=True
)

admin_schedule_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить расписание")],
        [KeyboardButton(text="🗑 Очистить расписание")],
        [KeyboardButton(text="🔄 Установить текущую неделю")],
        [KeyboardButton(text="📋 Показать расписание")],
        [KeyboardButton(text="⬅️ Назад")]
    ],
    resize_keyboard=True
)

week_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="1️⃣ 1-я неделя")],
        [KeyboardButton(text="2️⃣ 2-я неделя")],
        [KeyboardButton(text="3️⃣ 3-я неделя")],
        [KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True
)

day_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Понедельник"), KeyboardButton(text="Вторник")],
        [KeyboardButton(text="Среда"), KeyboardButton(text="Четверг")],
        [KeyboardButton(text="Пятница"), KeyboardButton(text="Суббота")],
        [KeyboardButton(text="❌ Отмена")]
    ],
    resize_keyboard=True
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Отмена")]],
    resize_keyboard=True
)


# =========================
# СОСТОЯНИЯ АДМИНА
# =========================

class ScheduleStates(StatesGroup):
    choosing_week = State()
    choosing_day = State()
    entering_lessons = State()

class CurrentWeekState(StatesGroup):
    choosing_week = State()

class ClearScheduleState(StatesGroup):
    choosing_week = State()


DAYS = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота"
]


# =========================
# БАЗА ДАННЫХ SQLITE
# =========================

DB_FILE = "bot_315.db"


def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week INTEGER NOT NULL,
            day TEXT NOT NULL,
            lesson TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL
        )
    """)

    cur.execute(
        "INSERT OR IGNORE INTO settings(key, value) VALUES('current_week', '1')"
    )

    conn.commit()
    conn.close()


def save_data(data=None):
    """
    Оставлено для совместимости со старой логикой.
    Основные данные теперь сохраняются непосредственно в SQLite.
    """
    return


def load_data():
    """
    Возвращает данные в привычном для бота формате,
    но источником является SQLite.
    """
    init_db()
    conn = get_db()
    cur = conn.cursor()

    current_week_row = cur.execute(
        "SELECT value FROM settings WHERE key='current_week'"
    ).fetchone()
    current_week = int(current_week_row["value"]) if current_week_row else 1

    schedule = default_schedule()

    rows = cur.execute(
        "SELECT week, day, lesson FROM schedule ORDER BY id"
    ).fetchall()

    for row in rows:
        schedule[str(row["week"])][row["day"]].append(row["lesson"])

    users = [
        row["user_id"]
        for row in cur.execute("SELECT user_id FROM users").fetchall()
    ]

    materials = [
        {"title": row["title"], "url": row["url"]}
        for row in cur.execute(
            "SELECT title, url FROM materials ORDER BY id"
        ).fetchall()
    ]

    conn.close()

    return {
        "schedule": schedule,
        "current_week": current_week,
        "materials": materials,
        "users": users
    }


def register_user(user_id):
    init_db()
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES(?)",
        (user_id,)
    )
    conn.commit()
    conn.close()


def get_current_week():
    init_db()
    conn = get_db()

    row = conn.execute(
        "SELECT value FROM settings WHERE key='current_week'"
    ).fetchone()

    conn.close()

    try:
        week = int(row["value"])
    except (TypeError, ValueError):
        week = 1

    return week if week in (1, 2, 3) else 1


def set_current_week(week):
    init_db()
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES('current_week', ?)",
        (str(week),)
    )
    conn.commit()
    conn.close()


def add_lessons(week, day, lessons):
    if not lessons:
        return

    init_db()
    conn = get_db()

    conn.executemany(
        "INSERT INTO schedule(week, day, lesson) VALUES(?, ?, ?)",
        [(week, day, lesson) for lesson in lessons]
    )

    conn.commit()
    conn.close()


def clear_week(week):
    init_db()
    conn = get_db()
    conn.execute("DELETE FROM schedule WHERE week=?", (week,))
    conn.commit()
    conn.close()


def get_lessons(week, day):
    init_db()
    conn = get_db()

    rows = conn.execute(
        "SELECT lesson FROM schedule WHERE week=? AND day=? ORDER BY id",
        (week, day)
    ).fetchall()

    conn.close()

    return [row["lesson"] for row in rows]


def add_material_db(title, url):
    init_db()
    conn = get_db()
    conn.execute(
        "INSERT INTO materials(title, url) VALUES(?, ?)",
        (title, url)
    )
    conn.commit()
    conn.close()


def delete_material_db(index):
    init_db()
    conn = get_db()

    rows = conn.execute(
        "SELECT id, title FROM materials ORDER BY id"
    ).fetchall()

    if not (0 <= index < len(rows)):
        conn.close()
        return None

    material_id = rows[index]["id"]
    title = rows[index]["title"]

    conn.execute(
        "DELETE FROM materials WHERE id=?",
        (material_id,)
    )

    conn.commit()
    conn.close()

    return title


# =========================
# ОБЩИЕ ФУНКЦИИ
# =========================

def get_kb_for_user(user_id: int):
    return admin_keyboard if user_id in ADMIN_IDS else student_keyboard


def week_from_button(text):
    if text.startswith("1️⃣"):
        return 1
    if text.startswith("2️⃣"):
        return 2
    if text.startswith("3️⃣"):
        return 3
    return None


def format_day_schedule(lessons):
    if not lessons:
        return "<b>Пар нет</b>"

    result = []
    for number, lesson in enumerate(lessons, 1):
        result.append(f"<b>{number}.</b> {escape(str(lesson))}")

    return "\n".join(result)


# =========================
# START / HELP
# =========================

@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    register_user(user_id)

    week_num = get_current_week()
    kb = get_kb_for_user(user_id)

    await message.answer(
        "💪 <b>Бот 315 группы на связи, доктора!</b>\n\n"
        f"📌 Администратор установил текущей <b>{week_num}-ю неделю</b>.\n\n"
        "Выбирай нужный вариант ниже:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    help_text = (
        "🤖 <b>Справка по боту 315 группы:</b>\n\n"
        "📅 <b>Сегодня</b> — расписание на текущий день.\n"
        "👉 <b>Завтра</b> — расписание на следующий день.\n"
        "📋 <b>Вся неделя</b> — расписание установленной администратором недели.\n"
        "⏭ <b>Следующая неделя</b> — следующая неделя цикла.\n"
        "📚 <b>Полезные материалы</b> — ссылки и тренинги группы.\n\n"
        "💊 <b>Администратор</b> заполняет расписание вручную."
    )
    await message.answer(help_text, parse_mode="HTML")


# =========================
# КАБИНЕТ ГЛАВВРАЧА
# =========================

@dp.message(F.text == "💊 Главврач")
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Доступ запрещен. Вы не Главврач отделения.")
        return

    week_num = get_current_week()

    text = (
        "💊 <b>КАБИНЕТ ГЛАВВРАЧА</b> 💊\n\n"
        f"📌 Текущая неделя: <b>{week_num}-я</b>\n\n"
        "Здесь можно вручную заполнить расписание, "
        "установить активную неделю и управлять материалами."
    )

    await message.answer(
        text,
        reply_markup=admin_schedule_keyboard,
        parse_mode="HTML"
    )


@dp.message(F.text == "⬅️ Назад")
async def admin_back(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await message.answer(
        "Главное меню.",
        reply_markup=admin_keyboard
    )


# =========================
# РУЧНОЕ РАСПИСАНИЕ
# =========================

@dp.message(F.text == "➕ Добавить расписание")
async def add_schedule_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.set_state(ScheduleStates.choosing_week)

    await message.answer(
        "➕ <b>Добавление расписания</b>\n\n"
        "Выбери, для какой недели добавляем пары:",
        reply_markup=week_keyboard,
        parse_mode="HTML"
    )


@dp.message(ScheduleStates.choosing_week)
async def add_schedule_week(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление отменено.", reply_markup=admin_schedule_keyboard)
        return

    week = week_from_button(message.text)

    if week is None:
        await message.answer("⚠️ Выбери 1, 2 или 3 неделю кнопкой ниже.")
        return

    await state.update_data(week=week)
    await state.set_state(ScheduleStates.choosing_day)

    await message.answer(
        f"✅ Выбрана <b>{week}-я неделя</b>.\n\n"
        "Теперь выбери день:",
        reply_markup=day_keyboard,
        parse_mode="HTML"
    )


@dp.message(ScheduleStates.choosing_day)
async def add_schedule_day(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление отменено.", reply_markup=admin_schedule_keyboard)
        return

    day = message.text.strip().lower()

    if day not in DAYS:
        await message.answer("⚠️ Выбери день кнопкой ниже.")
        return

    await state.update_data(day=day)
    await state.set_state(ScheduleStates.entering_lessons)

    await message.answer(
        f"📅 <b>{day.capitalize()}</b>\n\n"
        "Отправь пары одним сообщением — по одной паре на строку.\n\n"
        "<b>Пример:</b>\n"
        "<code>8:40-10:20 Анатомия\n"
        "10:30-12:10 Физиология\n"
        "12:20-14:00 Хирургия</code>\n\n"
        "Если пар нет — напиши <code>нет</code>.",
        reply_markup=cancel_keyboard,
        parse_mode="HTML"
    )


@dp.message(ScheduleStates.entering_lessons)
async def add_schedule_lessons(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление отменено.", reply_markup=admin_schedule_keyboard)
        return

    data_state = await state.get_data()
    week = data_state["week"]
    day = data_state["day"]

    raw_text = message.text.strip()

    if raw_text.lower() in ("нет", "нет пар", "-"):
        lessons = []
    else:
        lessons = [
            line.strip()
            for line in raw_text.splitlines()
            if line.strip()
        ]

    add_lessons(week, day, lessons)

    await state.clear()

    if lessons:
        preview = format_day_schedule(lessons)
        answer = (
            f"✅ Расписание добавлено!\n\n"
            f"📌 <b>{week}-я неделя</b>\n"
            f"📅 <b>{day.capitalize()}</b>\n\n"
            f"{preview}"
        )
    else:
        answer = (
            f"✅ Для {day.capitalize()} на {week}-й неделе "
            "указано, что пар нет."
        )

    await message.answer(
        answer,
        reply_markup=admin_schedule_keyboard,
        parse_mode="HTML"
    )


# =========================
# УСТАНОВКА ТЕКУЩЕЙ НЕДЕЛИ
# =========================

@dp.message(F.text == "🔄 Установить текущую неделю")
async def set_current_week_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.set_state(CurrentWeekState.choosing_week)

    await message.answer(
        "🔄 <b>Установка текущей недели</b>\n\n"
        "Выбери неделю, которая сейчас идет:",
        reply_markup=week_keyboard,
        parse_mode="HTML"
    )


@dp.message(CurrentWeekState.choosing_week)
async def set_current_week_finish(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отмена.", reply_markup=admin_schedule_keyboard)
        return

    week = week_from_button(message.text)

    if week is None:
        await message.answer("⚠️ Выбери 1, 2 или 3 неделю.")
        return

    set_current_week(week)

    await state.clear()

    await message.answer(
        f"✅ Текущей установлена <b>{week}-я неделя</b>.\n\n"
        "Теперь студенты будут видеть именно это расписание "
        "при нажатии «Сегодня», «Завтра» и «Вся неделя».",
        reply_markup=admin_schedule_keyboard,
        parse_mode="HTML"
    )


# =========================
# ОЧИСТКА РАСПИСАНИЯ
# =========================

@dp.message(F.text == "🗑 Очистить расписание")
async def clear_schedule_start(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.set_state(ClearScheduleState.choosing_week)

    await message.answer(
        "🗑 <b>Очистка расписания</b>\n\n"
        "Выбери неделю, которую нужно полностью очистить:",
        reply_markup=week_keyboard,
        parse_mode="HTML"
    )


@dp.message(ClearScheduleState.choosing_week)
async def clear_schedule_finish(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Отмена.", reply_markup=admin_schedule_keyboard)
        return

    week = week_from_button(message.text)

    if week is None:
        await message.answer("⚠️ Выбери 1, 2 или 3 неделю.")
        return

    clear_week(week)

    await state.clear()

    await message.answer(
        f"🗑 Расписание <b>{week}-й недели</b> полностью очищено.",
        reply_markup=admin_schedule_keyboard,
        parse_mode="HTML"
    )


# =========================
# ПРОСМОТР РАСПИСАНИЯ АДМИНОМ
# =========================

@dp.message(F.text == "📋 Показать расписание")
async def admin_show_schedule(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = load_data()

    parts = ["📋 <b>Все сохраненные пары</b>\n"]

    for week in (1, 2, 3):
        parts.append(f"\n🔄 <b>{week}-я неделя</b>")

        for day in DAYS:
            lessons = data["schedule"][str(week)].get(day, [])
            parts.append(f"\n📅 <b>{day.capitalize()}</b>")
            parts.append(format_day_schedule(lessons))

    text = "\n".join(parts)

    # Telegram ограничивает сообщение примерно 4096 символами.
    if len(text) <= 4000:
        await message.answer(text, parse_mode="HTML")
    else:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i + 4000], parse_mode="HTML")


# =========================
# СТУДЕНЧЕСКОЕ РАСПИСАНИЕ
# =========================

def get_day_name(index):
    return DAYS[index] if 0 <= index < len(DAYS) else None


@dp.message(F.text.startswith("📅 Сегодня"))
async def today_schedule(message: Message):
    from datetime import datetime

    now = datetime.now()
    day_name = get_day_name(now.weekday())

    if day_name is None:
        await message.answer("📚 Воскресенье — пар нет.")
        return

    week_num = get_current_week()
    lessons = get_lessons(week_num, day_name)

    response = (
        f"📅 <b>Сегодня</b> — {day_name.capitalize()}\n"
        f"🔄 Текущая неделя: <b>{week_num}-я</b>\n\n"
        f"{format_day_schedule(lessons)}"
    )

    await message.answer(response, parse_mode="HTML")


@dp.message(F.text.startswith("👉 Завтра"))
async def tomorrow_schedule(message: Message):
    from datetime import datetime, timedelta

    tomorrow = datetime.now() + timedelta(days=1)
    day_name = get_day_name(tomorrow.weekday())

    if day_name is None:
        await message.answer("📚 Воскресенье — пар нет.")
        return

    week_num = get_current_week()

    # В субботу «завтра» уже воскресенье — пар нет.
    lessons = get_lessons(week_num, day_name)

    response = (
        f"👉 <b>Завтра</b> — {day_name.capitalize()}\n"
        f"🔄 Текущая неделя: <b>{week_num}-я</b>\n\n"
        f"{format_day_schedule(lessons)}"
    )

    await message.answer(response, parse_mode="HTML")


@dp.message(F.text.startswith("📋 Вся неделя"))
async def full_week_schedule(message: Message):
    week_num = get_current_week()

    full_text = (
        "📋 <b>Расписание на текущую неделю</b>\n"
        f"🔄 Текущая неделя: <b>{week_num}-я</b>\n\n"
    )

    for day in DAYS:
        lessons = get_lessons(week_num, day)

        full_text += (
            f"🔹 <b>{day.capitalize()}</b>\n"
            f"{format_day_schedule(lessons)}\n\n"
        )

    await message.answer(full_text, parse_mode="HTML")


@dp.message(F.text.startswith("⏭ Следующая неделя"))
async def next_week_schedule(message: Message):
    current_week = get_current_week()
    next_week = (current_week % 3) + 1

    full_text = (
        "⏭ <b>Расписание на следующую неделю</b>\n"
        f"🔄 Следующая неделя цикла: <b>{next_week}-я</b>\n\n"
    )

    for day in DAYS:
        lessons = get_lessons(next_week, day)

        full_text += (
            f"🔹 <b>{day.capitalize()}</b>\n"
            f"{format_day_schedule(lessons)}\n\n"
        )

    await message.answer(full_text, parse_mode="HTML")


# =========================
# МАТЕРИАЛЫ
# =========================

@dp.message(F.text == "📚 Полезные материалы")
async def show_materials(message: Message):
    data = load_data()
    materials = data.get("materials", [])

    if not materials:
        await message.answer("📂 Пока сюда ничего не добавили.")
        return

    text = "📚 <b>Полезные материалы и тренинги для 315 группы:</b>\n\n"

    for i, item in enumerate(materials, 1):
        text += f"{i}. <a href='{escape(item['url'])}'>{escape(item['title'])}</a>\n"

    await message.answer(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True
    )


@dp.message(Command("addmat"))
async def add_material(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2 or "|" not in parts[1]:
        await message.answer(
            "⚠️ Формат: <code>/addmat Название | https://ссылка.com</code>",
            parse_mode="HTML"
        )
        return

    title, url = map(str.strip, parts[1].split("|", 1))

    add_material_db(title, url)

    await message.answer(
        f"✅ Материал «{escape(title)}» успешно добавлен в базу!",
        parse_mode="HTML"
    )


@dp.message(Command("delmat"))
async def delete_material(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split()

    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(
            "⚠️ Укажи номер материала. Пример: <code>/delmat 1</code>",
            parse_mode="HTML"
        )
        return

    index = int(parts[1]) - 1
    removed_title = delete_material_db(index)

    if removed_title is not None:
        await message.answer(
            f"🗑 Материал «{escape(removed_title)}» успешно удален!",
            parse_mode="HTML"
        )
    else:
        await message.answer("❌ Материал с таким номером не найден.")


# =========================
# РАССЫЛКА
# =========================

@dp.message(Command("broadcast"))
async def broadcast_message(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "⚠️ Напиши текст для рассылки.\n"
            "Пример: <code>/broadcast Всем привет!</code>",
            parse_mode="HTML"
        )
        return

    text_to_send = (
        "🚨 <b>ЭКСТРЕННОЕ ОПОВЕЩЕНИЕ ОТ ГЛАВВРАЧА:</b>\n\n"
        f"{escape(parts[1])}"
    )

    data = load_data()
    success, fail = 0, 0

    for uid in data.get("users", []):
        try:
            await bot.send_message(
                uid,
                text_to_send,
                parse_mode="HTML"
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    await message.answer(
        f"📢 Рассылка завершена!\n"
        f"✅ Доставлено: {success}\n"
        f"❌ Ошибок: {fail}"
    )


# =========================
# СТАТИСТИКА
# =========================

@dp.message(Command("stats"))
async def show_stats(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = load_data()

    await message.answer(
        f"📊 <b>Статистика отделения 315:</b>\n\n"
        f"👥 Студентов в боте: <code>{len(data.get('users', []))}</code>\n"
        f"📁 Сохранено материалов: <code>{len(data.get('materials', []))}</code>\n"
        f"🔄 Текущая неделя: <code>{get_current_week()}</code>",
        parse_mode="HTML"
    )


# =========================
# ЗАПУСК
# =========================

async def main():
    init_db()
    print("Бот Главврача запущен. Расписание хранится в SQLite.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
