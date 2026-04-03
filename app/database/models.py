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
                is_active BOOLEAN DEFAULT 0
            )
        '''
        )
        await db.commit()


async def get_user_settings(user_id: int):
    """Получает настройки пользователя."""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT resume_text, keywords, is_active FROM user_settings WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "resume_text": row[0],
                    "keywords": json.loads(row[1]) if row[1] else [],
                    "is_active": bool(row[2])
                }
            return None


async def update_user_settings(user_id: int, resume_text: str = None, keywords: list = None, is_active: bool = None):
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
            if is_active is not None:
                updates.append("is_active = ?")
                values.append(int(is_active))

            if updates:
                values.append(user_id)
                query = f"UPDATE user_settings SET {', '.join(updates)} WHERE user_id = ?"
                await db.execute(query, tuple(values))
        else:
            # Создаем нового пользователя
            kw_json = json.dumps(keywords) if keywords else "[]"
            res_text = resume_text or ""
            active = int(is_active) if is_active is not None else 0
            await db.execute(
                "INSERT INTO user_settings (user_id, resume_text, keywords, is_active) VALUES (?, ?, ?, ?)",
                (user_id, res_text, kw_json, active)
            )
        await db.commit()


async def get_active_settings():
    """Возвращает активных пользователей для фонового поиска."""
    users = []
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT user_id, resume_text, keywords, is_active FROM user_settings WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                users.append(
                    {
                        "user_id": row[0],
                        "resume_text": row[1],
                        "keywords": json.loads(row[2]) if row[2] else [],
                        "is_active": bool(row[3]),
                    }
                )
    return users

