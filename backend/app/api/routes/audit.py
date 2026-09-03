"""Audit log — admin-only, the append-only record of state-changing actions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import SessionDep
from app.auth.dependencies import require_role
from app.auth.roles import Role
from app.db.repositories import AuditRepository

router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
    dependencies=[Depends(require_role(Role.ADMIN))],
)


@router.get("")
def list_audit_entries(
    session: SessionDep, limit: int = Query(default=100, ge=1, le=1000)
) -> list[dict]:
    return [
        {
            "id": str(row.id),
            "actor": row.actor,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "detail": row.detail,
            "note": row.note,
            "created_at": row.created_at.isoformat(),
        }
        for row in AuditRepository(session).recent(limit)
    ]
