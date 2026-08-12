# Personal Telegram Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every bot user configure personal public Telegram channels while reusing that user's existing HeadHunter include and exclude keywords during scans.

**Architecture:** Add a JSON `tg_channels` field to the existing user-settings record and manage it from the Telegram-source menu. Make source-post ownership explicit with `user_id`, migrating the existing SQLite table to an owner-aware unique key. The bot passes the requesting user's channel list and existing keyword lists into the reader; HH search code remains untouched.

**Tech Stack:** Python 3, aiogram 3, aiosqlite, SQLite, Telethon, pytest.

## Global Constraints

- Do not change HeadHunter search filtering or add separate Telegram keyword profiles.
- Treat existing `keywords` as OR and `negative_keywords` as a rejection list for the same user.
- Accept only public Telegram usernames in `@username`, `username`, or `https://t.me/username` form.
- Do not introduce dependencies.
- Keep CLI environment-channel support for backwards compatibility; the bot must always pass explicit personal channels.
- Preserve pre-existing `source_posts` rows as legacy owner `user_id = 0`; do not show them in the personal bot flow.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `app/database/models.py` | Add and persist `tg_channels` in user settings. |
| `app/sources/telegram_feed.py` | Normalize public channel input; migrate, save, and retrieve source posts by owner. |
| `app/handlers/commands.py` | Add the channel-settings FSM flow and use only the requesting user's TG configuration. |
| `tests/database/test_user_settings.py` | Exercise user-settings migration and per-user channel isolation. |
| `tests/sources/test_telegram_feed.py` | Exercise input normalization, filter semantics, and owner-scoped source-post persistence. |
| `README.md` | Document credentials versus per-user channel configuration. |

### Task 1: Persist personal channel lists in user settings

**Files:**
- Create: `tests/database/__init__.py`
- Create: `tests/database/test_user_settings.py`
- Modify: `app/database/models.py:6-111`

**Interfaces:**
- Produces: `get_user_settings(user_id: int) -> dict | None` with a `tg_channels: list[str]` key.
- Produces: `update_user_settings(..., tg_channels: list[str] | None = None) -> None`.
- Consumes: module constant `DB_NAME`, monkeypatchable in tests before calling `init_db()`.

- [ ] **Step 1: Write the failing migration and isolation tests**

```python
import asyncio

from app.database import models


def test_user_settings_migrates_and_keeps_personal_channels(tmp_path, monkeypatch):
    db_path = tmp_path / "bot.sqlite"
    monkeypatch.setattr(models, "DB_NAME", str(db_path))

    async def scenario():
        await models.init_db()
        await models.update_user_settings(101, tg_channels=["ai_engineer_jobs"])
        await models.update_user_settings(202, tg_channels=["other_jobs"])
        first = await models.get_user_settings(101)
        second = await models.get_user_settings(202)
        assert first["tg_channels"] == ["ai_engineer_jobs"]
        assert second["tg_channels"] == ["other_jobs"]

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/database/test_user_settings.py::test_user_settings_migrates_and_keeps_personal_channels -v`

Expected: FAIL because `update_user_settings()` does not accept `tg_channels` and returned settings omit the key.

- [ ] **Step 3: Add the minimal user-settings migration and API**

In `init_db()`, add the idempotent migration:

```python
try:
    await db.execute("ALTER TABLE user_settings ADD COLUMN tg_channels TEXT")
except aiosqlite.OperationalError:
    pass
```

Extend both SELECT statements to select `tg_channels`, deserialize it with `json.loads(row[index]) if row[index] else []`, add `tg_channels` to `update_user_settings`, and serialize it only when the caller passes a non-`None` value. The insert path can rely on SQLite `NULL`, because the reader maps it to `[]`.

- [ ] **Step 4: Run the focused test and existing source tests**

Run: `pytest tests/database/test_user_settings.py tests/sources -v`

Expected: PASS; existing source tests remain unchanged.

- [ ] **Step 5: Commit the database deliverable**

```bash
git add app/database/models.py tests/database
git commit -m "feat: store personal telegram channels"
```

### Task 2: Make Telegram source data owner-aware and normalize channel input

**Files:**
- Create: `tests/sources/test_telegram_feed.py`
- Modify: `app/sources/telegram_feed.py:26-303`
- Modify: `app/sources/models.py:24-30`

**Interfaces:**
- Produces: `normalize_channels(raw: str) -> list[str]`, returning unique normalized public usernames in their first-seen order.
- Produces: `save_post(user_id: int, post: JobPost, db_path: str) -> bool`.
- Produces: `get_recent_posts(user_id: int, db_path: str = DEFAULT_DB_PATH, limit: int = 10) -> list[SavedPostPreview]`.
- Produces: `fetch_channel_posts(..., user_id: int = 0, ...) -> list[ChannelFetchStats]` and `fetch_from_config(..., user_id: int = 0, channels: list[str] | None = None, ...)`.
- Consumes: existing `JobPost` value object; add `user_id` to `SavedPostPreview` only if it is needed by a caller (the handler does not need it).

- [ ] **Step 1: Write failing tests for normalization, filtering, and ownership**

```python
import asyncio

from app.sources.models import JobPost
from app.sources.telegram_feed import _matches_filters, get_recent_posts, normalize_channels, save_post


def test_normalize_channels_accepts_supported_forms_and_deduplicates():
    assert normalize_channels(
        "@ai_engineer_jobs, https://t.me/ai_engineer_jobs, other_jobs, https://example.com/x"
    ) == ["ai_engineer_jobs", "other_jobs"]


def test_filters_require_any_include_and_reject_negative_match():
    assert _matches_filters("Python LLM role", ["go", "python"], ["senior"])
    assert not _matches_filters("Python Senior role", ["python"], ["senior"])


def test_saved_posts_are_scoped_to_owner(tmp_path):
    post = JobPost("telegram", "ai_engineer_jobs", 1, "", "Python role", "", "Python role", "hash")

    async def scenario():
        assert await save_post(101, post, str(tmp_path / "posts.sqlite"))
        assert await get_recent_posts(101, str(tmp_path / "posts.sqlite"))
        assert await get_recent_posts(202, str(tmp_path / "posts.sqlite")) == []

    asyncio.run(scenario())
```

- [ ] **Step 2: Run the source tests to verify they fail**

Run: `pytest tests/sources/test_telegram_feed.py -v`

Expected: FAIL because `normalize_channels` and owner-aware signatures do not exist.

- [ ] **Step 3: Implement input normalization and owner-scoped persistence**

Implement `normalize_channels()` by splitting CSV input, accepting `@username` and a parsed `https://t.me/<username>` path, rejecting other domains, validating Telegram username syntax, and preserving first-seen order.

Extend the `source_posts` schema with `user_id INTEGER NOT NULL`. In `init_source_db()`, use `PRAGMA table_info(source_posts)` to detect a legacy table without `user_id`; in a transaction, create an owner-aware replacement table with:

```sql
UNIQUE(user_id, source, channel, message_id)
```

Copy all legacy rows into it with `user_id = 0`, then replace the old table. For a new database, create the owner-aware schema directly. Include `user_id` in the insert, dedupe key, and the `WHERE user_id = ?` clause of `get_recent_posts()`.

Pass `user_id` through `fetch_channel_posts()` into `save_post()`. In `fetch_from_config()`, use `channels if channels is not None else ...` so an explicitly empty personal list does not silently fall back to `TG_JOB_CHANNELS`. Preserve CLI behavior by leaving its caller on the default owner `0`.

- [ ] **Step 4: Run source tests and the complete suite**

Run: `pytest tests/sources/test_telegram_feed.py tests/sources -v`

Expected: PASS.

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 5: Commit the reader deliverable**

```bash
git add app/sources/telegram_feed.py app/sources/models.py tests/sources/test_telegram_feed.py
git commit -m "feat: scope telegram posts by user"
```

### Task 3: Add the personal-channel bot flow and document it

**Files:**
- Modify: `app/handlers/commands.py:21-329`
- Modify: `README.md:68-108,351-379`

**Interfaces:**
- Consumes: `normalize_channels(raw: str) -> list[str]` from `app.sources.telegram_feed`.
- Consumes: `update_user_settings(user_id, tg_channels=...)` and `settings["tg_channels"]`.
- Consumes: owner-aware `fetch_from_config(channels=..., keywords=..., negative_keywords=..., user_id=...)` and `get_recent_posts(user_id=...)`.
- Produces: `UserState.waiting_for_tg_channels` and handlers for `⚙️ Настроить каналы`.

- [ ] **Step 1: Write a focused failing test for the pure channel-input contract**

Add this test to `tests/sources/test_telegram_feed.py`; it is the handler's parsing dependency and avoids coupling tests to aiogram internals.

```python
def test_normalize_channels_returns_empty_for_only_invalid_entries():
    assert normalize_channels("https://example.com/jobs, @bad!") == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/sources/test_telegram_feed.py::test_normalize_channels_returns_empty_for_only_invalid_entries -v`

Expected: FAIL until the validator rejects unsupported URLs and malformed usernames.

- [ ] **Step 3: Wire the menu and handlers**

Add `KeyboardButton(text="⚙️ Настроить каналы")` to `get_tg_sources_keyboard()` and `waiting_for_tg_channels` to `UserState`.

Implement the settings action with these exact outcomes:

```python
@router.message(F.text == "⚙️ Настроить каналы")
async def ask_for_tg_channels(message: Message, state: FSMContext):
    await message.answer(
        "Отправь публичные Telegram-каналы через запятую. "
        "Подойдут @channel, channel или https://t.me/channel. "
        "Чтобы очистить список, отправь: <code>-</code>",
        parse_mode="HTML",
    )
    await state.set_state(UserState.waiting_for_tg_channels)
```

The state handler maps `-` to `[]`; otherwise it calls `normalize_channels(message.text or "")`. If the result is empty, it explains that no valid public channels were found and leaves the previous setting intact. For a non-empty result, call `update_user_settings(message.from_user.id, tg_channels=channels)`, confirm the normalized list, and clear state.

Change `scan_telegram_sources()` to reject an empty `settings["tg_channels"]` with a direction to `⚙️ Настроить каналы`. Otherwise pass `channels=settings["tg_channels"]`, `user_id=message.from_user.id`, and the existing user keyword arrays into `fetch_from_config()`. Change `show_saved_telegram_posts()` to call `get_recent_posts(user_id=message.from_user.id, limit=10)`.

Update `README.md` so `TG_API_ID`, `TG_API_HASH`, and `TG_SESSION_NAME` remain deployment configuration, while users add scan channels inside the bot. Remove the claim that bot scans use `TG_JOB_CHANNELS`.

- [ ] **Step 4: Run the focused tests and manually verify the bot flow**

Run: `pytest tests/database/test_user_settings.py tests/sources/test_telegram_feed.py -v`

Expected: PASS.

Manual verification:

1. Start the bot and send `/start`.
2. Open `📡 TG вакансии` → `⚙️ Настроить каналы`.
3. Send `https://t.me/ai_engineer_jobs, @ai_engineer_jobs`; confirm one saved username.
4. Run `📡 Скан TG`; verify the displayed settings' HH keywords are used and only this user's channels are queried.
5. Open `🗂 TG посты`; verify posts from another test user are absent.

- [ ] **Step 5: Run regression tests and commit the complete feature**

Run: `pytest -q`

Expected: PASS.

```bash
git add app/handlers/commands.py README.md tests/sources/test_telegram_feed.py
git commit -m "feat: configure telegram channels in bot"
```

## Plan Self-Review

- **Spec coverage:** Task 1 implements the personal channel setting; Task 2 implements accepted forms, filtering semantics, and data isolation; Task 3 wires the bot flow and documents it. No HeadHunter search path is modified.
- **Placeholder scan:** No TBD/TODO entries or deferred implementation steps remain.
- **Type consistency:** Every bot caller passes `user_id` and explicit `channels`; `save_post`, `get_recent_posts`, and the source fetch functions use the same integer owner identifier.
