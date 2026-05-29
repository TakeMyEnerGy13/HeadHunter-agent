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
