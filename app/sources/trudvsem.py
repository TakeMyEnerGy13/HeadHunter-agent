from __future__ import annotations

import asyncio
import logging

import httpx

from app.sources.base import JobSource, UnifiedVacancy, contains_excluded_keyword

logger = logging.getLogger(__name__)

BASE_URL = "http://opendata.trudvsem.ru/api/v1/vacancies"
PAGE_LIMIT = 100
MAX_PAGES = 10
THROTTLE_SECONDS = 1.0


def _format_salary(salary_min: int, salary_max: int) -> str | None:
    if not salary_min and not salary_max:
        return None
    parts: list[str] = []
    if salary_min:
        parts.append(f"{salary_min:,.0f}".replace(",", " "))
    if salary_max:
        parts.append(f"{salary_max:,.0f}".replace(",", " "))
    return " - ".join(parts) + " ₽"


def _parse_vacancy(raw: dict) -> UnifiedVacancy | None:
    vac = raw.get("vacancy")
    if not vac:
        return None

    vac_id = vac.get("id", "")
    title = vac.get("job-name", "")
    if not vac_id or not title:
        return None

    company_block = vac.get("company") or {}
    company = company_block.get("name", "")

    duty = (vac.get("duty") or "").strip()
    requirements = (vac.get("requirements") or "").strip()
    description_parts = []
    if duty:
        description_parts.append(f"Обязанности: {duty}")
    if requirements:
        description_parts.append(f"Требования: {requirements}")
    description = "\n".join(description_parts) or title

    salary = _format_salary(
        int(vac.get("salary_min") or 0),
        int(vac.get("salary_max") or 0),
    )

    return UnifiedVacancy(
        source="trudvsem",
        external_id=f"trudvsem:{vac_id}",
        title=title,
        company=company,
        url=vac.get("vac_url", ""),
        description=description,
        salary=salary,
    )


class TrudvsemClient(JobSource):
    source_name = "trudvsem"

    async def fetch_vacancies(
        self,
        keywords: list[str],
        negative_keywords: list[str],
        seen_ids: set[str],
        target_count: int = 50,
    ) -> list[UnifiedVacancy]:
        query = " ".join(keywords)
        normalized_negative = [kw.lower() for kw in negative_keywords if kw.strip()]
        collected: list[UnifiedVacancy] = []
        offset = 0

        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(MAX_PAGES):
                if len(collected) >= target_count:
                    break

                params = {"text": query, "offset": offset, "limit": PAGE_LIMIT}
                try:
                    resp = await client.get(BASE_URL, params=params)
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("Trudvsem API error: %s", exc)
                    return collected

                vacancies_raw = (
                    (data.get("results") or {}).get("vacancies") or []
                )
                if not vacancies_raw:
                    break

                for item in vacancies_raw:
                    if len(collected) >= target_count:
                        break
                    vac = _parse_vacancy(item)
                    if vac is None:
                        continue
                    if vac.external_id in seen_ids:
                        continue
                    if contains_excluded_keyword(vac, normalized_negative):
                        continue
                    collected.append(vac)

                if len(vacancies_raw) < PAGE_LIMIT:
                    break

                offset += PAGE_LIMIT
                await asyncio.sleep(THROTTLE_SECONDS)

        return collected
