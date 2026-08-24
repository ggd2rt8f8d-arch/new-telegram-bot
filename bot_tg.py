import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8644752125:AAFshcTZh4vTOZAb2CzL4Kk0DCzI3W5Cbt8"
CHANNEL_USERNAME = "@topzfilmz"

# Главный админ (твой ID). Только он может назначать других админов и банить.
SUPER_ADMIN_IDS = [2113363430]  # <-- ЗАМЕНИ НА СВОЙ ID

DB_NAME = "movies.db"
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                user_id INTEGER PRIMARY KEY,
                reason TEXT
            )
        """)
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


async def add_movie_to_db(code, title, year, poster, description, rating):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO movies VALUES (?, ?, ?, ?, ?, ?)",
            (code, title, year, poster, description, rating)
        )
        await db.commit()


async def update_movie_field(code: str, field: str, value):
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
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


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


# -------------------- Клавиатуры --------------------
def subscribe_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
    ])


def admin_main_kb(user_id: int):
    buttons = [
        [InlineKeyboardButton(text="📋 Список фильмов", callback_data="admin_list")],
        [InlineKeyboardButton(text="➕ Добавить фильм", callback_data="admin_add")],
    ]
    if is_super_admin(user_id):  # только для главного
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


# -------------------- Проверки --------------------
async def check_sub(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}
    except Exception:
        return False


# ==================== ХЭНДЛЕРЫ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    if await is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы в боте.")

    if await check_sub(message.from_user.id):
        await message.answer("Привет! 👋\nВведи код фильма:")
    else:
        await message.answer("Подпишись на канал, чтобы пользоваться ботом:", reply_markup=subscribe_kb())


@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(callback: CallbackQuery):
    if await check_sub(callback.from_user.id):
        await callback.message.edit_text("✅ Подписка подтверждена!\nВведи код фильма:")
    else:
        await callback.answer("Ты ещё не подписан!", show_alert=True)


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await is_admin(message.from_user.id):
        return await message.answer("⛔ Нет доступа")

    await message.answer("🔧 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=admin_main_kb(message.from_user.id))


@dp.callback_query(F.data == "admin_close")
async def cb_close(callback: CallbackQuery):
    await callback.message.delete()


@dp.callback_query(F.data == "admin_list")
async def cb_list(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return

    movies = await get_all_movies()
    if not movies:
        return await callback.message.edit_text("База пустая.", reply_markup=admin_main_kb(callback.from_user.id))

    buttons = []
    for code, title, year in movies:
        buttons.append([InlineKeyboardButton(text=f"{code} — {title} ({year})", callback_data=f"movie:{code}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])

    await callback.message.edit_text("📋 <b>Список фильмов:</b>\nВыбери фильм для редактирования:", parse_mode="HTML",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data == "admin_back")
async def cb_back(callback: CallbackQuery):
    await callback.message.edit_text("🔧 <b>Админ-панель</b>", parse_mode="HTML",
                                     reply_markup=admin_main_kb(callback.from_user.id))


@dp.callback_query(F.data.startswith("movie:"))
async def cb_movie(callback: CallbackQuery):
    code = callback.data.split(":")[1]
    movie = await get_movie(code)
    if not movie:
        return await callback.answer("Фильм не найден", show_alert=True)

    text = (
        f"<b>{movie['title']} ({movie['year']})</b>\n"
        f"Код: <code>{movie['code']}</code>\n"
        f"IMDb: {movie['rating']}\n\n"
        f"{movie['description'][:150]}..."
    )
    await callback.message.edit_text(text, parse_mode="HTML",
                                     reply_markup=movie_actions_kb(code, callback.from_user.id))


# ---------- Удаление фильма (только супер) ----------
@dp.callback_query(F.data.startswith("delete_movie:"))
async def cb_delete_movie(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Недостаточно прав", show_alert=True)

    code = callback.data.split(":")[1]
    await delete_movie(code)
    await callback.answer("Фильм удалён")
    await cb_list(callback)


# ---------- Редактирование ----------
@dp.callback_query(F.data.startswith("edit_"))
async def cb_edit_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return

    action, code = callback.data.split(":")
    field = action.replace("edit_", "")  # title / year / poster ...

    await state.update_data(edit_code=code, edit_field=field)
    await callback.message.edit_text(f"Введи новое значение для <b>{field}</b>:", parse_mode="HTML")
    await state.set_state(EditMovie.waiting_value)


@dp.message(EditMovie.waiting_value)
async def process_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    code = data["edit_code"]
    field = data["edit_field"]
    value = message.text.strip()

    if field == "year" and not value.isdigit():
        return await message.answer("Год должен быть числом. Попробуй ещё раз:")

    if field == "year":
        value = int(value)

    await update_movie_field(code, field, value)
    await message.answer("✅ Обновлено!")
    await state.clear()

    # Показываем снова карточку фильма
    movie = await get_movie(code)
    text = (
        f"<b>{movie['title']} ({movie['year']})</b>\n"
        f"Код: <code>{movie['code']}</code>\n"
        f"IMDb: {movie['rating']}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=movie_actions_kb(code, message.from_user.id))


# ---------- Добавление фильма ----------
@dp.callback_query(F.data == "admin_add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        return
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
        return await message.answer("Год — число:")
    await state.update_data(year=int(message.text.strip()))
    await message.answer("Ссылка на <b>обложку</b>:", parse_mode="HTML")
    await state.set_state(AddMovie.poster)


@dp.message(AddMovie.poster)
async def add_poster(message: Message, state: FSMContext):
    await state.update_data(poster=message.text.strip())
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
    await add_movie_to_db(data["code"], data["title"], data["year"], data["poster"], data["description"], message.text.strip())
    await message.answer(f"✅ Фильм <b>{data['title']}</b> добавлен!", parse_mode="HTML")
    await state.clear()


# ---------- Управление админами (только супер) ----------
@dp.callback_query(F.data == "admin_admins")
async def cb_admins(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Недостаточно прав", show_alert=True)

    admins = await get_admins()
    text = "👥 <b>Админы:</b>\n\n"
    if not admins:
        text += "Пока нет обычных админов."
    else:
        for uid in admins:
            text += f"<code>{uid}</code>\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Назначить админа", callback_data="add_admin")],
        [InlineKeyboardButton(text="➖ Снять админа", callback_data="remove_admin")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "add_admin")
async def cb_add_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи Telegram ID нового админа:")
    await state.set_state(AddAdmin.waiting_id)


@dp.message(AddAdmin.waiting_id)
async def process_add_admin(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("ID должен быть числом:")
    uid = int(message.text.strip())
    await add_admin(uid)
    await message.answer(f"✅ Пользователь <code>{uid}</code> теперь админ", parse_mode="HTML")
    await state.clear()


@dp.callback_query(F.data == "remove_admin")
async def cb_remove_admin(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи Telegram ID админа, которого снять:")
    await state.set_state(AddAdmin.waiting_id)  # переиспользуем
    await state.update_data(action="remove")


# ---------- Баны (только супер) ----------
@dp.callback_query(F.data == "admin_bans")
async def cb_bans(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return await callback.answer("Недостаточно прав", show_alert=True)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="ban_user")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="unban_user")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_text("🚫 <b>Управление банами</b>", parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "ban_user")
async def cb_ban(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи Telegram ID пользователя для бана:")
    await state.set_state(BanUser.waiting_id)
    await state.update_data(action="ban")


@dp.callback_query(F.data == "unban_user")
async def cb_unban(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введи Telegram ID для разбана:")
    await state.set_state(BanUser.waiting_id)
    await state.update_data(action="unban")


@dp.message(BanUser.waiting_id)
async def process_ban(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("ID — число:")
    uid = int(message.text.strip())
    data = await state.get_data()

    if data.get("action") == "ban":
        await ban_user(uid)
        await message.answer(f"🚫 Пользователь <code>{uid}</code> забанен", parse_mode="HTML")
    else:
        await unban_user(uid)
        await message.answer(f"✅ Пользователь <code>{uid}</code> разбанен", parse_mode="HTML")
    await state.clear()


# ---------- Выдача фильма ----------
@dp.message(F.text)
async def handle_code(message: Message):
    if await is_banned(message.from_user.id):
        return await message.answer("🚫 Вы заблокированы в боте.")

    if not await check_sub(message.from_user.id):
        return await message.answer("Сначала подпишись на канал!", reply_markup=subscribe_kb())

    movie = await get_movie(message.text.strip())
    if not movie:
        return await message.answer("❌ Код не найден.")

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
