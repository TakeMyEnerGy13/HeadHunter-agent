from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.database.models import get_user_settings, update_user_settings

# Роутер — это как диспетчер маршруток, он распределяет сообщения по нужным функциям
router = Router()

# Состояния, в которых может находиться пользователь
class UserState(StatesGroup):
    waiting_for_resume = State()
    waiting_for_keywords = State()

# Создаем клавиатуру (меню) - добавили новые кнопки!
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Изменить резюме"), KeyboardButton(text="🔑 Изменить ключи")],
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
    res_len = len(settings['resume_text']) if settings['resume_text'] else 0
    
    text = (
        f"📊 <b>Твои настройки:</b>\n\n"
        f"Автопоиск (каждые 4 часа): {status}\n"
        f"Ключевые слова: <code>{keys}</code>\n"
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

@router.message(F.text == "📖 Как это работает?")
async def show_guide(message: Message):
    """Показывает справку по боту"""
    guide_text = (
        "<b>🤖 Краткий гайд по AI-Рекрутеру:</b>\n\n"
        "1️⃣ <b>Настройка:</b> Отправь свое резюме (📝) и ключевые слова (🔑, например: <i>Python, AI</i>).\n"
        "2️⃣ <b>Поиск:</b> Нажми «🚀 Искать сейчас» или включи автопоиск (⚙️).\n"
        "3️⃣ <b>Анализ:</b> Бот найдет вакансии на HH, прочитает их и сравнит с твоим резюме. Тебе придут только те, которые подходят на 60% и выше.\n"
        "4️⃣ <b>Умная память:</b> Бот запоминает, что он тебе уже отправлял (и что пропускал). Он не будет присылать одни и те же вакансии дважды.\n"
        "5️⃣ <b>Сброс:</b> Если ты обновил резюме и хочешь заново проверить старые вакансии, нажми «🧹 Очистить историю»."
    )
    await message.answer(guide_text, parse_mode="HTML")