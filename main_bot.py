import asyncio
import logging
import traceback
import aiosqlite  # Добавили для работы с памятью вакансий
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TG_BOT_TOKEN
from app.handlers.commands import router
from app.database.models import init_db, get_user_settings, DB_NAME

# Импортируем наши боевые сервисы и агентов
from app.services.hh_client import HHClient
from app.agents.analyzer import AnalyzerAgent
from app.agents.writer import WriterAgent
from app.services.telegram import TelegramNotifier

# Включаем логирование
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TG_BOT_TOKEN)
dp = Dispatcher()

# --- ФУНКЦИИ ДЛЯ ПАМЯТИ ВАКАНСИЙ ---
async def init_seen_db():
    """Создает таблицу для хранения просмотренных вакансий."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS seen_vacancies (
                user_id INTEGER,
                vacancy_id TEXT,
                UNIQUE(user_id, vacancy_id)
            )
        ''')
        await db.commit()

async def is_vacancy_seen(user_id: int, vacancy_id: str) -> bool:
    """Проверяет, видел ли уже этот пользователь эту вакансию."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT 1 FROM seen_vacancies WHERE user_id = ? AND vacancy_id = ?", 
            (user_id, str(vacancy_id))
        ) as cursor:
            return await cursor.fetchone() is not None

async def mark_vacancy_seen(user_id: int, vacancy_id: str):
    """Отмечает вакансию как просмотренную для конкретного пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR IGNORE INTO seen_vacancies (user_id, vacancy_id) VALUES (?, ?)", 
            (user_id, str(vacancy_id))
        )
        await db.commit()

async def clear_user_history(user_id: int):
    """Очищает историю просмотренных вакансий для пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM seen_vacancies WHERE user_id = ?", (user_id,))
        await db.commit()
# ------------------------------------

async def run_search_job(user_id: int):
    """Главная функция: берет данные из БД и запускает агентов для одного пользователя."""
    settings = await get_user_settings(user_id)
    
    if not settings:
        logging.info(f"Настройки для пользователя {user_id} не найдены.")
        return

    resume_text = settings.get('resume_text')
    keywords = settings.get('keywords')

    if not resume_text or not keywords:
        await bot.send_message(user_id, "⚠️ Не могу начать поиск: не задано резюме или ключевые слова. Настрой их в меню!")
        return

    await bot.send_message(user_id, "🔍 Начинаю поиск вакансий по твоим ключам. Это может занять пару минут...")
    
    hh_client = HHClient()
    analyzer = AnalyzerAgent()
    writer = WriterAgent()
    
    # ВАЖНО: Передаем конкретный user_id, чтобы бот писал нужному другу, а не только вам
    tg_notifier = TelegramNotifier(chat_id=str(user_id)) 
    
    try:
        # 1. Получаем вакансии
        vacancies = await hh_client.fetch_vacancies(keywords=keywords, max_pages=1)
        if not vacancies:
            await bot.send_message(user_id, "🤷‍♂️ По твоим ключам пока нет новых вакансий на HH.")
            return

        found_good = 0
        skipped = 0
        
        # 2. Анализируем каждую
        for vac in vacancies:
            # Получаем уникальный ID вакансии (или ссылку, если ID вдруг нет)
            vac_id = str(getattr(vac, 'id', getattr(vac, 'alternate_url', vac.name)))
            
            # ПРОВЕРКА ПАМЯТИ: Если уже видели — пропускаем!
            if await is_vacancy_seen(user_id, vac_id):
                skipped += 1
                continue

            logging.info(f"[{user_id}] Анализируем: {getattr(vac, 'name', 'Неизвестная вакансия')}")
            
            # Безопасно собираем текст вакансии
            vac_text = ""
            if hasattr(vac, 'description') and vac.description:
                vac_text = vac.description
            elif hasattr(vac, 'snippet') and vac.snippet:
                req = vac.snippet.get('requirement', '') if isinstance(vac.snippet, dict) else getattr(vac.snippet, 'requirement', '')
                res = vac.snippet.get('responsibility', '') if isinstance(vac.snippet, dict) else getattr(vac.snippet, 'responsibility', '')
                req = req if req else ""
                res = res if res else ""
                vac_text = f"Требования: {req}\nОбязанности: {res}"
            else:
                vac_text = str(getattr(vac, '__dict__', vac))

            # Безопасное получение компании и ссылки
            company_name = "Неизвестная компания"
            if hasattr(vac, 'company_name'):
                company_name = vac.company_name
            elif hasattr(vac, 'employer') and vac.employer:
                if isinstance(vac.employer, dict):
                    company_name = vac.employer.get('name', 'Неизвестная компания')
                else:
                    company_name = getattr(vac.employer, 'name', 'Неизвестная компания')
            vac_url = getattr(vac, 'alternate_url', getattr(vac, 'url', 'Нет ссылки'))

            # Прогоняем через аналитика
            analysis = await analyzer.analyze_vacancy(vac_text, resume_text)
            
            # Отмечаем как просмотренную, чтобы больше не анализировать её в будущем
            await mark_vacancy_seen(user_id, vac_id)
            
            # 3. Фильтруем и пишем письмо
            if analysis.match_score >= 60:
                letter = await writer.generate_letter(vac_text, resume_text)
                
                # 4. Отправляем в Telegram
                await tg_notifier.send_vacancy_alert(
                    title=getattr(vac, 'name', 'Неизвестная вакансия'),
                    company=company_name,
                    url=vac_url,
                    score=analysis.match_score,
                    reason=analysis.brief_reason,
                    cover_letter=letter.text
                )
                found_good += 1
        
        await bot.send_message(user_id, f"✅ Поиск завершен!\nНовых крутых вакансий найдено: {found_good}\nПропущено старых: {skipped}")
        
    except Exception as e:
        err_trace = traceback.format_exc()
        logging.error(f"Ошибка во время поиска для {user_id}:\n{err_trace}")
        safe_error = str(e).replace('<', '&lt;').replace('>', '&gt;')
        await bot.send_message(
            user_id, 
            f"❌ <b>Произошла ошибка во время поиска.</b>\n\n"
            f"<b>Техническая деталь:</b>\n<code>{safe_error}</code>",
            parse_mode="HTML"
        )

async def scheduled_search_for_all():
    """Функция планировщика: собирает всех активных пользователей и запускает для них поиск."""
    logging.info("Запуск планового поиска для всех активных пользователей...")
    async with aiosqlite.connect(DB_NAME) as db:
        # Ищем всех, у кого is_active = 1 (включен автопоиск)
        async with db.execute("SELECT user_id FROM user_settings WHERE is_active = 1") as cursor:
            users = await cursor.fetchall()
            
    for (user_id,) in users:
        # Запускаем поиск для каждого пользователя асинхронно
        asyncio.create_task(run_search_job(user_id))


@dp.message(F.text == "🚀 Искать сейчас")
async def manual_search(message: Message):
    await run_search_job(message.from_user.id)

@dp.message(F.text == "🧹 Очистить историю")
async def clear_history_handler(message: Message):
    await clear_user_history(message.from_user.id)
    await message.answer("🧹 История просмотренных вакансий успешно очищена!\nТеперь при следующем поиске бот заново проверит все актуальные вакансии на HH.")

async def main():
    await init_db()
    await init_seen_db() # Инициализируем таблицу с памятью вакансий
    dp.include_router(router)
    
    scheduler = AsyncIOScheduler()
    # Теперь планировщик вызывает функцию, которая обрабатывает ВСЕХ друзей
    scheduler.add_job(scheduled_search_for_all, "interval", hours=4)
    scheduler.start()
    
    logging.info("Бот успешно запущен и ждет команд!")
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())