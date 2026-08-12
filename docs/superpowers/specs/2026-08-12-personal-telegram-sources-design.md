# Personal Telegram Sources Design

## Goal

Let each bot user manage their own Telegram job channels. Keep the existing HeadHunter keyword profile as the only text-filter source for Telegram scans.

## Scope

- Store a personal list of Telegram channel usernames for every `user_id`.
- Add a Telegram-menu action for setting or clearing that list.
- Scan only the requesting user's channels.
- Reuse existing `keywords` and `negative_keywords` from `user_settings`:
  - a post must contain at least one keyword when keywords are configured;
  - a post is rejected when it contains any negative keyword.
- Isolate saved Telegram posts by `user_id`.
- Support channel input as comma-separated `@username`, `username`, or `https://t.me/username` values.

## Out of Scope

- Separate Telegram keyword profiles.
- Filters for seniority, work format, salary, location, or LLM classification.
- Changes to HeadHunter search filtering.
- Scheduled background Telegram scans.

## User Flow

1. The user opens `📡 TG вакансии`.
2. The user selects `⚙️ Настроить каналы`.
3. The bot asks for comma-separated channel links or usernames. Sending `-` clears the list.
4. The bot validates and stores normalized usernames in the user's settings.
5. The user selects `📡 Скан TG`.
6. The scanner reads the stored channels and applies the user's existing HeadHunter include/exclude keywords.
7. The user selects `🗂 TG посты` to see only posts saved for that user.

## Data Model

`user_settings` gains `tg_channels TEXT`, containing a JSON list of normalized Telegram usernames. The migration is additive and gives existing users an empty list.

`source_posts` gains a `user_id` owner. Its uniqueness becomes `(user_id, source, channel, message_id)` so the same public message can be independently saved for users with different filters. Existing rows are preserved as unowned legacy rows and are not returned through the personal bot flow.

## Components

- `app/database/models.py`
  - migrate, load, and update `tg_channels` in user settings.
- `app/handlers/commands.py`
  - add the channel-settings button and FSM state;
  - pass the user's channels and `user_id` into the scan;
  - retrieve only the user's saved posts.
- `app/sources/telegram_feed.py`
  - normalize Telegram links and usernames;
  - accept explicit channels without falling back to environment configuration;
  - persist and query posts by owner.
- `tests/`
  - cover input normalization, personal channel storage, post isolation, and include/exclude behavior.
- `README.md`
  - document per-user channel setup and retain Telethon credentials as deployment configuration.

## Error Handling

- A scan without personal channels returns a clear bot message directing the user to channel settings.
- Invalid or empty channel entries are ignored; if no valid channels remain, the bot does not save the setting.
- Telegram authentication and channel-access errors continue to be shown to the requesting user without exposing credentials.

## Acceptance Criteria

- Two users can configure different channel lists and scans never read another user's list.
- Telegram scans use the existing HeadHunter `keywords` and `negative_keywords` for the same user.
- A user sees only their saved Telegram posts.
- The bot accepts `@channel`, `channel`, and `https://t.me/channel` input.
- Existing HeadHunter search behavior remains unchanged.
