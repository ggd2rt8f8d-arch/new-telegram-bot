import asyncio
import os
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove)
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.enums import ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@topzfilmz")

super_admins_str = os.getenv("SUPER_ADMIN_IDS", "")
SUPER_ADMIN_IDS = [int(uid.strip()) for uid in super_admins_str.split(",") if uid.strip().isdigit()]

DB_NAME = "movies.db"
# ===================================================

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не задан в переменных окружения!")
# ===================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# -------------------- FSM --------------------
class AddMovie(StatesGroup):
    code = State()
    title = State()
    year = State()
    poster = State()
    description = State()
    rating = State()


class EditMovie(StatesGroup):
    waiting_value = State()


class BanUser(StatesGroup):
    waiting_id = State()


class AddAdmin(StatesGroup):
    waiting_id = State()


# -------------------- База данных --------------------
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS movies (
                code TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                year INTEGER,
                poster TEXT,
                description TEXT,
                rating TEXT
            )
        """)
        await db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS bans (user_id INTEGER PRIMARY KEY, reason TEXT DEFAULT '')")
        await db.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0)")
        await db.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('total_requests', 0)")
        await db.commit()


async def get_movie(code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM movies WHERE code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "code": row[0], "title": row[1], "year": row[2],
                    "poster": row[3], "description": row[4], "rating": row[5]
                }
            return None


async def get_all_movies():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT code, title, year FROM movies ORDER BY code") as cursor:
            return await cursor.fetchall()


async def get_movies_count():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT COUNT(*) FROM movies") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def add_movie_to_db(code, title, year, poster, description, rating):
    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO movies (code, title, year, poster, description, rating) VALUES (?, ?, ?, ?, ?, ?)",
                (code, title, year, poster, description, rating)
            )
            await db.commit()
            logging.info(f"Фильм добавлен: {code}")
        except aiosqlite.IntegrityError:
            logging.warning(f"Код уже существует: {code}")
            raise


async def update_movie_field(code: str, field: str, value):
    allowed = {"title", "year", "poster", "description", "rating"}
    if field not in allowed:
        return
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"UPDATE movies SET {field} = ? WHERE code = ?", (value, code))
        await db.commit()


async def delete_movie(code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM movies WHERE code = ?", (code,))
        await db.commit()


async def is_admin(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None


async def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS


async def add_admin(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
        await db.commit()


async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_admins():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id FROM admins") as cursor:
            return [r[0] for r in await cursor.fetchall()]


async def ban_user(user_id: int, reason: str = ""):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR REPLACE INTO bans (user_id, reason) VALUES (?, ?)", (user_id, reason))
        await db.commit()


async def unban_user(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
        await db.commit()


async def is_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT 1 FROM bans WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone() is not None


async def get_banned_users():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, reason FROM bans") as cursor:
            return await cursor.fetchall()


async def increment_requests():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE stats SET value = value + 1 WHERE key = 'total_requests'")
        await db.commit()


async def get_total_requests():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT value FROM stats WHERE key = 'total_requests'") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# -------------------- Клавиатуры --------------------
def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
    ])


def admin_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔧 Админ-панель")]],
        resize_keyboard=True
    )


def admin_main_kb(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="📋 Список фильмов", callback_data="admin_list")],
        [InlineKeyboardButton(text="➕ Добавить фильм", callback_data="admin_add")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
    ]
    if is_super_admin(user_id):
        buttons.append([InlineKeyboardButton(text="👥 Управление админами", callback_data="admin_admins")])
        buttons.append([InlineKeyboardButton(text="🚫 Баны", callback_data="admin_bans")])
    buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def movie_actions_kb(code: str, user_id: int):
    buttons = [
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"edit_title:{code}")],
        [InlineKeyboardButton(text="📅 Год", callback_data=f"edit_year:{code}")],
        [InlineKeyboardButton(text="🖼 Обложка", callback_data=f"edit_poster:{code}")],
        [InlineKeyboardButton(text="📝 Описание", callback_data=f"edit_description:{code}")],
        [InlineKeyboardButton(text="⭐ Рейтинг", callback_data=f"edit_rating:{code}")],
    ]
    if is_super_admin(user_id):
        buttons.append([InlineKeyboardButton(text="🗑 Удалить фильм", callback_data=f"delete_movie:{code}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def check_sub(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False


# ==================== ХЭНДЛЕРЫ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    if await is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы в боте.")

    is_user_admin = await is_admin(message.from_user.id)

    if await check_sub(message.from_user.id):
        text = "Привет! 👋\nВведи код фильма:"
        if is_user_admin:
            await message.answer(text, reply_markup=admin_reply_kb())
        else:
            await message.answer(text, reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("Подпишись на канал, чтобы пользоваться ботом:", reply_markup=subscribe_kb())


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery):
    if await check_sub(callback.from_user.id):
        is_user_admin = await is_admin(callback.from_user.id)
        text = "✅ Подписка подтверждена!\nВведи код фильма:"
        if is_user_admin:
            await callback.message.answer(text, reply_markup=admin_reply_kb())
        else:
            await callback.message.answer(text)
        await callback.message.delete()
    else:
        await callback.answer("Ты ещё не подписан!", show_alert=True)


@dp.message(F.text == "🔧 Админ-панель")
@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    await state.clear()
    if not await is_admin(message.from_user.id):
        return await message.answer("⛔ Нет доступа")

    await message.answer("🔧 <b>Админ-панель</b>", parse_mode="HTML",
                         reply_markup=admin_main_kb(message.from_user.id))


@dp.callback_query(F.data == "admin_close")
async def cb_close(callback: CallbackQuery):
    await callback.message.delete()


@dp.callback_query(F.data == "admin_back")
async def cb_back(callback: CallbackQuery):
    await callback.message.edit_text("🔧 <b>Админ-панель</b>", parse_mode="HTML",
                                     reply_markup=admin_main_kb(callback.from_user.id))


@dp.callback_query(F.data == "admin_stats")
async def cb_stats(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    movies_count = await get_movies_count()
    requests_count = await get_total_requests()

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"🎬 Фильмов в базе: <b>{movies_count}</b>\n"
        f"🔍 Всего запросов: <b>{requests_count}</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ]))


@dp.callback_query(F.data == "admin_list")
async def cb_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    movies = await get_all_movies()

    if not movies:
        await callback.message.edit_text(
            "База пустая.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
            ])
        )
        return

    buttons = []
    for code, title, year in movies:
        buttons.append([InlineKeyboardButton(
            text=f"{code} — {title} ({year})",
            callback_data=f"movie:{code}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])

    await callback.message.edit_text(
        "📋 <b>Список фильмов:</b>\nВыбери фильм:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("movie:"))
async def cb_movie(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    movie = await get_movie(code)

    if not movie:
        await callback.answer("Фильм не найден", show_alert=True)
        return

    text = (
        f"<b>{movie['title']} ({movie['year']})</b>\n"
        f"Код: <code>{movie['code']}</code>\n"
        f"IMDb: {movie['rating']}\n\n"
        f"{movie['description'][:180]}..."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=movie_actions_kb(code, callback.from_user.id)
    )


@dp.callback_query(F.data.startswith("delete_movie:"))
async def cb_delete_movie(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Недостаточно прав", show_alert=True)

    code = callback.data.split(":", 1)[1]
    await delete_movie(code)
    await callback.answer("Фильм удалён ✅")
    await cb_list(callback)


# ---------- Редактирование ----------
@dp.callback_query(F.data.startswith("edit_"))
async def cb_edit_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return

    parts = callback.data.split(":", 1)
    field = parts[0].replace("edit_", "")
    code = parts[1]

    await state.update_data(edit_code=code, edit_field=field)

    if field == "poster":
        await callback.message.edit_text(
            "Отправь <b>новую обложку</b>:\n• Фотографию\n• Или прямую ссылку",
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(f"Введи новое значение для <b>{field}</b>:", parse_mode="HTML")

    await state.set_state(EditMovie.waiting_value)


@dp.message(EditMovie.waiting_value)
async def process_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["edit_code"]
    field = data["edit_field"]

    if field == "poster":
        if message.photo:
            value = message.photo[-1].file_id
        elif message.text:
            value = message.text.strip()
        else:
            return await message.answer("Отправь фото или ссылку:")
    else:
        if not message.text:
            return await message.answer("Отправь текстом:")
        value = message.text.strip()
        if field == "year":
            if not value.isdigit():
                return await message.answer("Год должен быть числом:")
            value = int(value)

    await update_movie_field(code, field, value)
    await state.clear()
    await message.answer("✅ Обновлено!")

    movie = await get_movie(code)
    if movie:
        text = (
            f"<b>{movie['title']} ({movie['year']})</b>\n"
            f"Код: <code>{movie['code']}</code>\n"
            f"IMDb: {movie['rating']}"
        )
        await message.answer(text, parse_mode="HTML",
                             reply_markup=movie_actions_kb(code, message.from_user.id))


# ---------- Добавление фильма ----------
@dp.callback_query(F.data == "admin_add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("Введи <b>код</b> фильма:", parse_mode="HTML")
    await state.set_state(AddMovie.code)


@dp.message(AddMovie.code)
async def add_code(message: Message, state: FSMContext):
    code = message.text.strip()
    if await get_movie(code):
        return await message.answer("Такой код уже есть. Введи другой:")
    await state.update_data(code=code)
    await message.answer("Введи <b>название</b>:", parse_mode="HTML")
    await state.set_state(AddMovie.title)


@dp.message(AddMovie.title)
async def add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Введи <b>год</b>:", parse_mode="HTML")
    await state.set_state(AddMovie.year)


@dp.message(AddMovie.year)
async def add_year(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("Год должен быть числом:")
    await state.update_data(year=int(message.text.strip()))
    await message.answer(
        "Отправь <b>обложку</b>:\n• Фотографию\n• Или прямую ссылку",
        parse_mode="HTML"
    )
    await state.set_state(AddMovie.poster)


@dp.message(AddMovie.poster)
async def add_poster(message: Message, state: FSMContext):
    if message.photo:
        poster = message.photo[-1].file_id
    elif message.text:
        poster = message.text.strip()
    else:
        return await message.answer("Отправь фото или ссылку:")

    await state.update_data(poster=poster)
    await message.answer("Краткое <b>описание</b>:", parse_mode="HTML")
    await state.set_state(AddMovie.description)


@dp.message(AddMovie.description)
async def add_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("Оценка <b>IMDb</b>:", parse_mode="HTML")
    await state.set_state(AddMovie.rating)


@dp.message(AddMovie.rating)
async def add_rating(message: Message, state: FSMContext):
    data = await state.get_data()
    try:
        await add_movie_to_db(
            data["code"], data["title"], data["year"],
            data["poster"], data["description"], message.text.strip()
        )
        await state.clear()
        count = await get_movies_count()
        await message.answer(
            f"✅ Фильм <b>{data['title']}</b> добавлен!\n"
            f"Всего фильмов в базе: <b>{count}</b>",
            parse_mode="HTML"
        )
    except aiosqlite.IntegrityError:
        await message.answer("❌ Такой код уже существует. Попробуй другой.")


# ---------- Админы ----------
@dp.callback_query(F.data == "admin_admins")
async def cb_admins(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Недостаточно прав", show_alert=True)

    admins = await get_admins()
    text = "👥 <b>Обычные админы:</b>\n\n"
    text += "Пока нет." if not admins else "\n".join(f"<code>{uid}</code>" for uid in admins)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Назначить админа", callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Снять админа", callback_data="remove_admin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "add_admin")
async def cb_add_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Введи Telegram ID нового админа:")
    await state.set_state(AddAdmin.waiting_id)
    await state.update_data(action="add")


@dp.callback_query(F.data == "remove_admin")
async def cb_remove_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Введи Telegram ID админа для снятия:")
    await state.set_state(AddAdmin.waiting_id)
    await state.update_data(action="remove")


@dp.message(AddAdmin.waiting_id)
async def process_admin(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        return await message.answer("ID должен быть числом. Попробуй ещё раз:")

    uid = int(message.text.strip())
    data = await state.get_data()
    await state.clear()

    if data.get("action") == "add":
        await add_admin(uid)
        await message.answer(f"✅ <code>{uid}</code> теперь админ", parse_mode="HTML")
    else:
        await remove_admin(uid)
        await message.answer(f"✅ <code>{uid}</code> снят с админки", parse_mode="HTML")


# ---------- Баны ----------
@dp.callback_query(F.data == "admin_bans")
async def cb_bans(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Недостаточно прав", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="ban_user")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="unban_user")],
        [InlineKeyboardButton(text="📋 Список забаненных", callback_data="list_bans")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text("🚫 <b>Управление банами</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "list_bans")
async def cb_list_bans(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return

    banned = await get_banned_users()
    if not banned:
        text = "Список банов пуст."
    else:
        text = "🚫 <b>Забаненные:</b>\n\n"
        for uid, reason in banned:
            text += f"<code>{uid}</code>"
            if reason:
                text += f" — {reason}"
            text += "\n"

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bans")]
    ]))


@dp.callback_query(F.data == "ban_user")
async def cb_ban(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Введи Telegram ID для бана:")
    await state.set_state(BanUser.waiting_id)
    await state.update_data(action="ban")


@dp.callback_query(F.data == "unban_user")
async def cb_unban(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Введи Telegram ID для разбана:")
    await state.set_state(BanUser.waiting_id)
    await state.update_data(action="unban")


@dp.message(BanUser.waiting_id)
async def process_ban(message: Message, state: FSMContext):
    if not message.text or not message.text.strip().isdigit():
        return await message.answer("ID должен быть числом:")

    uid = int(message.text.strip())
    data = await state.get_data()
    await state.clear()

    if data.get("action") == "ban":
        await ban_user(uid)
        await message.answer(f"🚫 <code>{uid}</code> забанен", parse_mode="HTML")
    else:
        await unban_user(uid)
        await message.answer(f"✅ <code>{uid}</code> разбанен", parse_mode="HTML")


# ---------- Выдача фильма (только когда НЕТ активного состояния) ----------
@dp.message(StateFilter(None), F.text)
async def handle_code(message: Message):
    if await is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы в боте.")

    if not await check_sub(message.from_user.id):
        return await message.answer("Сначала подпишись на канал!", reply_markup=subscribe_kb())

    code = message.text.strip()
    movie = await get_movie(code)

    if not movie:
        return await message.answer("❌ Код не найден.")

    await increment_requests()

    caption = (
        f"<b>{movie['title']} ({movie['year']})</b>\n\n"
        f"⭐ <b>IMDb:</b> {movie['rating']}\n\n"
        f"{movie['description']}"
    )
    await message.answer_photo(photo=movie["poster"], caption=caption, parse_mode="HTML")


# -------------------- Запуск --------------------
async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
