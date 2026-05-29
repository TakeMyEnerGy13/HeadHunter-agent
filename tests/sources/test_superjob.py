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
