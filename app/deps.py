"""Dépendances FastAPI : authentification, rôles, CSRF."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.i18n import gettext as _
from app.models import Role, User
from app.services.auth import (
    CSRF_FORM_FIELD,
    CSRF_HEADER,
    CSRF_SESSION_KEY,
    csrf_tokens_match,
    session_matches_password,
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class NotAuthenticatedError(Exception):
    """Gérée dans main.py : redirection vers /login (HX-Redirect pour HTMX)."""


async def get_current_user(request: Request, session: SessionDep) -> User | None:
    # Déjà chargé par le middleware de contexte (main.py) sur les pages normales.
    state_user = getattr(request.state, "user", None)
    if state_user is not None:
        return state_user
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    user = await session.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or not session_matches_password(request.session, user.hashed_password)
    ):
        request.session.clear()
        return None
    request.state.user = user
    return user


async def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if user is None:
        raise NotAuthenticatedError()
    return user


async def require_manager(user: Annotated[User, Depends(require_user)]) -> User:
    if user.role != Role.manager:
        raise HTTPException(status_code=403, detail=_("Read-only account: action not allowed."))
    return user


CurrentUser = Annotated[User, Depends(require_user)]
ManagerUser = Annotated[User, Depends(require_manager)]

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def csrf_protect(request: Request) -> None:
    """Vérifie le jeton CSRF sur toute requête mutante (header HTMX ou champ de formulaire)."""
    if request.method not in MUTATING_METHODS:
        return
    expected = request.session.get(CSRF_SESSION_KEY)
    provided = request.headers.get(CSRF_HEADER)
    if provided is None:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            form = await request.form()
            value = form.get(CSRF_FORM_FIELD)
            provided = value if isinstance(value, str) else None
    if not csrf_tokens_match(expected, provided):
        raise HTTPException(status_code=403, detail=_("Invalid or missing CSRF token."))
