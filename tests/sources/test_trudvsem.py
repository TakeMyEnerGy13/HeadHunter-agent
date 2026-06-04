import pytest
import httpx

from app.sources.trudvsem import TrudvsemClient, BASE_URL


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
        keywords=["python"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )
    vac_cpp = [v for v in results if "C++" in v.title][0]
    assert vac_cpp.salary is None


@pytest.mark.asyncio
async def test_fetch_merges_and_dedupes_across_keywords(client, httpx_mock):
    resp_python = {
        "status": "200",
        "meta": {"total": 1, "limit": 100},
        "results": {
            "vacancies": [
                {
                    "vacancy": {
                        "id": "p1",
                        "job-name": "Python Dev",
                        "company": {"name": "A"},
                        "vac_url": "u1",
                        "salary_min": 0,
                        "salary_max": 0,
                    }
                }
            ]
        },
    }
    resp_ai = {
        "status": "200",
        "meta": {"total": 2, "limit": 100},
        "results": {
            "vacancies": [
                {
                    "vacancy": {
                        "id": "p1",
                        "job-name": "Python Dev",
                        "company": {"name": "A"},
                        "vac_url": "u1",
                        "salary_min": 0,
                        "salary_max": 0,
                    }
                },
                {
                    "vacancy": {
                        "id": "x2",
                        "job-name": "AI Engineer",
                        "company": {"name": "B"},
                        "vac_url": "u2",
                        "salary_min": 0,
                        "salary_max": 0,
                    }
                },
            ]
        },
    }
    httpx_mock.add_response(
        url=httpx.URL(BASE_URL, params={"text": "python", "offset": 0, "limit": 100}),
        json=resp_python,
    )
    httpx_mock.add_response(
        url=httpx.URL(BASE_URL, params={"text": "ai", "offset": 0, "limit": 100}),
        json=resp_ai,
    )

    results = await client.fetch_vacancies(
        keywords=["python", "ai"],
        negative_keywords=[],
        seen_ids=set(),
        target_count=50,
    )

    assert [v.external_id for v in results] == ["trudvsem:p1", "trudvsem:x2"]
