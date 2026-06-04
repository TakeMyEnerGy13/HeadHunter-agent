# Multi-Source Job Search Design

**Date:** 2026-05-29
**Status:** Approved
**Problem:** HH.ru disabled public vacancy search API. Bot needs alternative job sources.
**Solution:** Replace HHClient with pluggable JobSource architecture using SuperJob API + Trudvsem.ru API.

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sources | SuperJob API + Trudvsem.ru API | Real APIs, no scraping fragility |
| Architecture | Abstract `JobSource` interface | Easy to add sources later |
| User settings | Shared keywords across all sources | Simpler UX, LLM filters irrelevant results |
| Deduplication | None at start | Rare cross-platform overlap, add later if needed |

---

## 1. Unified Vacancy Model

New `UnifiedVacancy` replaces HH-specific `Vacancy` as the common data model:

```python
class UnifiedVacancy(BaseModel):
    source: str            # "superjob" | "trudvsem" | "hh"
    external_id: str       # "{source}:{platform_id}" — unique key for seen_vacancies
    title: str
    company: str
    url: str
    description: str       # Full text for LLM (requirements + responsibilities)
    salary: str | None     # Display only, not for filtering
```

Location: `app/sources/models.py` (alongside existing dataclasses)

## 2. JobSource Abstract Interface

```python
class JobSource(ABC):
    source_name: str

    @abstractmethod
    async def fetch_vacancies(
        self,
        keywords: list[str],
        negative_keywords: list[str],
        seen_ids: set[str],
        target_count: int = 50,
    ) -> list[UnifiedVacancy]: ...
```

Location: `app/sources/base.py`

### 2a. SuperJobClient

- Endpoint: `https://api.superjob.ru/2.0/vacancies/`
- Auth: `X-Api-App-Id` header (Secret key)
- Params: `keyword`, `count` (max 100), `page`, `order_field=date`
- Field mapping: `profession` -> title, `firm_name` -> company, `link` -> url, `candidat` + `work` -> description
- Pagination: iterate until `target_count` new vacancies or pages exhausted
- Throttle: 1s between pages
- Error handling: log + return empty list

Location: `app/sources/superjob.py`

### 2b. TrudvsemClient

- Endpoint: `http://opendata.trudvsem.ru/api/v1/vacancies`
- Auth: none required
- Params: `text`, `limit` (max 100), `offset`
- Field mapping: `job-name` -> title, `company.name` -> company, `vac_url` -> url, `duty` -> description
- Same pagination/throttle/error pattern as SuperJob

Location: `app/sources/trudvsem.py`

### Common logic in both clients:
- Negative keyword filtering: case-insensitive substring match on `title + description`
- Skip `seen_ids` by `external_id`
- On API error: log warning, return empty list (don't crash the whole search)

## 3. Changes to run_search_job

**New flow:**
```
sources = [SuperJobClient(), TrudvsemClient()]  # only enabled ones
seen_ids = load_all_seen_ids(user_id)           # one bulk query

for source in sources:
    vacancies += source.fetch_vacancies(keywords, negative, seen_ids, target=50)

for vac in vacancies:
    analysis = AnalyzerAgent.analyze_vacancy(vac.description, resume)
    if analysis.match_score >= 60:
        letter = WriterAgent.generate_letter(vac.description, resume, ...)
        TelegramNotifier.send_vacancy_alert(vac.title, vac.company, vac.url, ...)
    mark_vacancy_seen(user_id, vac.external_id)
```

**What changes in `main_bot.py`:**
- `run_search_job` works with `list[UnifiedVacancy]` instead of `list[Vacancy]`
- No more `HHClient()` — replaced by list of `JobSource`
- Fields accessed directly: `vac.title`, `vac.company`, `vac.url`, `vac.description`
- `seen_ids` loaded once before source loop (bulk query)

**What does NOT change:**
- `AnalyzerAgent`, `WriterAgent`, `CoverLetterPipeline` — same inputs
- `TelegramNotifier.send_vacancy_alert` — same parameters
- Scheduler logic (`scheduled_search_for_all`)
- UI in `commands.py`

## 4. Configuration

### New .env variables:
```
SUPERJOB_API_KEY=          # Secret key from api.superjob.ru
TRUDVSEM_ENABLED=1         # Set to 0 to disable
```

### SuperJob registration:
1. Go to api.superjob.ru
2. Register application (type: "API access for developers")
3. Copy Secret key to SUPERJOB_API_KEY

### Graceful degradation:
- Empty `SUPERJOB_API_KEY` -> SuperJob skipped with log warning
- `TRUDVSEM_ENABLED=0` -> Trudvsem skipped
- Both disabled -> bot tells user "no active sources configured"
- Each source catches its own errors independently

## 5. File Structure (new/modified)

```
app/sources/
├── base.py              # NEW: JobSource ABC + UnifiedVacancy model
├── superjob.py          # NEW: SuperJobClient
├── trudvsem.py          # NEW: TrudvsemClient
├── registry.py          # NEW: get_active_sources() factory
├── models.py            # EXISTING: keep Telegram post models
└── telegram_feed.py     # EXISTING: unchanged
config.py                # MODIFIED: add SUPERJOB_API_KEY, TRUDVSEM_ENABLED
main_bot.py              # MODIFIED: run_search_job uses JobSource list
.env.example             # MODIFIED: add new vars
```
