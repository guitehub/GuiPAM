"""Journal d'audit : trace de toute mutation."""

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import AuditLog, User

# Champs à ne jamais consigner en clair.
SENSITIVE_FIELDS = {"hashed_password", "password"}


def diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """Diff avant/après, champs sensibles masqués."""
    before = before or {}
    after = after or {}
    changes: dict[str, Any] = {}
    for key in sorted(set(before) | set(after)):
        if key in ("created_at", "updated_at"):
            continue
        old, new = before.get(key), after.get(key)
        if old != new:
            if key in SENSITIVE_FIELDS:
                changes[key] = {"before": "***", "after": "***"}
            else:
                changes[key] = {"before": _scalar(old), "after": _scalar(new)}
    return changes


def _scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)


async def record(
    session: AsyncSession,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    changes: dict[str, Any] | None = None,
) -> None:
    """Ajoute une entrée d'audit (commit laissé à l'appelant)."""
    session.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "système",
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            changes=changes or None,
        )
    )
