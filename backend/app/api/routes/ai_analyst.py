"""AI Analyst endpoint.

Rate-limited more tightly than the rest of the API: each question is a real,
billed model call, unlike every other route here which only reads Postgres.
"""

# No `from __future__ import annotations` in this file: slowapi's
# @limiter.limit decorator wraps the endpoint in a way that loses
# FastAPI's ability to resolve postponed (stringified) annotations,
# which silently turns the request body and every Depends() parameter
# into a required query parameter instead. Verified in isolation --
# this is the one exception to the codebase-wide convention.

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.ai.analyst import AIAnalyst, AnalystUnavailable
from app.api.deps import SessionDep, SettingsDep
from app.auth.dependencies import require_authenticated

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(
    prefix="/api/ai-analyst", tags=["ai-analyst"], dependencies=[Depends(require_authenticated)]
)


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class AnswerOut(BaseModel):
    answer: str
    tools_used: list[str]


class AvailabilityOut(BaseModel):
    available: bool
    model: str | None = None


@router.get("/availability", response_model=AvailabilityOut)
def availability(settings: SettingsDep) -> AvailabilityOut:
    return AvailabilityOut(
        available=bool(settings.anthropic_api_key),
        model=settings.ai_analyst_model if settings.anthropic_api_key else None,
    )


@router.post("/ask", response_model=AnswerOut)
@limiter.limit("15/hour")
def ask(
    request: Request, body: QuestionRequest, session: SessionDep, settings: SettingsDep
) -> AnswerOut:
    try:
        analyst = AIAnalyst(session, settings)
        answer = analyst.ask(body.question)
    except AnalystUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    return AnswerOut(answer=answer.text, tools_used=answer.tools_used)
