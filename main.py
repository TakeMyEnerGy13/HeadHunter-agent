import asyncio

from app.agents.analyzer import AnalyzerAgent
from app.agents.writer import WriterAgent
from app.services.telegram import TelegramNotifier
from hh_client import HHClient, HHClientError

MY_RESUME = (
    "Junior/Middle AI Engineer. Знаю Python, Cursor, пишу промпты, "
    "разбираюсь в API нейросетей и базово в FastAPI."
)


async def main() -> None:
    client = HHClient()

    query = "AI Architect"
    try:
        vacancies = client.get_vacancies(query)
    except HHClientError as exc:
        print(f"Не удалось получить вакансии: {exc}")
        return

    print(f'По запросу "{query}" найдено вакансий: {len(vacancies)}')
    if not vacancies:
        print("Вакансии для анализа не найдены.")
        return

    analyzer = AnalyzerAgent()
    writer = WriterAgent()
    tg_notifier = TelegramNotifier()

    for i, vac in enumerate(vacancies, 1):
        print(f"\n[{i}/{len(vacancies)}] Анализируем: {vac.name}")

        try:
            # 1. Анализ
            analysis = await analyzer.analyze_vacancy(vac.to_text(), MY_RESUME)
            print(f"   Оценка: {analysis.match_score} | Вердикт: {analysis.brief_reason}")

            # 2. Фильтр и генерация письма
            if analysis.match_score >= 70:
                print("   [!] Подходит! Пишем письмо...")
                letter = await writer.generate_letter(vac.to_text(), MY_RESUME)

                # 3. ОТПРАВКА В TELEGRAM (Сразу!)
                await tg_notifier.send_vacancy_alert(
                    title=vac.name,
                    company=vac.employer.name if vac.employer else "",
                    url=vac.url or "",
                    score=analysis.match_score,
                    reason=analysis.brief_reason,
                    cover_letter=letter.text,
                )
                print("   [TG] Отправлено в Telegram!")

        except Exception as exc:
            print(f"   [ОШИБКА] Не удалось обработать вакансию: {exc}")

    print("\n✅ Поиск завершен!")


if __name__ == "__main__":
    asyncio.run(main())

