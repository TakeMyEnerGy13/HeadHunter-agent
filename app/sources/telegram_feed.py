import argparse
import asyncio
import hashlib
import os
import sqlite3
from datetime import timezone
from pathlib import Path
from typing import Iterable

import aiosqlite

from app.sources.models import ChannelFetchStats, JobPost, SavedPostPreview
from config import (
    TG_API_HASH,
    TG_API_ID,
    TG_JOB_CHANNELS,
    TG_SOURCE_DB_PATH,
    TG_SESSION_NAME,
    TG_SOURCE_KEYWORDS,
    TG_SOURCE_NEGATIVE_KEYWORDS,
)

DEFAULT_DB_PATH = TG_SOURCE_DB_PATH


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_channel(channel: str) -> str:
    return channel.strip().lstrip("@")


def _normalize_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean[:120]
    return "Telegram job post"


def _matches_filters(text: str, keywords: Iterable[str], negative_keywords: Iterable[str]) -> bool:
    normalized = _normalize_text(text)
    normalized_keywords = [_normalize_text(keyword) for keyword in keywords]
    normalized_negative = [_normalize_text(keyword) for keyword in negative_keywords]

    if normalized_keywords and not any(keyword in normalized for keyword in normalized_keywords):
        return False
    return not any(keyword in normalized for keyword in normalized_negative)


async def init_source_db(db_path: str = DEFAULT_DB_PATH) -> None:
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS source_posts (
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
        await db.commit()


async def save_post(post: JobPost, db_path: str = DEFAULT_DB_PATH) -> bool:
    await init_source_db(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute(
            """
            INSERT OR IGNORE INTO source_posts (
                source, channel, message_id, posted_at, title, text, url, text_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.source,
                post.channel,
                post.message_id,
                post.posted_at,
                post.title,
                post.text,
                post.url,
                post.text_hash,
            ),
        )
        await db.commit()
        return cursor.rowcount > 0


def _build_post(channel: str, entity: object, message: object) -> JobPost | None:
    text = (getattr(message, "message", None) or "").strip()
    if not text:
        return None

    message_id = int(getattr(message, "id"))
    posted_at_value = getattr(message, "date", None)
    if posted_at_value:
        posted_at = posted_at_value.astimezone(timezone.utc).isoformat()
    else:
        posted_at = ""

    username = getattr(entity, "username", None)
    url = f"https://t.me/{username}/{message_id}" if username else ""

    return JobPost(
        source="telegram",
        channel=channel,
        message_id=message_id,
        posted_at=posted_at,
        text=text,
        url=url,
        title=_title_from_text(text),
        text_hash=_hash_text(text),
    )


async def fetch_channel_posts(
    channels: list[str],
    limit: int,
    keywords: list[str],
    negative_keywords: list[str],
    db_path: str,
    session_name: str,
    api_id: int,
    api_hash: str,
    verbose: bool = True,
) -> list[ChannelFetchStats]:
    try:
        from telethon import TelegramClient
    except ImportError as exc:
        raise RuntimeError("Telethon is not installed. Run: pip install -r requirements.txt") from exc

    await init_source_db(db_path)
    stats: list[ChannelFetchStats] = []

    client = TelegramClient(session_name, api_id, api_hash)
    await client.start()
    try:
        for raw_channel in channels:
            channel = _normalize_channel(raw_channel)
            scanned = 0
            saved = 0
            duplicates = 0
            filtered = 0

            entity = await client.get_entity(channel)
            async for message in client.iter_messages(entity, limit=limit):
                scanned += 1
                post = _build_post(channel, entity, message)
                if not post:
                    filtered += 1
                    continue
                if not _matches_filters(post.text, keywords, negative_keywords):
                    filtered += 1
                    continue

                if await save_post(post, db_path):
                    saved += 1
                    if verbose:
                        print(f"[saved] @{channel} #{post.message_id}: {post.title}")
                else:
                    duplicates += 1

            stats.append(
                ChannelFetchStats(
                    channel=channel,
                    scanned=scanned,
                    saved=saved,
                    duplicates=duplicates,
                    filtered=filtered,
                )
            )
            if verbose:
                print(
                    f"@{channel}: scanned={scanned}, saved={saved}, "
                    f"duplicates={duplicates}, filtered={filtered}"
                )
    finally:
        await client.disconnect()

    return stats


def _validate_config(api_id_raw: str, api_hash: str, channels: list[str]) -> tuple[int, str]:
    if not api_id_raw.strip():
        raise ValueError("TG_API_ID is required")
    if not api_hash.strip():
        raise ValueError("TG_API_HASH is required")
    if not channels:
        raise ValueError("At least one Telegram channel is required")

    try:
        api_id = int(api_id_raw)
    except ValueError as exc:
        raise ValueError("TG_API_ID must be an integer") from exc

    return api_id, api_hash


def print_recent_posts(db_path: str, limit: int) -> int:
    path = Path(db_path)
    if not path.exists():
        print(f"Source DB not found: {path}")
        return 0

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT channel, message_id, posted_at, title, url
            FROM source_posts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        print("No saved Telegram posts found.")
        return 0

    for row in rows:
        print(f"@{row['channel']} #{row['message_id']} {row['posted_at']}")
        print(f"  {row['title']}")
        if row["url"]:
            print(f"  {row['url']}")
    return 0


async def get_recent_posts(db_path: str = DEFAULT_DB_PATH, limit: int = 10) -> list[SavedPostPreview]:
    path = Path(db_path)
    if not path.exists():
        return []

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT channel, message_id, posted_at, title, url
            FROM source_posts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()

    return [
        SavedPostPreview(
            channel=row["channel"],
            message_id=int(row["message_id"]),
            posted_at=row["posted_at"] or "",
            title=row["title"] or "",
            url=row["url"] or "",
        )
        for row in rows
    ]


async def fetch_from_config(
    channels: list[str] | None = None,
    keywords: list[str] | None = None,
    negative_keywords: list[str] | None = None,
    limit: int = 20,
    db_path: str = DEFAULT_DB_PATH,
    verbose: bool = False,
) -> list[ChannelFetchStats]:
    resolved_channels = channels or [_normalize_channel(channel) for channel in _split_csv(TG_JOB_CHANNELS)]
    resolved_keywords = keywords if keywords is not None else _split_csv(TG_SOURCE_KEYWORDS)
    resolved_negative = (
        negative_keywords if negative_keywords is not None else _split_csv(TG_SOURCE_NEGATIVE_KEYWORDS)
    )
    api_id, api_hash = _validate_config(TG_API_ID, TG_API_HASH, resolved_channels)

    return await fetch_channel_posts(
        channels=resolved_channels,
        limit=limit,
        keywords=resolved_keywords,
        negative_keywords=resolved_negative,
        db_path=db_path,
        session_name=TG_SESSION_NAME,
        api_id=api_id,
        api_hash=api_hash,
        verbose=verbose,
    )


async def async_main(args: argparse.Namespace) -> int:
    channels = [_normalize_channel(channel) for channel in _split_csv(args.channels or TG_JOB_CHANNELS)]
    keywords = _split_csv(args.keywords if args.keywords is not None else TG_SOURCE_KEYWORDS)
    negative_keywords = _split_csv(
        args.negative_keywords if args.negative_keywords is not None else TG_SOURCE_NEGATIVE_KEYWORDS
    )
    session_name = args.session or TG_SESSION_NAME
    api_id, api_hash = _validate_config(TG_API_ID, TG_API_HASH, channels)

    stats = await fetch_channel_posts(
        channels=channels,
        limit=args.limit,
        keywords=keywords,
        negative_keywords=negative_keywords,
        db_path=args.db,
        session_name=session_name,
        api_id=api_id,
        api_hash=api_hash,
        verbose=True,
    )
    saved_total = sum(item.saved for item in stats)
    print(f"Saved total: {saved_total}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch job posts from Telegram channels via Telethon.")
    parser.add_argument("--channels", default=None, help="Comma-separated channel usernames. Defaults to TG_JOB_CHANNELS.")
    parser.add_argument("--keywords", default=None, help="Comma-separated include keywords. Defaults to TG_SOURCE_KEYWORDS.")
    parser.add_argument(
        "--negative-keywords",
        default=None,
        help="Comma-separated exclude keywords. Defaults to TG_SOURCE_NEGATIVE_KEYWORDS.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Messages to scan per channel.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="SQLite path for saved source posts.")
    parser.add_argument("--session", default=None, help="Telethon session name. Defaults to TG_SESSION_NAME.")
    parser.add_argument("--list-saved", action="store_true", help="Print recently saved posts without fetching.")

    args = parser.parse_args()

    if args.limit < 1:
        print("--limit must be >= 1")
        return 1
    if args.list_saved:
        return print_recent_posts(args.db, args.limit)

    try:
        return asyncio.run(async_main(args))
    except Exception as exc:
        print(f"Telegram feed error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
