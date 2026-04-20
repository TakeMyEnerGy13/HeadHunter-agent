from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
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

    @staticmethod
    def _format_http_error(response: httpx.Response) -> str:
        header_request_ids = response.headers.get_list("X-Request-ID")
        if not header_request_ids:
            header_request_ids = response.headers.get_list("X-Request-Id")
        request_id = next((value.strip() for value in header_request_ids if value and value.strip()), None)
        content_type = response.headers.get("Content-Type", "")
        details: list[str] = [f"HTTP {response.status_code}", f"url='{response.request.url}'"]

        if request_id:
            details.append(f"request_id='{request_id}'")

        if "application/json" in content_type.lower():
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                errors = payload.get("errors")
                body_request_id = payload.get("request_id")
                if errors:
                    details.append(f"errors={json.dumps(errors, ensure_ascii=False)}")
                if body_request_id and body_request_id != request_id:
                    details.append(f"body_request_id='{body_request_id}'")
            elif response.text:
                details.append(f"body='{response.text[:300]}'")
        elif response.text:
            details.append(f"body='{response.text[:300]}'")

        return ", ".join(details)

    async def _get_vacancies_page(
        self, client: httpx.AsyncClient, query_str: str, page: int, extra_params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "text": query_str,
            "page": page,
            "per_page": 100,
        }
        if extra_params:
            params.update(extra_params)
        try:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            message = self._format_http_error(exc.response)
            raise HHClientError(f"Ошибка HH API: {message}") from exc
        except httpx.HTTPError as exc:
            raise HHClientError(f"Ошибка сети при запросе к HH: {exc}") from exc

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise HHClientError("Не удалось распарсить JSON-ответ HH") from exc

        return data.get("items", [])

    async def fetch_vacancies(
        self,
        keywords: list[str],
        negative_keywords: list[str] | None = None,
        max_pages: int = 1,
        *,
        target_new_count: int | None = None,
        is_already_seen: Callable[[str], Awaitable[bool]] | None = None,
        max_api_pages: int = 20,
    ):
        """Ищет вакансии по списку ключевых слов.

        Без target_new_count — как раньше: до max_pages страниц, все подходящие по API.

        С target_new_count — листает страницы (до max_api_pages), пока не наберёт
        заданное число вакансий, для которых is_already_seen(vacancy_id) == False.
        Свежие сверху: order_by=publication_time.
        """
        if not keywords:
            return []

        query_str = " OR ".join([f'"{kw}"' for kw in keywords])

        normalized_negative = [kw.lower() for kw in (negative_keywords or []) if kw.strip()]

        async with httpx.AsyncClient(headers=self.headers, timeout=15.0) as client:
            if target_new_count is None:
                all_vacancies: list[Vacancy] = []
                for page in range(max_pages):
                    items = await self._get_vacancies_page(client, query_str, page)
                    for raw in items:
                        try:
                            vac = Vacancy.model_validate(raw)
                        except ValidationError:
                            continue
                        if self._contains_excluded_keyword(vac, normalized_negative):
                            continue
                        all_vacancies.append(vac)

                unique_by_id: dict[str, Vacancy] = {vac.id: vac for vac in all_vacancies}
                return list(unique_by_id.values())

            if is_already_seen is None:
                raise ValueError("is_already_seen обязателен, если задан target_new_count")

            new_vacancies: list[Vacancy] = []
            seen_in_result: set[str] = set()
            page = 0
            extra = {"order_by": "publication_time"}

            while len(new_vacancies) < target_new_count and page < max_api_pages:
                items = await self._get_vacancies_page(client, query_str, page, extra)
                if not items:
                    break

                for raw in items:
                    if len(new_vacancies) >= target_new_count:
                        break
                    try:
                        vac = Vacancy.model_validate(raw)
                    except ValidationError:
                        continue
                    if self._contains_excluded_keyword(vac, normalized_negative):
                        continue
                    if vac.id in seen_in_result:
                        continue
                    if await is_already_seen(vac.id):
                        continue
                    seen_in_result.add(vac.id)
                    new_vacancies.append(vac)

                page += 1
                await asyncio.sleep(1)

            return new_vacancies

    @staticmethod
    def _contains_excluded_keyword(vacancy: Vacancy, excluded_keywords: list[str]) -> bool:
        if not excluded_keywords:
            return False

        searchable_text = vacancy.to_text().lower()
        return any(keyword in searchable_text for keyword in excluded_keywords)
