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
