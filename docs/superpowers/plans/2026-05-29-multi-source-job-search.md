# Multi-Source Job Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken HH API with pluggable SuperJob + Trudvsem job sources behind a common `JobSource` interface.

**Architecture:** Abstract `JobSource` base class in `app/sources/base.py` with `UnifiedVacancy` model. Two concrete clients (`SuperJobClient`, `TrudvsemClient`) implement `fetch_vacancies()`. A registry factory returns enabled sources based on env config. `run_search_job` in `main_bot.py` iterates over active sources and feeds `UnifiedVacancy` objects into the existing LLM pipeline.

**Tech Stack:** Python 3, httpx (async HTTP), pydantic (models), aiosqlite (seen vacancies), pytest (tests)

**Spec:** `docs/superpowers/specs/2026-05-29-multi-source-job-search-design.md`

---

### Task 1: UnifiedVacancy model + JobSource ABC

**Files:**
- Create: `app/sources/base.py`
- Create: `tests/sources/test_base.py`

- [ ] **Step 1: Create test directory and test file with basic model tests**

Create `tests/__init__.py`, `tests/sources/__init__.py`, and `tests/sources/test_base.py`:

```python
# tests/__init__.py
# (empty)

# tests/sources/__init__.py
# (empty)

# tests/sources/test_base.py
import pytest
from pydantic import ValidationError


def test_unified_vacancy_valid():
    from app.sources.base import UnifiedVacancy

    vac = UnifiedVacancy(
        source="superjob",
        external_id="superjob:123",
        title="Python Developer",
        company="Acme Corp",
        url="https://superjob.ru/vacancy/123",
        description="We need a Python dev with Django experience.",
        salary="from 200 000 rub",
    )
    assert vac.source == "superjob"
    assert vac.external_id == "superjob:123"
    assert vac.salary == "from 200 000 rub"


def test_unified_vacancy_salary_optional():
    from app.sources.base import UnifiedVacancy

    vac = UnifiedVacancy(
        source="trudvsem",
        external_id="trudvsem:abc",
        title="Analyst",
        company="Gov Inc",
        url="https://trudvsem.ru/vacancy/abc",
        description="Duty text here.",
    )
    assert vac.salary is None


def test_unified_vacancy_missing_required_field():
    from app.sources.base import UnifiedVacancy

    with pytest.raises(ValidationError):
        UnifiedVacancy(
            source="superjob",
            external_id="superjob:1",
            # title is missing
            company="X",
            url="https://example.com",
            description="text",
        )


def test_job_source_is_abstract():
    from app.sources.base import JobSource

    with pytest.raises(TypeError):
        JobSource()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_base.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.sources.base'` (file doesn't exist yet)

- [ ] **Step 3: Implement UnifiedVacancy and JobSource**

Create `app/sources/base.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_base.py -v`

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add app/sources/base.py tests/__init__.py tests/sources/__init__.py tests/sources/test_base.py
git commit -m "feat: add UnifiedVacancy model and JobSource ABC"
```

---

### Task 2: Negative keyword filtering helper

Both clients need the same negative keyword filtering. Extract it into `base.py` to avoid duplication.

**Files:**
- Modify: `app/sources/base.py`
- Create: `tests/sources/test_filtering.py`

- [ ] **Step 1: Write failing tests for the helper**

Create `tests/sources/test_filtering.py`:

```python
from app.sources.base import UnifiedVacancy, contains_excluded_keyword


def _make_vacancy(title: str = "Dev", description: str = "Build things") -> UnifiedVacancy:
    return UnifiedVacancy(
        source="test",
        external_id="test:1",
        title=title,
        company="Co",
        url="https://example.com",
        description=description,
    )


def test_no_excluded_keywords():
    vac = _make_vacancy()
    assert contains_excluded_keyword(vac, []) is False


def test_excluded_keyword_in_title():
    vac = _make_vacancy(title="Senior Python Developer")
    assert contains_excluded_keyword(vac, ["senior"]) is True


def test_excluded_keyword_in_description():
    vac = _make_vacancy(description="Looking for a C++ guru")
    assert contains_excluded_keyword(vac, ["c++"]) is True


def test_excluded_keyword_case_insensitive():
    vac = _make_vacancy(title="TEAM LEAD position")
    assert contains_excluded_keyword(vac, ["team lead"]) is True


def test_excluded_keyword_no_match():
    vac = _make_vacancy(title="Junior Python Dev", description="Flask, Django")
    assert contains_excluded_keyword(vac, ["senior", "c++"]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_filtering.py -v`

Expected: FAIL — `ImportError: cannot import name 'contains_excluded_keyword'`

- [ ] **Step 3: Implement the helper in base.py**

Add to `app/sources/base.py` after the `JobSource` class:

```python
def contains_excluded_keyword(vacancy: UnifiedVacancy, excluded_keywords: list[str]) -> bool:
    if not excluded_keywords:
        return False
    text = f"{vacancy.title} {vacancy.description}".lower()
    return any(kw in text for kw in excluded_keywords)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_filtering.py -v`

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add app/sources/base.py tests/sources/test_filtering.py
git commit -m "feat: add contains_excluded_keyword helper"
```

---

### Task 3: TrudvsemClient

Trudvsem is simpler (no auth) so we implement it first.

**API reference (verified):**
- GET `http://opendata.trudvsem.ru/api/v1/vacancies`
- Params: `text`, `offset` (0-based), `limit` (max 100)
- Response: `{"results": {"vacancies": [{"vacancy": {...}}]}, "meta": {"total": N, "limit": N}}`
- Vacancy fields: `id`, `job-name`, `duty`, `requirements`, `salary_min`, `salary_max`, `salary`, `company.name`, `vac_url`, `region.name`

**Files:**
- Create: `app/sources/trudvsem.py`
- Create: `tests/sources/test_trudvsem.py`

- [ ] **Step 1: Write tests with mocked HTTP responses**

Create `tests/sources/test_trudvsem.py`:

```python
import pytest
import httpx

from app.sources.trudvsem import TrudvsemClient


SAMPLE_RESPONSE = {
    "status": "200",
    "meta": {"total": 2, "limit": 100},
    "results": {
        "vacancies": [
            {
                "vacancy": {
                    "id": "aaa-bbb-111",
                    "job-name": "Python Developer",
                    "duty": "Develop backend services",
                    "requirements": "3+ years Python experience",
                    "salary_min": 150000,
                    "salary_max": 250000,
                    "company": {"name": "TechCorp"},
                    "vac_url": "https://trudvsem.ru/vacancy/aaa-bbb-111",
                    "region": {"name": "Moscow"},
                }
            },
            {
                "vacancy": {
                    "id": "ccc-ddd-222",
                    "job-name": "Senior C++ Engineer",
                    "duty": "Low-level optimization",
                    "requirements": "5+ years C++",
                    "salary_min": 0,
                    "salary_max": 0,
                    "company": {"name": "SystemsInc"},
                    "vac_url": "https://trudvsem.ru/vacancy/ccc-ddd-222",
                    "region": {"name": "SPb"},
                }
            },
        ]
    },
}

EMPTY_RESPONSE = {
    "status": "200",
    "meta": {"total": 0, "limit": 100},
    "results": {"vacancies": []},
}


@pytest.fixture
def client():
    return TrudvsemClient()


def test_source_name(client):
    assert client.source_name == "trudvsem"


@pytest.mark.asyncio
async def test_fetch_maps_fields(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    assert len(results) == 2

    vac = results[0]
    assert vac.source == "trudvsem"
    assert vac.external_id == "trudvsem:aaa-bbb-111"
    assert vac.title == "Python Developer"
    assert vac.company == "TechCorp"
    assert vac.url == "https://trudvsem.ru/vacancy/aaa-bbb-111"
    assert "Develop backend services" in vac.description
    assert "3+ years Python experience" in vac.description
    assert vac.salary == "150 000 - 250 000 ₽"


@pytest.mark.asyncio
async def test_fetch_filters_negative_keywords(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=["c++"],
        seen_ids=set(),
        target_count=50,
    )
    assert len(results) == 1
    assert results[0].title == "Python Developer"


@pytest.mark.asyncio
async def test_fetch_skips_seen_ids(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=[],
        seen_ids={"trudvsem:aaa-bbb-111"},
        target_count=50,
    )
    assert len(results) == 1
    assert results[0].external_id == "trudvsem:ccc-ddd-222"


@pytest.mark.asyncio
async def test_fetch_empty_response(client, httpx_mock):
    httpx_mock.add_response(json=EMPTY_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["rust"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    assert results == []


@pytest.mark.asyncio
async def test_fetch_handles_api_error(client, httpx_mock):
    httpx_mock.add_response(status_code=500, text="Internal Server Error")

    results = await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    assert results == []


@pytest.mark.asyncio
async def test_salary_zero_means_none(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=[],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    vac_cpp = [v for v in results if "C++" in v.title][0]
    assert vac_cpp.salary is None
```

- [ ] **Step 2: Install test dependencies and run tests to verify they fail**

Run:
```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
pip install pytest pytest-asyncio pytest-httpx
python -m pytest tests/sources/test_trudvsem.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.sources.trudvsem'`

- [ ] **Step 3: Implement TrudvsemClient**

Create `app/sources/trudvsem.py`:

```python
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
                    data.get("results", {}).get("vacancies") or []
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_trudvsem.py -v`

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add app/sources/trudvsem.py tests/sources/test_trudvsem.py
git commit -m "feat: add TrudvsemClient job source"
```

---

### Task 4: SuperJobClient

**API reference (verified):**
- GET `https://api.superjob.ru/2.0/vacancies/`
- Auth: `X-Api-App-Id: {secret_key}` header
- Params: `keyword`, `count` (max 100), `page` (0-based), `order_field=date`, `order_direction=desc`
- Response: `{"objects": [...], "total": N, "more": bool}`
- Vacancy fields: `id`, `profession`, `firm_name`, `payment_from`, `payment_to`, `candidat`, `work`, `link`, `town.title`, `currency`

**Files:**
- Create: `app/sources/superjob.py`
- Create: `tests/sources/test_superjob.py`

- [ ] **Step 1: Write tests with mocked HTTP responses**

Create `tests/sources/test_superjob.py`:

```python
import pytest

from app.sources.superjob import SuperJobClient


SAMPLE_RESPONSE = {
    "objects": [
        {
            "id": 12345,
            "profession": "Python Developer",
            "firm_name": "Acme Corp",
            "payment_from": 200000,
            "payment_to": 350000,
            "currency": "rub",
            "candidat": "Experience with Django, REST APIs, PostgreSQL.",
            "work": "Developing backend microservices.",
            "link": "https://www.superjob.ru/vakansii/python-developer-12345.html",
            "town": {"title": "Moscow"},
        },
        {
            "id": 67890,
            "profession": "Senior C++ Developer",
            "firm_name": "GameStudio",
            "payment_from": 0,
            "payment_to": 0,
            "currency": "rub",
            "candidat": "5+ years C++ and Unreal Engine.",
            "work": "Game engine optimization.",
            "link": "https://www.superjob.ru/vakansii/cpp-dev-67890.html",
            "town": {"title": "SPb"},
        },
    ],
    "total": 2,
    "more": False,
}

EMPTY_RESPONSE = {"objects": [], "total": 0, "more": False}


@pytest.fixture
def client():
    return SuperJobClient(api_key="test-secret-key")


def test_source_name(client):
    assert client.source_name == "superjob"


@pytest.mark.asyncio
async def test_fetch_maps_fields(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    assert len(results) == 2

    vac = results[0]
    assert vac.source == "superjob"
    assert vac.external_id == "superjob:12345"
    assert vac.title == "Python Developer"
    assert vac.company == "Acme Corp"
    assert vac.url == "https://www.superjob.ru/vakansii/python-developer-12345.html"
    assert "Django" in vac.description
    assert "microservices" in vac.description
    assert vac.salary == "200 000 - 350 000 ₽"


@pytest.mark.asyncio
async def test_fetch_filters_negative_keywords(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["developer"],
        negative_keywords=["c++"],
        seen_ids=set(),
        target_count=50,
    )
    assert len(results) == 1
    assert results[0].title == "Python Developer"


@pytest.mark.asyncio
async def test_fetch_skips_seen_ids(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["developer"],
        negative_keywords=[],
        seen_ids={"superjob:12345"},
        target_count=50,
    )
    assert len(results) == 1
    assert results[0].external_id == "superjob:67890"


@pytest.mark.asyncio
async def test_fetch_empty_response(client, httpx_mock):
    httpx_mock.add_response(json=EMPTY_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=["rust"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    assert results == []


@pytest.mark.asyncio
async def test_fetch_handles_api_error(client, httpx_mock):
    httpx_mock.add_response(status_code=500, text="Internal Server Error")

    results = await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    assert results == []


@pytest.mark.asyncio
async def test_salary_zero_means_none(client, httpx_mock):
    httpx_mock.add_response(json=SAMPLE_RESPONSE)

    results = await client.fetch_vacancies(
        keywords=[],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    vac_cpp = [v for v in results if "C++" in v.title][0]
    assert vac_cpp.salary is None


@pytest.mark.asyncio
async def test_auth_header_sent(client, httpx_mock):
    httpx_mock.add_response(json=EMPTY_RESPONSE)

    await client.fetch_vacancies(
        keywords=["python"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    request = httpx_mock.get_request()
    assert request.headers["X-Api-App-Id"] == "test-secret-key"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_superjob.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.sources.superjob'`

- [ ] **Step 3: Implement SuperJobClient**

Create `app/sources/superjob.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_superjob.py -v`

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add app/sources/superjob.py tests/sources/test_superjob.py
git commit -m "feat: add SuperJobClient job source"
```

---

### Task 5: Source registry + config

A factory function that returns enabled sources based on env config.

**Files:**
- Create: `app/sources/registry.py`
- Modify: `config.py` — add `SUPERJOB_API_KEY`, `TRUDVSEM_ENABLED`
- Modify: `.env.example` — add new vars
- Create: `tests/sources/test_registry.py`

- [ ] **Step 1: Write tests for the registry**

Create `tests/sources/test_registry.py`:

```python
from unittest.mock import patch

from app.sources.registry import get_active_sources
from app.sources.superjob import SuperJobClient
from app.sources.trudvsem import TrudvsemClient


def test_both_enabled():
    with patch("app.sources.registry.SUPERJOB_API_KEY", "sk-test"), \
         patch("app.sources.registry.TRUDVSEM_ENABLED", "1"):
        sources = get_active_sources()
    names = [s.source_name for s in sources]
    assert "superjob" in names
    assert "trudvsem" in names


def test_superjob_disabled_when_no_key():
    with patch("app.sources.registry.SUPERJOB_API_KEY", ""), \
         patch("app.sources.registry.TRUDVSEM_ENABLED", "1"):
        sources = get_active_sources()
    names = [s.source_name for s in sources]
    assert "superjob" not in names
    assert "trudvsem" in names


def test_trudvsem_disabled():
    with patch("app.sources.registry.SUPERJOB_API_KEY", "sk-test"), \
         patch("app.sources.registry.TRUDVSEM_ENABLED", "0"):
        sources = get_active_sources()
    names = [s.source_name for s in sources]
    assert "superjob" in names
    assert "trudvsem" not in names


def test_all_disabled():
    with patch("app.sources.registry.SUPERJOB_API_KEY", ""), \
         patch("app.sources.registry.TRUDVSEM_ENABLED", "0"):
        sources = get_active_sources()
    assert sources == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_registry.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.sources.registry'`

- [ ] **Step 3: Add config variables**

Add to the end of `config.py` (before the closing newline):

```python
SUPERJOB_API_KEY = os.getenv("SUPERJOB_API_KEY", "")
TRUDVSEM_ENABLED = os.getenv("TRUDVSEM_ENABLED", "1")
```

Add to `.env.example`:

```
# --- Job Sources ---
SUPERJOB_API_KEY=          # Secret key from api.superjob.ru/register
TRUDVSEM_ENABLED=1         # Set to 0 to disable Trudvsem source
```

- [ ] **Step 4: Implement registry**

Create `app/sources/registry.py`:

```python
from __future__ import annotations

import logging

from config import SUPERJOB_API_KEY, TRUDVSEM_ENABLED
from app.sources.base import JobSource
from app.sources.superjob import SuperJobClient
from app.sources.trudvsem import TrudvsemClient

logger = logging.getLogger(__name__)


def get_active_sources() -> list[JobSource]:
    sources: list[JobSource] = []

    if SUPERJOB_API_KEY.strip():
        sources.append(SuperJobClient(api_key=SUPERJOB_API_KEY))
        logger.info("SuperJob source enabled")
    else:
        logger.warning("SuperJob source disabled: SUPERJOB_API_KEY is empty")

    if TRUDVSEM_ENABLED.strip() not in ("0", "false", "no", ""):
        sources.append(TrudvsemClient())
        logger.info("Trudvsem source enabled")
    else:
        logger.info("Trudvsem source disabled by config")

    return sources
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/sources/test_registry.py -v`

Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add app/sources/registry.py config.py .env.example tests/sources/test_registry.py
git commit -m "feat: add source registry with graceful degradation"
```

---

### Task 6: Integrate sources into run_search_job

Replace HHClient usage in `main_bot.py` with the new source registry.

**Files:**
- Modify: `main_bot.py`

- [ ] **Step 1: Add bulk seen_ids loader**

Add a new helper function in `main_bot.py` after the existing `count_seen_vacancies` function (around line 72):

```python
async def get_seen_ids(user_id: int) -> set[str]:
    """Load all seen vacancy IDs for a user as a set (for fast lookup)."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT vacancy_id FROM seen_vacancies WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
```

- [ ] **Step 2: Rewrite run_search_job to use sources**

Replace the entire `run_search_job` function (lines 74–200) with:

```python
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
```

- [ ] **Step 3: Clean up unused imports in main_bot.py**

Remove the `HHClient` import (line 15):

```python
# DELETE this line:
from app.services.hh_client import HHClient
```

The remaining imports (`AnalyzerAgent`, `WriterAgent`, `TelegramNotifier`, `aiosqlite`, `traceback`, etc.) stay as-is.

- [ ] **Step 4: Run all tests to verify nothing is broken**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/ -v`

Expected: All tests pass (base, filtering, trudvsem, superjob, registry)

- [ ] **Step 5: Verify bot starts without crash**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -c "from app.sources.registry import get_active_sources; print([s.source_name for s in get_active_sources()])"`

Expected: Prints list of enabled sources (depends on .env config). No import errors.

- [ ] **Step 6: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add main_bot.py
git commit -m "feat: integrate multi-source search into run_search_job"
```

---

### Task 7: Update .env.example and README

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Update .env.example with all new variables**

Ensure `.env.example` contains a `# --- Job Sources ---` section with:

```
# --- Job Sources ---
# SuperJob: register at https://api.superjob.ru/register to get a key
SUPERJOB_API_KEY=
# Trudvsem (Работа России): free, no key needed. Set to 0 to disable
TRUDVSEM_ENABLED=1
```

- [ ] **Step 2: Add a sources section to README.md**

Add after the existing HH section in README.md:

```markdown
## Источники вакансий

Бот поддерживает несколько источников. Каждый включается/выключается отдельно через `.env`:

| Источник | Требуется | Переменная |
|----------|-----------|------------|
| SuperJob | API key ([регистрация](https://api.superjob.ru/register)) | `SUPERJOB_API_KEY` |
| Trudvsem (Работа России) | Ничего | `TRUDVSEM_ENABLED=1` (по умолчанию вкл) |

Если все источники выключены, бот сообщит об этом при попытке поиска.
```

- [ ] **Step 3: Commit**

```bash
cd C:\Users\Тёма\.cursor\projects\hh_agent
git add .env.example README.md
git commit -m "docs: update env example and README with new job sources"
```

---

### Task 8: Run full test suite and verify

**Files:** none (verification only)

- [ ] **Step 1: Run all tests**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m pytest tests/ -v --tb=short`

Expected: All tests pass:
- `tests/sources/test_base.py` — 4 passed
- `tests/sources/test_filtering.py` — 5 passed
- `tests/sources/test_trudvsem.py` — 7 passed (with httpx_mock)
- `tests/sources/test_superjob.py` — 7 passed (with httpx_mock)
- `tests/sources/test_registry.py` — 4 passed

- [ ] **Step 2: Verify import chain**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -c "from main_bot import run_search_job; print('OK')"`

Expected: `OK` — no import errors

- [ ] **Step 3: Run the existing eval suite (if it still works)**

Run: `cd C:\Users\Тёма\.cursor\projects\hh_agent && python -m app.evals.run --dry-run`

Expected: Dry run passes (validates eval dataset format without LLM calls)
