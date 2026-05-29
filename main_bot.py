import asyncio
import logging
import traceback
import aiosqlite  # Добавили для работы с памятью вакансий
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Message
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TG_BOT_TOKEN
from app.handlers.commands import router
from app.database.models import init_db, get_user_settings, DB_NAME

# Импортируем наши боевые сервисы и агентов
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

async def count_seen_vacancies(user_id: int) -> int:
    """Сколько уникальных вакансий пользователь уже просматривал (всего в истории)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM seen_vacancies WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

async def get_seen_ids(user_id: int) -> set[str]:
    """Load all seen vacancy IDs for a user as a set (for fast lookup)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT vacancy_id FROM seen_vacancies WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
# ------------------------------------

async def run_search_job(user_id: int):
    """Main search function: fetches from all active sources, analyzes, writes letters."""
    from app.sources.registry import get_active_sources

    settings = await get_user_settings(user_id)

    if not settings:
        logging.info(f"Settings not found for user {user_id}.")
        return

    resume_text = settings.get("resume_text")
    keywords = settings.get("keywords")
    negative_keywords = settings.get("negative_keywords", [])

    if not resume_text or not keywords:
        await bot.send_message(
            user_id,
            "⚠️ Не могу начать поиск: не задано резюме или ключевые слова. Настрой их в меню!",
        )
        return

    sources = get_active_sources()
    if not sources:
        await bot.send_message(
            user_id,
            "⚠️ Нет активных источников вакансий. Проверь настройки SUPERJOB_API_KEY и TRUDVSEM_ENABLED в .env.",
        )
        return

    source_names = ", ".join(s.source_name for s in sources)
    await bot.send_message(
        user_id,
        f"🔍 Начинаю поиск вакансий ({source_names}). Это может занять пару минут...",
    )

    analyzer = AnalyzerAgent()
    writer = WriterAgent()
    tg_notifier = TelegramNotifier(chat_id=str(user_id))

    try:
        seen_ids = await get_seen_ids(user_id)

        all_vacancies = []
        for source in sources:
            try:
                vacancies = await source.fetch_vacancies(
                    keywords=keywords,
                    negative_keywords=negative_keywords,
                    seen_ids=seen_ids,
                    target_count=50,
                )
                all_vacancies.extend(vacancies)
                logging.info(
                    f"[{user_id}] {source.source_name}: fetched {len(vacancies)} new vacancies"
                )
            except Exception as exc:
                logging.error(
                    f"[{user_id}] {source.source_name} failed: {exc}"
                )

        if not all_vacancies:
            await bot.send_message(
                user_id,
                "🤷‍♂️ По твоим ключам пока нет новых вакансий.",
            )
            return

        found_good = 0

        for vac in all_vacancies:
            logging.info(f"[{user_id}] Analyzing: {vac.title} ({vac.source})")

            analysis = await analyzer.analyze_vacancy(vac.description, resume_text)
            await mark_vacancy_seen(user_id, vac.external_id)

            if analysis.match_score >= 60:
                letter = await writer.generate_letter(
                    vac.description,
                    resume_text,
                    tone_samples=settings.get("tone_samples", ""),
                    preferences=settings.get("preferences", ""),
                )

                await tg_notifier.send_vacancy_alert(
                    title=vac.title,
                    company=vac.company,
                    url=vac.url,
                    score=analysis.match_score,
                    reason=analysis.brief_reason,
                    cover_letter=letter.text,
                )
                found_good += 1

        total_seen = await count_seen_vacancies(user_id)
        await bot.send_message(
            user_id,
            f"✅ Поиск завершен!\n"
            f"Проверено новых вакансий: {len(all_vacancies)}\n"
            f"Подходящих: {found_good}\n"
            f"Всего в истории: {total_seen}",
        )

    except Exception as e:
        err_trace = traceback.format_exc()
        logging.error(f"Search error for {user_id}:\n{err_trace}")
        safe_error = str(e).replace("<", "&lt;").replace(">", "&gt;")
        await bot.send_message(
            user_id,
            f"❌ <b>Произошла ошибка во время поиска.</b>\n\n"
            f"<b>Техническая деталь:</b>\n<code>{safe_error}</code>",
            parse_mode="HTML",
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
    scheduler = AsyncIOScheduler()
    try:
        await init_db()
        await init_seen_db() # Инициализируем таблицу с памятью вакансий
        dp.include_router(router)

        # Теперь планировщик вызывает функцию, которая обрабатывает ВСЕХ друзей
        scheduler.add_job(scheduled_search_for_all, "interval", hours=4)
        scheduler.start()

        logging.info("Бот успешно запущен и ждет команд!")
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except TelegramNetworkError as exc:
        logging.error(
            "Не удалось подключиться к Telegram API. "
            "Проверь интернет/DNS/VPN/proxy и доступность api.telegram.org: %s",
            exc,
        )
        raise
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
