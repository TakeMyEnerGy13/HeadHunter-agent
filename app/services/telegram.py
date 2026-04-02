import httpx
from config import TG_BOT_TOKEN, TG_CHAT_ID


class TelegramNotifier:
    def __init__(self, bot_token: str = TG_BOT_TOKEN, chat_id: str = TG_CHAT_ID):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

    async def send_vacancy_alert(
        self,
        title: str,
        company: str,
        url: str,
        score: int,
        reason: str,
        cover_letter: str,
    ):
        """Отправляет красивое сообщение с вакансией в Telegram."""

        # Формируем текст сообщения с использованием HTML-разметки
        message_text = (
            f"🎯 <b>Новая подходящая вакансия!</b>\n\n"
            f"💼 <b>Название:</b> <a href='{url}'>{title}</a>\n"
            f"🏢 <b>Компания:</b> {company}\n"
            f"⚡ <b>Совпадение:</b> {score}/100\n\n"
            f"🤖 <b>Вердикт ИИ:</b>\n<i>{reason}</i>\n\n"
            f"📝 <b>Готовое письмо:</b>\n<code>{cover_letter}</code>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": message_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,  # Чтобы превью ссылок не засоряло чат
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                print(f"[TG ERROR] Ошибка отправки в Telegram: {exc.response.text}")
            except Exception as exc:
                print(f"[TG ERROR] Неожиданная ошибка: {exc}")
