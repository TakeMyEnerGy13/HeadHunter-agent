from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests
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
    def __init__(self, base_url: str = BASE_URL, headers: Dict[str, str] | None = None) -> None:
        self.base_url = base_url
        self.headers = headers or DEFAULT_HEADERS

    def get_vacancies(self, query: str) -> List[Vacancy]:
        params = {"text": query}

        try:
            response = requests.get(self.base_url, headers=self.headers, params=params, timeout=10)
        except requests.RequestException as exc:
            raise HHClientError(f"Ошибка сети при запросе к HH: {exc}") from exc

        if not response.ok:
            raise HHClientError(
                f"Некорректный ответ от HH: {response.status_code} {response.text}"
            )

        try:
            data: Dict[str, Any] = response.json()
        except ValueError as exc:
            raise HHClientError("Не удалось распарсить JSON-ответ HH") from exc

        items = data.get("items", [])

        vacancies: List[Vacancy] = []
        for raw in items:
            try:
                vacancies.append(Vacancy.model_validate(raw))
            except ValidationError:
                # Игнорируем некорректные записи на этом базовом этапе
                continue

        return vacancies

