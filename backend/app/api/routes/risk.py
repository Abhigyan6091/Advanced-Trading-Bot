"""Risk decisions, limits and rejection analysis.

The endpoints behind the dashboard section that matters most: what the engine
refused, and why.
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import ServiceDep, SessionDep
from app.api.presenters import risk_decision_out, safe_ratio
from app.api.schemas import RiskDecisionOut, RiskSummaryOut
from app.core.money import ZERO
from app.db.repositories import RiskDecisionRepository

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("/summary", response_model=RiskSummaryOut)
def summary(session: SessionDep, service: ServiceDep) -> RiskSummaryOut:
    repo = RiskDecisionRepository(session)
    counts = repo.counts_by_action()
    total = sum(counts.values())

    limits = service.risk_engine.limits
    return RiskSummaryOut(
        limits={k: str(v) for k, v in limits.model_dump().items()},
        decision_counts=counts,
        rejection_reasons=repo.rejection_reasons(),
        current_score=_current_score(repo),
        approval_rate=safe_ratio(counts.get("APPROVE", 0), total),
        recent=[risk_decision_out(r) for r in repo.recent(limit=20)],
    )


@router.get("/decisions", response_model=list[RiskDecisionOut])
def decisions(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=500),
    action: str | None = Query(default=None, pattern="^(APPROVE|REDUCE|REJECT)$"),
) -> list[RiskDecisionOut]:
    repo = RiskDecisionRepository(session)
    return [risk_decision_out(r) for r in repo.recent(limit=limit, action=action)]


@router.get("/rejections", response_model=list[RiskDecisionOut])
def rejections(
    session: SessionDep, limit: int = Query(default=50, ge=1, le=500)
) -> list[RiskDecisionOut]:
    """Refused trades with their reasons — the product's signature view."""
    repo = RiskDecisionRepository(session)
    return [risk_decision_out(r) for r in repo.rejections(limit=limit)]


@router.get("/decisions/{decision_id}", response_model=RiskDecisionOut)
def decision_detail(session: SessionDep, decision_id: str) -> RiskDecisionOut:
    from app.db.models import RiskDecisionRow

    row = session.get(RiskDecisionRow, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="risk decision not found")
    return risk_decision_out(row)


@router.get("/limits")
def limits(service: ServiceDep) -> dict[str, str]:
    return {k: str(v) for k, v in service.risk_engine.limits.model_dump().items()}


def _current_score(repo: RiskDecisionRepository) -> Decimal:
    """Mean score of the last twenty decisions — the account's risk posture."""
    recent = repo.recent(limit=20)
    if not recent:
        return ZERO
    return sum((r.score for r in recent), ZERO) / len(recent)
