"""Gestion des utilisateurs (manager uniquement)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlmodel import select

from app.deps import ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import Role, User
from app.services import audit
from app.services.auth import hash_password
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])

MIN_PASSWORD_LENGTH = 8


async def _get_user(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=_("User not found."))
    return user


async def _active_manager_count(session: SessionDep) -> int:
    result = await session.exec(
        select(User).where(User.role == Role.manager, User.is_active == True)  # noqa: E712
    )
    return len(result.all())


def _user_dict(user: User) -> dict:
    return {"username": user.username, "role": user.role.value, "is_active": user.is_active}


def _parse_role(raw: str) -> Role:
    try:
        return Role(raw)
    except ValueError:
        return Role.user


@router.get("/users")
async def users_page(request: Request, user: ManagerUser, session: SessionDep):
    result = await session.exec(select(User).order_by(User.username))
    return render(request, "users.html", {"users": result.all()})


@router.get("/users/new")
async def user_new_form(request: Request, user: ManagerUser):
    return render(request, "partials/_user_form.html", {"target_user": None, "errors": []})


@router.get("/users/{user_id}/edit")
async def user_edit_form(request: Request, user: ManagerUser, session: SessionDep, user_id: int):
    target = await _get_user(session, user_id)
    return render(request, "partials/_user_form.html", {"target_user": target, "errors": []})


@router.post("/users")
async def create_user(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "user",
):
    errors: list[str] = []
    username = username.strip()
    if not username:
        errors.append(_("Username is required."))
    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(_("Password must be at least %d characters long.") % MIN_PASSWORD_LENGTH)
    if username:
        existing = (await session.exec(select(User).where(User.username == username))).first()
        if existing is not None:
            errors.append(_("Username “%s” is already taken.") % username)
    if errors:
        return render(
            request, "partials/_user_form.html", {"target_user": None, "errors": errors}, status_code=422
        )
    new_user = User(username=username, hashed_password=hash_password(password), role=_parse_role(role))
    session.add(new_user)
    await session.flush()
    await audit.record(session, user, "create", "user", new_user.id, audit.diff({}, _user_dict(new_user)))
    await session.commit()
    flash(request, _("User “%s” created.") % username)
    return hx_refresh()


@router.patch("/users/{user_id}")
async def update_user(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    user_id: int,
    role: Annotated[str, Form()] = "user",
    is_active: Annotated[str, Form()] = "",
):
    target = await _get_user(session, user_id)
    new_role = _parse_role(role)
    new_active = is_active == "on"
    was_active_manager = target.role == Role.manager and target.is_active
    demoted_or_deactivated = new_role != Role.manager or not new_active
    if was_active_manager and demoted_or_deactivated and await _active_manager_count(session) <= 1:
        return render(
            request,
            "partials/_user_form.html",
            {"target_user": target, "errors": [_("Cannot demote or deactivate the last active manager.")]},
            status_code=422,
        )
    before = _user_dict(target)
    target.role = new_role
    target.is_active = new_active
    session.add(target)
    await audit.record(session, user, "update", "user", target.id, audit.diff(before, _user_dict(target)))
    await session.commit()
    flash(request, _("User “%s” updated.") % target.username)
    return hx_refresh()


@router.post("/users/{user_id}/password")
async def reset_password(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    user_id: int,
    password: Annotated[str, Form()] = "",
):
    target = await _get_user(session, user_id)
    if len(password) < MIN_PASSWORD_LENGTH:
        return render(
            request,
            "partials/_user_form.html",
            {
                "target_user": target,
                "errors": [_("Password must be at least %d characters long.") % MIN_PASSWORD_LENGTH],
            },
            status_code=422,
        )
    target.hashed_password = hash_password(password)
    session.add(target)
    await audit.record(
        session, user, "update", "user", target.id, {"password": {"before": "***", "after": "***"}}
    )
    await session.commit()
    flash(request, _("Password of “%s” reset.") % target.username)
    return hx_refresh()


@router.delete("/users/{user_id}")
async def delete_user(request: Request, user: ManagerUser, session: SessionDep, user_id: int):
    target = await _get_user(session, user_id)
    if target.role == Role.manager and target.is_active and await _active_manager_count(session) <= 1:
        raise HTTPException(status_code=422, detail=_("Cannot delete the last active manager."))
    before = _user_dict(target)
    username = target.username
    await session.delete(target)
    await audit.record(session, user, "delete", "user", user_id, audit.diff(before, {}))
    await session.commit()
    flash(request, _("User “%s” deleted.") % username)
    return hx_refresh()
