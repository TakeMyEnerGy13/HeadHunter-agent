import asyncio

from app.database import models


def test_user_settings_keep_personal_telegram_channels(tmp_path, monkeypatch):
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
