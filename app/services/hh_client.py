from __future__ import annotations

from typing import Any, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import BASE_URL, DEFAULT_HEADERS


class Employer(BaseModel):
    name: str


class Snippet(BaseModel):
    requirement: Optional[str] = None
    responsibility: Optional[str] = None


class Vacancy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    employer: Optional[Employer] = None
    url: Optional[str] = Field(default=None, alias="alternate_url")
    snippet: Optional[Snippet] = None

    def to_text(self) -> str:
        parts: list[str] = [self.name]
        if self.employer and self.employer.name:
            parts.append(f"Компания: {self.employer.name}")
        if self.snippet:
            if self.snippet.responsibility:
                parts.append(f"Обязанности: {self.snippet.responsibility}")
            if self.snippet.requirement:
                parts.append(f"Требования: {self.snippet.requirement}")
        if self.url:
            parts.append(f"Ссылка: {self.url}")
        return "\n".join(parts).strip()


class HHClientError(Exception):
    """Базовое исключение клиента HH."""


class HHClient:
    def __init__(self, base_url: str = BASE_URL, headers: dict[str, str] | None = None) -> None:
        self.base_url = base_url
        self.headers = headers or DEFAULT_HEADERS

    async def fetch_vacancies(self, keywords: list[str], max_pages: int = 1):
        """Ищет вакансии по списку ключевых слов."""
        all_vacancies = []

        # Объединяем ключевые слова в один OR-запрос для HH API
        # Если передали ["Python", "FastAPI"], получится: '"Python" OR "FastAPI"'
        if not keywords:
            return []  # Если ключей нет, не ищем

        query_str = " OR ".join([f'"{kw}"' for kw in keywords])

        async with httpx.AsyncClient(headers=self.headers, timeout=15.0) as client:
            for page in range(max_pages):
                params = {
                    "text": query_str,
                    "page": page,
                }
                try:
                    response = await client.get(self.base_url, params=params)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise HHClientError(f"Ошибка сети при запросе к HH: {exc}") from exc

                try:
                    data: dict[str, Any] = response.json()
                except ValueError as exc:
                    raise HHClientError("Не удалось распарсить JSON-ответ HH") from exc

                items = data.get("items", [])
                for raw in items:
                    try:
                        all_vacancies.append(Vacancy.model_validate(raw))
                    except ValidationError:
                        continue

        unique_by_id: dict[str, Vacancy] = {vac.id: vac for vac in all_vacancies}
        return list(unique_by_id.values())
