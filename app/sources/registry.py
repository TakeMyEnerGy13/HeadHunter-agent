from __future__ import annotations

import logging

from config import SUPERJOB_API_KEY, TRUDVSEM_ENABLED
from app.sources.base import JobSource
from app.sources.superjob import SuperJobClient
from app.sources.trudvsem import TrudvsemClient

logger = logging.getLogger(__name__)


def get_active_sources() -> list[JobSource]:
    sources: list[JobSource] = []

    if SUPERJOB_API_KEY.strip():
        sources.append(SuperJobClient(api_key=SUPERJOB_API_KEY))
        logger.info("SuperJob source enabled")
    else:
        logger.warning("SuperJob source disabled: SUPERJOB_API_KEY is empty")

    if TRUDVSEM_ENABLED.strip() not in ("0", "false", "no", ""):
        sources.append(TrudvsemClient())
        logger.info("Trudvsem source enabled")
    else:
        logger.info("Trudvsem source disabled by config")

    return sources
