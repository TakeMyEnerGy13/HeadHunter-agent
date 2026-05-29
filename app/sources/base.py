from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel


class UnifiedVacancy(BaseModel):
    source: str
    external_id: str
    title: str
    company: str
    url: str
    description: str
    salary: Optional[str] = None


class JobSource(ABC):
    source_name: str

    @abstractmethod
    async def fetch_vacancies(
        self,
        keywords: list[str],
        negative_keywords: list[str],
        seen_ids: set[str],
        target_count: int = 50,
    ) -> list[UnifiedVacancy]: ...


def contains_excluded_keyword(vacancy: UnifiedVacancy, excluded_keywords: list[str]) -> bool:
    if not excluded_keywords:
        return False
    text = f"{vacancy.title} {vacancy.description}".lower()
    return any(kw in text for kw in excluded_keywords)
