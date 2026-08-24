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

# Сюда впиши свой Telegram ID (узнать можно у @userinfobot)
ADMIN_IDS = [2113363430]  # <-- ЗАМЕНИ НА СВОЙ ID

DB_NAME = "movies.db"
# ===================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# ---------- Состояния для добавления фильма ----------
class AddMovie(StatesGroup):
    code = State()
    title = State()
    year = State()
    poster = State()
    description = State()
    rating = State()


# ---------- Работа с базой ----------
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
        await db.commit()


async def add_movie_to_db(code, title, year, poster, description, rating):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO movies (code, title, year, poster, description, rating) VALUES (?, ?, ?, ?, ?, ?)",
            (code, title, year, poster, description, rating)
        )
        await db.commit()


async def get_movie(code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT * FROM movies WHERE code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "code": row[0],
                    "title": row[1],
                    "year": row[2],
                    "poster": row[3],
                    "description": row[4],
                    "rating": row[5]
                }
            return None


async def get_all_movies():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT code, title, year FROM movies ORDER BY code") as cursor:
            return await cursor.fetchall()


async def delete_movie(code: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM movies WHERE code = ?", (code,))
        await db.commit()


# ---------- Клавиатуры ----------
def get_subscribe_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
    ])


# ---------- Проверка подписки ----------
async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR
        }
    except Exception:
        return False


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ==================== ХЭНДЛЕРЫ ====================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    if await is_subscribed(message.from_user.id):
        await message.answer("Привет! 👋\nВведи цифровой код фильма:")
    else:
        await message.answer(
            "Привет! 👋\nЧтобы пользоваться ботом, подпишись на канал:",
            reply_markup=get_subscribe_keyboard()
        )


@dp.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text("✅ Подписка подтверждена!\n\nВведи код фильма:")
    else:
        await callback.answer("❌ Ты ещё не подписан!", show_alert=True)


# ---------- Админ-команды ----------
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return await message.answer("⛔ Нет доступа")

    text = (
        "🔧 <b>Админ-панель</b>\n\n"
        "/add — добавить фильм\n"
        "/list — список всех фильмов\n"
        "/del код — удалить фильм\n"
        "Пример: /del 1234"
    )
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("list"))
async def cmd_list(message: Message):
    if not is_admin(message.from_user.id):
        return

    movies = await get_all_movies()
    if not movies:
        return await message.answer("База пустая.")

    text = "📋 <b>Список фильмов:</b>\n\n"
    for code, title, year in movies:
        text += f"<code>{code}</code> — {title} ({year})\n"

    await message.answer(text, parse_mode="HTML")


@dp.message(Command("del"))
async def cmd_del(message: Message):
    if not is_admin(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.answer("Использование: /del код")

    code = parts[1].strip()
    movie = await get_movie(code)
    if not movie:
        return await message.answer("❌ Фильм с таким кодом не найден")

    await delete_movie(code)
    await message.answer(f"✅ Фильм <b>{movie['title']}</b> удалён", parse_mode="HTML")


# ---------- Добавление фильма (FSM) ----------
@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer("Введи <b>код</b> фильма (например 1234):", parse_mode="HTML")
    await state.set_state(AddMovie.code)


@dp.message(AddMovie.code)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip()
    if await get_movie(code):
        await message.answer("⚠️ Такой код уже существует. Введи другой:")
        return

    await state.update_data(code=code)
    await message.answer("Введи <b>название</b> фильма:", parse_mode="HTML")
    await state.set_state(AddMovie.title)


@dp.message(AddMovie.title)
async def process_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await message.answer("Введи <b>год</b> выхода (например 2014):", parse_mode="HTML")
    await state.set_state(AddMovie.year)


@dp.message(AddMovie.year)
async def process_year(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        await message.answer("Год должен быть числом. Попробуй ещё раз:")
        return

    await state.update_data(year=int(message.text.strip()))
    await message.answer("Отправь <b>ссылку на обложку</b> (прямую ссылку на картинку):", parse_mode="HTML")
    await state.set_state(AddMovie.poster)


@dp.message(AddMovie.poster)
async def process_poster(message: Message, state: FSMContext):
    await state.update_data(poster=message.text.strip())
    await message.answer("Введи <b>краткое описание</b> фильма:", parse_mode="HTML")
    await state.set_state(AddMovie.description)


@dp.message(AddMovie.description)
async def process_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("Введи <b>оценку IMDb</b> (например 8.7):", parse_mode="HTML")
    await state.set_state(AddMovie.rating)


@dp.message(AddMovie.rating)
async def process_rating(message: Message, state: FSMContext):
    data = await state.get_data()
    rating = message.text.strip()

    await add_movie_to_db(
        code=data["code"],
        title=data["title"],
        year=data["year"],
        poster=data["poster"],
        description=data["description"],
        rating=rating
    )

    await message.answer(
        f"✅ Фильм успешно добавлен!\n\n"
        f"<b>{data['title']} ({data['year']})</b>\n"
        f"Код: <code>{data['code']}</code>",
        parse_mode="HTML"
    )
    await state.clear()


# ---------- Выдача фильма по коду ----------
@dp.message(F.text)
async def handle_code(message: Message):
    if not await is_subscribed(message.from_user.id):
        await message.answer("❌ Сначала подпишись на канал!", reply_markup=get_subscribe_keyboard())
        return

    code = message.text.strip()
    movie = await get_movie(code)

    if not movie:
        await message.answer("❌ Код не найден.")
        return

    caption = (
        f"<b>{movie['title']} ({movie['year']})</b>\n\n"
        f"⭐ <b>IMDb:</b> {movie['rating']}\n\n"
        f"{movie['description']}"
    )

    await message.answer_photo(
        photo=movie["poster"],
        caption=caption,
        parse_mode="HTML"
    )


# ---------- Запуск ----------
async def main():
    await init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
