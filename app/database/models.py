import aiosqlite
import json

DB_NAME = "bot_data.sqlite"


async def init_db():
    """Создает таблицу настроек пользователя, если её нет."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            '''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                resume_text TEXT,
                keywords TEXT,
                negative_keywords TEXT,
                is_active BOOLEAN DEFAULT 0
            )
        '''
        )
        # Мягкая миграция для уже существующей таблицы без negative_keywords.
        try:
            await db.execute("ALTER TABLE user_settings ADD COLUMN negative_keywords TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE user_settings ADD COLUMN tone_samples TEXT")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE user_settings ADD COLUMN preferences TEXT")
        except aiosqlite.OperationalError:
            pass
        await db.commit()


async def get_user_settings(user_id: int):
    """Получает настройки пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT resume_text, keywords, negative_keywords, is_active, tone_samples, preferences FROM user_settings WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "resume_text": row[0],
                    "keywords": json.loads(row[1]) if row[1] else [],
                    "negative_keywords": json.loads(row[2]) if row[2] else [],
                    "is_active": bool(row[3]),
                    "tone_samples": row[4] or "",
                    "preferences": row[5] or "",
                }
            return None


async def update_user_settings(
    user_id: int,
    resume_text: str = None,
    keywords: list = None,
    negative_keywords: list = None,
    is_active: bool = None,
    tone_samples: str = None,
    preferences: str = None,
):
    """Обновляет или создает настройки пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, существует ли пользователь
        async with db.execute("SELECT 1 FROM user_settings WHERE user_id = ?", (user_id,)) as cursor:
            exists = await cursor.fetchone()

        if exists:
            # Динамически формируем запрос на обновление
            updates = []
            values = []
            if resume_text is not None:
                updates.append("resume_text = ?")
                values.append(resume_text)
            if keywords is not None:
                updates.append("keywords = ?")
                values.append(json.dumps(keywords))
            if negative_keywords is not None:
                updates.append("negative_keywords = ?")
                values.append(json.dumps(negative_keywords))
            if is_active is not None:
                updates.append("is_active = ?")
                values.append(int(is_active))
            if tone_samples is not None:
                updates.append("tone_samples = ?")
                values.append(tone_samples)
            if preferences is not None:
                updates.append("preferences = ?")
                values.append(preferences)

            if updates:
                values.append(user_id)
                query = f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = ?"
                await db.execute(query, tuple(values))
        else:
            # Создаем нового пользователя
            kw_json = json.dumps(keywords) if keywords else "[]"
            negative_kw_json = json.dumps(negative_keywords) if negative_keywords else "[]"
            res_text = resume_text or ""
            active = int(is_active) if is_active is not None else 0
            await db.execute(
                "INSERT INTO user_settings (user_id, resume_text, keywords, negative_keywords, is_active) VALUES (?, ?, ?, ?, ?)",
                (user_id, res_text, kw_json, negative_kw_json, active),
            )
        await db.commit()


async def get_active_settings():
    """Возвращает активных пользователей для фонового поиска."""
    users = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, resume_text, keywords, negative_keywords, is_active, tone_samples, preferences FROM user_settings WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                users.append(
                    {
                        "user_id": row[0],
                        "resume_text": row[1],
                        "keywords": json.loads(row[2]) if row[2] else [],
                        "negative_keywords": json.loads(row[3]) if row[3] else [],
                        "is_active": bool(row[4]),
                        "tone_samples": row[5] or "",
                        "preferences": row[6] or "",
                    }
                )
    return users

