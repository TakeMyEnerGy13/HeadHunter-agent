import logging
from html import escape

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.agents.writer import WriterAgent, WriterAgentError
from app.database.models import get_user_settings, update_user_settings
from app.sources.telegram_feed import fetch_from_config, get_recent_posts
from app.utils.fetcher import fetch_job_text

logger = logging.getLogger(__name__)

# Роутер — это как диспетчер маршруток, он распределяет сообщения по нужным функциям
router = Router()

# Состояния, в которых может находиться пользователь
class UserState(StatesGroup):
    waiting_for_resume = State()
    waiting_for_keywords = State()
    waiting_for_negative_keywords = State()
    waiting_for_tone_samples = State()
    waiting_for_preferences = State()
    waiting_for_job_posting = State()

# Создаем клавиатуру (меню) - добавили новые кнопки!
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Искать сейчас"), KeyboardButton(text="✍️ Написать письмо")],
            [KeyboardButton(text="📡 TG вакансии"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="📖 Как это работает?")],
        ],
        resize_keyboard=True
    )


def get_tg_sources_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📡 Скан TG"), KeyboardButton(text="🗂 TG посты")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def get_settings_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Изменить резюме"), KeyboardButton(text="🔑 Изменить ключи")],
            [KeyboardButton(text="🚫 Изменить исключения"), KeyboardButton(text="🎨 Стиль письма")],
            [KeyboardButton(text="📌 Предпочтения"), KeyboardButton(text="⚙️ Статус автопоиска")],
            [KeyboardButton(text="ℹ️ Мои настройки"), KeyboardButton(text="🧹 Очистить историю")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True,
    )


def _clip_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Срабатывает при команде /start"""
    # Инициализируем пользователя в базе
    await update_user_settings(message.from_user.id) 
    await message.answer(
        "Привет! Я твой личный AI-рекрутер. 🤖\n"
        "Я буду искать вакансии по твоим правилам, оценивать их и писать сопроводительные письма.\n\n"
        "Для начала давай загрузим резюме и настроим ключевые слова в меню ниже:",
        reply_markup=get_main_keyboard()
    )


@router.message(F.text == "📡 TG вакансии")
async def show_tg_sources_menu(message: Message):
    await message.answer("Раздел Telegram-вакансий:", reply_markup=get_tg_sources_keyboard())


@router.message(F.text == "⚙️ Настройки")
async def show_settings_menu(message: Message):
    await message.answer("Раздел настроек:", reply_markup=get_settings_keyboard())


@router.message(F.text == "⬅️ Назад")
async def back_to_main_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())


@router.message(F.text == "ℹ️ Мои настройки")
async def show_settings(message: Message):
    """Показывает текущие настройки из БД"""
    settings = await get_user_settings(message.from_user.id)
    if not settings:
        await message.answer("Настройки не найдены. Нажми /start")
        return
    
    status = "ВКЛЮЧЕН ✅" if settings['is_active'] else "ВЫКЛЮЧЕН ❌"
    keys = ", ".join(settings['keywords']) if settings['keywords'] else "Не заданы"
    negative_keys = ", ".join(settings['negative_keywords']) if settings.get('negative_keywords') else "Не заданы"
    res_len = len(settings['resume_text']) if settings['resume_text'] else 0
    
    text = (
        f"📊 <b>Твои настройки:</b>\n\n"
        f"Автопоиск (каждые 4 часа): {status}\n"
        f"Ключевые слова: <code>{keys}</code>\n"
        f"Исключающие слова: <code>{negative_keys}</code>\n"
        f"Резюме загружено: {'Да' if res_len > 0 else 'Нет'} ({res_len} символов)"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "⚙️ Статус автопоиска")
async def toggle_auto_search(message: Message):
    """Включает/выключает автопоиск"""
    settings = await get_user_settings(message.from_user.id)
    if not settings:
        return
    new_status = not settings['is_active']
    await update_user_settings(message.from_user.id, is_active=new_status)
    status_text = "ВКЛЮЧЕН ✅" if new_status else "ВЫКЛЮЧЕН ❌"
    await message.answer(f"Автопоиск теперь {status_text}")

@router.message(F.text == "📝 Изменить резюме")
async def ask_for_resume(message: Message, state: FSMContext):
    """Просит прислать резюме и переводит бота в режим ожидания"""
    await message.answer("Отправь мне текст своего резюме следующим сообщением:\n(Можно просто скопировать текст из документа)")
    await state.set_state(UserState.waiting_for_resume)

@router.message(StateFilter(UserState.waiting_for_resume))
async def save_resume(message: Message, state: FSMContext):
    """Ловит текст резюме и сохраняет в БД"""
    await update_user_settings(message.from_user.id, resume_text=message.text)
    await message.answer("✅ Резюме успешно сохранено в базу данных!")
    await state.clear() # Выходим из режима ожидания

@router.message(F.text == "🔑 Изменить ключи")
async def ask_for_keywords(message: Message, state: FSMContext):
    """Просит прислать ключевые слова"""
    await message.answer(
        "Отправь ключевые слова для поиска <b>через запятую</b>.\n"
        "Пример: <i>Python Developer, AI Engineer, FastAPI</i>", 
        parse_mode="HTML"
    )
    await state.set_state(UserState.waiting_for_keywords)

@router.message(StateFilter(UserState.waiting_for_keywords))
async def save_keywords(message: Message, state: FSMContext):
    """Ловит ключевые слова, разбивает их в список и сохраняет"""
    # Превращаем "Python, AI" в список ["Python", "AI"]
    keys = [k.strip() for k in message.text.split(",") if k.strip()]
    await update_user_settings(message.from_user.id, keywords=keys)
    await message.answer(f"✅ Ключевые слова сохранены: {', '.join(keys)}")
    await state.clear()


@router.message(F.text == "🚫 Изменить исключения")
async def ask_for_negative_keywords(message: Message, state: FSMContext):
    """Просит прислать исключающие слова для отсечения нерелевантных вакансий."""
    await message.answer(
        "Отправь слова-исключения <b>через запятую</b>.\n"
        "Если любое из них встретится в вакансии, бот ее пропустит.\n"
        "Пример: <i>Senior, Team Lead, C++</i>\n"
        "Чтобы очистить список, отправь: <code>-</code>",
        parse_mode="HTML",
    )
    await state.set_state(UserState.waiting_for_negative_keywords)


@router.message(StateFilter(UserState.waiting_for_negative_keywords))
async def save_negative_keywords(message: Message, state: FSMContext):
    """Ловит исключающие слова, разбивает в список и сохраняет."""
    raw_text = (message.text or "").strip()
    if raw_text == "-":
        negative_keys: list[str] = []
    else:
        negative_keys = [k.strip() for k in raw_text.split(",") if k.strip()]

    await update_user_settings(message.from_user.id, negative_keywords=negative_keys)

    if negative_keys:
        await message.answer(f"✅ Исключающие слова сохранены: {', '.join(negative_keys)}")
    else:
        await message.answer("✅ Список исключающих слов очищен.")
    await state.clear()

@router.message(F.text == "📖 Как это работает?")
async def show_guide(message: Message):
    """Показывает справку по боту"""
    guide_text = (
        "<b>🤖 Краткий гайд по AI-Рекрутеру:</b>\n\n"
        "1️⃣ <b>Главное меню:</b> быстрый поиск, ручное письмо, TG-вакансии и настройки.\n"
        "2️⃣ <b>Настройки:</b> нажми «⚙️ Настройки», чтобы обновить резюме, ключи, исключения, стиль и предпочтения.\n"
        "3️⃣ <b>Поиск HH:</b> нажми «🚀 Искать сейчас» или включи автопоиск в настройках.\n"
        "4️⃣ <b>TG-вакансии:</b> нажми «📡 TG вакансии», затем «📡 Скан TG» или «🗂 TG посты».\n"
        "5️⃣ <b>Письмо вручную:</b> нажми «✍️ Написать письмо» и отправь текст вакансии или ссылку.\n"
        "6️⃣ <b>Память:</b> бот запоминает просмотренные вакансии. Сброс истории находится в настройках."
    )
    await message.answer(guide_text, parse_mode="HTML")


@router.message(F.text == "🎨 Стиль письма")
async def ask_for_tone_samples(message: Message, state: FSMContext):
    """Просит прислать примеры стиля письма."""
    await message.answer(
        "Отправь 1-3 примера текстов в своём стиле — сообщения, посты, фрагменты писем.\n"
        "Бот изучит лексику, длину предложений и структуру, чтобы писать в твоём тоне.\n"
        "Чтобы очистить, отправь: <code>-</code>",
        parse_mode="HTML",
    )
    await state.set_state(UserState.waiting_for_tone_samples)


@router.message(StateFilter(UserState.waiting_for_tone_samples))
async def save_tone_samples(message: Message, state: FSMContext):
    """Сохраняет примеры стиля."""
    raw = (message.text or "").strip()
    tone_samples = "" if raw == "-" else raw
    await update_user_settings(message.from_user.id, tone_samples=tone_samples)
    if tone_samples:
        await message.answer("✅ Примеры стиля сохранены. Бот будет стараться писать похоже.")
    else:
        await message.answer("✅ Примеры стиля очищены.")
    await state.clear()


@router.message(F.text == "📌 Предпочтения")
async def ask_for_preferences(message: Message, state: FSMContext):
    """Просит прислать пожелания к письму."""
    await message.answer(
        "Напиши свои пожелания к сопроводительным письмам.\n"
        "Например: <i>не больше 3 абзацев, без официоза, делай акцент на ML-опыте</i>.\n"
        "Чтобы очистить, отправь: <code>-</code>",
        parse_mode="HTML",
    )
    await state.set_state(UserState.waiting_for_preferences)


@router.message(StateFilter(UserState.waiting_for_preferences))
async def save_preferences(message: Message, state: FSMContext):
    """Сохраняет пожелания к письму."""
    raw = (message.text or "").strip()
    preferences = "" if raw == "-" else raw
    await update_user_settings(message.from_user.id, preferences=preferences)
    if preferences:
        await message.answer("✅ Предпочтения сохранены.")
    else:
        await message.answer("✅ Предпочтения очищены.")
    await state.clear()


@router.message(F.text == "📡 Скан TG")
async def scan_telegram_sources(message: Message):
    """Запускает ручной scan Telegram job channels из настроек .env."""
    settings = await get_user_settings(message.from_user.id)
    if not settings:
        await message.answer("Настройки не найдены. Нажми /start")
        return

    keywords = settings.get("keywords") or None
    negative_keywords = settings.get("negative_keywords") or None
    status_msg = await message.answer("📡 Сканирую Telegram-каналы...")

    try:
        stats = await fetch_from_config(
            keywords=keywords,
            negative_keywords=negative_keywords,
            limit=30,
            verbose=False,
        )
    except Exception as exc:
        logger.error("Telegram source scan failed for user %s: %s", message.from_user.id, exc)
        await status_msg.delete()
        await message.answer(
            "❌ Не удалось просканировать Telegram-каналы.\n"
            f"Техническая деталь: <code>{escape(str(exc))}</code>",
            parse_mode="HTML",
        )
        return

    await status_msg.delete()
    if not stats:
        await message.answer("Telegram-каналы не настроены. Проверь TG_JOB_CHANNELS в .env.")
        return

    saved_total = sum(item.saved for item in stats)
    scanned_total = sum(item.scanned for item in stats)
    filtered_total = sum(item.filtered for item in stats)
    duplicates_total = sum(item.duplicates for item in stats)
    lines = [
        "📡 <b>Telegram scan завершён</b>",
        f"Просмотрено сообщений: {scanned_total}",
        f"Сохранено новых: {saved_total}",
        f"Дубликаты: {duplicates_total}",
        f"Отфильтровано: {filtered_total}",
        "",
        "Каналы:",
    ]
    for item in stats:
        lines.append(
            f"@{escape(item.channel)}: saved={item.saved}, duplicates={item.duplicates}, filtered={item.filtered}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(F.text == "🗂 TG посты")
async def show_saved_telegram_posts(message: Message):
    """Показывает последние сохранённые Telegram job posts."""
    posts = await get_recent_posts(limit=10)
    if not posts:
        await message.answer("Сохранённых TG-постов пока нет. Нажми «📡 Скан TG».")
        return

    chunks = []
    for post in posts:
        title = _clip_text(post.title, 180)
        channel = post.channel
        line = f"@{channel} #{post.message_id}\n{title}"
        if post.url:
            line += f"\n{post.url}"
        chunks.append(line)

    text = "🗂 Последние TG-посты:\n\n" + "\n\n".join(chunks)
    if len(text) > 4096:
        text = _clip_text(text, 4096)
    await message.answer(text)


@router.message(F.text == "✍️ Написать письмо")
async def ask_for_job_posting(message: Message, state: FSMContext):
    """Запрашивает вакансию для генерации письма."""
    await message.answer(
        "Отправь текст вакансии или ссылку на неё — я напишу сопроводительное письмо прямо сейчас."
    )
    await state.set_state(UserState.waiting_for_job_posting)


@router.message(StateFilter(UserState.waiting_for_job_posting))
async def generate_letter_handler(message: Message, state: FSMContext):
    """Принимает вакансию (текст или URL), запускает пайплайн, отвечает письмом."""
    await state.clear()

    settings = await get_user_settings(message.from_user.id)
    if not settings or not settings.get("resume_text"):
        await message.answer("⚠️ Сначала загрузи резюме: ⚙️ Настройки → 📝 Изменить резюме.")
        return

    source = (message.text or "").strip()
    if not source:
        await message.answer("Получил пустое сообщение. Попробуй ещё раз.")
        return

    status_msg = await message.answer("⏳ Генерирую письмо, это займёт около минуты...")

    try:
        job_text = await fetch_job_text(source)
    except ValueError as e:
        await status_msg.delete()
        await message.answer(f"❌ Не удалось загрузить вакансию: {e}")
        return

    writer = WriterAgent()
    try:
        letter = await writer.generate_letter(
            vacancy_text=job_text,
            resume_text=settings["resume_text"],
            tone_samples=settings.get("tone_samples", ""),
            preferences=settings.get("preferences", ""),
        )
    except WriterAgentError as e:
        logger.error("WriterAgent failed for user %s: %s", message.from_user.id, e)
        await status_msg.delete()
        await message.answer("❌ Не удалось сгенерировать письмо. Попробуй позже.")
        return

    await status_msg.delete()

    # Telegram limit: 4096 chars per message
    text = letter.text
    if len(text) > 4096:
        text = text[:4090] + "…"
    await message.answer(text)
