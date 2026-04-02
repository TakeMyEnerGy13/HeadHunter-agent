from pydantic import BaseModel, Field


class VacancyAnalysis(BaseModel):
    match_score: int = Field(ge=0, le=100)
    brief_reason: str


class CoverLetter(BaseModel):
    text: str

