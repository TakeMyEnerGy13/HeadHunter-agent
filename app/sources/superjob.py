from __future__ import annotations

import asyncio
import logging

import httpx

from app.sources.base import JobSource, UnifiedVacancy, contains_excluded_keyword

logger = logging.getLogger(__name__)

BASE_URL = "https://api.superjob.ru/2.0/vacancies/"
PAGE_SIZE = 100
MAX_PAGES = 10
THROTTLE_SECONDS = 1.0


def _format_salary(payment_from: int, payment_to: int, currency: str) -> str | None:
    if not payment_from and not payment_to:
        return None
    symbol = "₽" if currency == "rub" else currency
    parts: list[str] = []
    if payment_from:
        parts.append(f"{payment_from:,.0f}".replace(",", " "))
    if payment_to:
        parts.append(f"{payment_to:,.0f}".replace(",", " "))
    return " - ".join(parts) + f" {symbol}"


def _parse_vacancy(raw: dict) -> UnifiedVacancy | None:
    vac_id = raw.get("id")
    title = raw.get("profession", "")
    if not vac_id or not title:
        return None

    candidat = (raw.get("candidat") or "").strip()
    work = (raw.get("work") or "").strip()
    description_parts = []
    if work:
        description_parts.append(f"Обязанности: {work}")
    if candidat:
        description_parts.append(f"Требования: {candidat}")
    description = "\n".join(description_parts) or title

    salary = _format_salary(
        int(raw.get("payment_from") or 0),
        int(raw.get("payment_to") or 0),
        raw.get("currency", "rub"),
    )

    return UnifiedVacancy(
        source="superjob",
        external_id=f"superjob:{vac_id}",
        title=title,
        company=raw.get("firm_name", ""),
        url=raw.get("link", ""),
        description=description,
        salary=salary,
    )


class SuperJobClient(JobSource):
    source_name = "superjob"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def fetch_vacancies(
        self,
        keywords: list[str],
        negative_keywords: list[str],
        seen_ids: set[str],
        target_count: int = 50,
    ) -> list[UnifiedVacancy]:
        keyword = " ".join(keywords)
        normalized_negative = [kw.lower() for kw in negative_keywords if kw.strip()]
        collected: list[UnifiedVacancy] = []

        headers = {"X-Api-App-Id": self.api_key}

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            for page in range(MAX_PAGES):
                if len(collected) >= target_count:
                    break

                params = {
                    "keyword": keyword,
                    "count": PAGE_SIZE,
                    "page": page,
                    "order_field": "date",
                    "order_direction": "desc",
                }
                try:
                    resp = await client.get(BASE_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("SuperJob API error: %s", exc)
                    return collected

                objects = data.get("objects") or []
                if not objects:
                    break

                for raw in objects:
                    if len(collected) >= target_count:
                        break
                    vac = _parse_vacancy(raw)
                    if vac is None:
                        continue
                    if vac.external_id in seen_ids:
                        continue
                    if contains_excluded_keyword(vac, normalized_negative):
                        continue
                    collected.append(vac)

                if not data.get("more", False):
                    break

                if page < MAX_PAGES - 1:
                    await asyncio.sleep(THROTTLE_SECONDS)

        return collected
