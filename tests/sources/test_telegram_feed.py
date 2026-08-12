import asyncio
import sqlite3

from app.sources.models import JobPost
from app.sources import telegram_feed


def test_normalize_channels_accepts_supported_forms_and_deduplicates():
    assert hasattr(telegram_feed, "normalize_channels")
    assert telegram_feed.normalize_channels(
        "@ai_engineer_jobs, https://t.me/ai_engineer_jobs, other_jobs, https://example.com/x"
    ) == ["ai_engineer_jobs", "other_jobs"]


def test_normalize_channels_returns_empty_for_only_invalid_entries():
    assert hasattr(telegram_feed, "normalize_channels")
    assert telegram_feed.normalize_channels("https://example.com/jobs, @bad!") == []


def test_filters_require_any_include_and_reject_negative_match():
    assert telegram_feed._matches_filters("Python LLM role", ["go", "python"], ["senior"])
    assert not telegram_feed._matches_filters("Python Senior role", ["python"], ["senior"])


def test_saved_posts_are_scoped_to_owner(tmp_path):
    post = JobPost("telegram", "ai_engineer_jobs", 1, "", "Python role", "", "Python role", "hash")

    async def scenario():
        db_path = str(tmp_path / "posts.sqlite")
        assert await telegram_feed.save_post(101, post, db_path)
        assert await telegram_feed.get_recent_posts(101, db_path)
        assert await telegram_feed.get_recent_posts(202, db_path) == []

    asyncio.run(scenario())


def test_source_db_migrates_existing_posts_to_legacy_owner(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute(
            """
            CREATE TABLE source_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                channel TEXT NOT NULL,
                message_id INTEGER NOT NULL,
                posted_at TEXT,
                title TEXT,
                text TEXT NOT NULL,
                url TEXT,
                text_hash TEXT NOT NULL,
                is_processed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, channel, message_id)
            )
            """
        )
        db.execute(
            "INSERT INTO source_posts (source, channel, message_id, text, text_hash) VALUES (?, ?, ?, ?, ?)",
            ("telegram", "legacy_jobs", 1, "Legacy Python role", "legacy-hash"),
        )

    async def scenario():
        await telegram_feed.init_source_db(str(db_path))
        posts = await telegram_feed.get_recent_posts(0, str(db_path))
        assert [post.channel for post in posts] == ["legacy_jobs"]

    asyncio.run(scenario())
