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
