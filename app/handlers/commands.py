import logging

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.agents.writer import WriterAgent, WriterAgentError
from app.database.models import get_user_settings, update_user_settings
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
            [KeyboardButton(text="📝 Изменить резюме"), KeyboardButton(text="🔑 Изменить ключи")],
            [KeyboardButton(text="🚫 Изменить исключения")],
            [KeyboardButton(text="🎨 Стиль письма"), KeyboardButton(text="📌 Предпочтения")],
            [KeyboardButton(text="✍️ Написать письмо")],
            [KeyboardButton(text="⚙️ Статус автопоиска"), KeyboardButton(text="🚀 Искать сейчас")],
            [KeyboardButton(text="🧹 Очистить историю"), KeyboardButton(text="📖 Как это работает?")],
            [KeyboardButton(text="ℹ️ Мои настройки")]
        ],
        resize_keyboard=True
    )

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
        "1️⃣ <b>Настройка:</b> Отправь свое резюме (📝) и ключевые слова (🔑, например: <i>Python, AI</i>).\n"
        "2️⃣ <b>Исключения:</b> Добавь стоп-слова (🚫), чтобы отсечь неподходящие вакансии (например: <i>Team Lead</i>).\n"
        "3️⃣ <b>Стиль и предпочтения:</b> Обучи бота своему стилю (🎨) и задай пожелания к письмам (📌).\n"
        "4️⃣ <b>Поиск:</b> Нажми «🚀 Искать сейчас» или включи автопоиск (⚙️).\n"
        "5️⃣ <b>Письмо вручную:</b> Нажми «✍️ Написать письмо» и отправь текст вакансии или ссылку — бот напишет письмо сразу.\n"
        "6️⃣ <b>Анализ:</b> Бот найдет вакансии на HH, прочитает их и сравнит с твоим резюме. Тебе придут только те, которые подходят на 60% и выше.\n"
        "7️⃣ <b>Умная память:</b> Бот запоминает, что он тебе уже отправлял (и что пропускал). Он не будет присылать одни и те же вакансии дважды.\n"
        "8️⃣ <b>Сброс:</b> Если ты обновил резюме и хочешь заново проверить старые вакансии, нажми «🧹 Очистить историю»."
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
        await message.answer("⚠️ Сначала загрузи резюме (кнопка 📝 Изменить резюме).")
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