"""Journal d'audit : consultation filtrable et paginée."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlmodel import select

from app.deps import CurrentUser, SessionDep
from app.models import AuditLog
from app.templating import render

router = APIRouter()

PAGE_SIZE = 50

ACTIONS = ["create", "update", "delete", "login", "check", "import", "export"]
ENTITY_TYPES = ["reseau", "subnet", "ip", "monitor", "user", "service_account", "api_key", "backup"]


@router.get("/audit")
async def audit_page(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    action: Annotated[str, Query()] = "",
    entity_type: Annotated[str, Query()] = "",
    username: Annotated[str, Query()] = "",
    page: Annotated[int, Query(ge=1)] = 1,
):
    statement = select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())  # type: ignore[attr-defined]
    if action:
        statement = statement.where(AuditLog.action == action)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if username.strip():
        statement = statement.where(AuditLog.username.contains(username.strip()))  # type: ignore[attr-defined]
    statement = statement.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1)
    rows = (await session.exec(statement)).all()
    has_next = len(rows) > PAGE_SIZE
    context = {
        "entries": rows[:PAGE_SIZE],
        "filters": {"action": action, "entity_type": entity_type, "username": username},
        "page": page,
        "has_next": has_next,
        "actions": ACTIONS,
        "entity_types": ENTITY_TYPES,
    }
    if request.headers.get("hx-request") and request.headers.get("hx-target") == "audit-rows":
        return render(request, "partials/_audit_rows.html", context)
    return render(request, "audit.html", context)
