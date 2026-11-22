"""Connexion / déconnexion / changement de langue."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from app.deps import SessionDep, csrf_protect, get_current_user
from app.flash import flash
from app.i18n import LOCALE_COOKIE, available_locales, gettext as _
from app.models import User, utcnow
from app.services import audit
from app.services.auth import login_rate_limiter, start_login, verify_password
from app.templating import render

router = APIRouter(dependencies=[Depends(csrf_protect)])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/login")
async def login_page(request: Request, session: SessionDep):
    user = await get_current_user(request, session)
    if user is not None:
        return RedirectResponse("/", status_code=302)
    return render(request, "login.html")


@router.post("/login")
async def login(
    request: Request,
    session: SessionDep,
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    remember: Annotated[bool, Form()] = False,
):
    username = username.strip()
    ip = _client_ip(request)

    retry_after = login_rate_limiter.retry_after(ip, username)
    if retry_after > 0:
        error = _("Too many attempts. Try again in %d seconds.") % int(retry_after + 1)
        return render(
            request, "login.html", {"error": error, "username": username, "remember": remember}, status_code=429
        )

    result = await session.exec(select(User).where(User.username == username))
    user = result.first()
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        login_rate_limiter.record_failure(ip, username)
        error = _("Invalid username or password.")
        return render(
            request, "login.html", {"error": error, "username": username, "remember": remember}, status_code=422
        )

    login_rate_limiter.record_success(ip, username)
    start_login(request.session, user.id, user.hashed_password, remember)
    user.last_login_at = utcnow()
    session.add(user)
    await audit.record(session, user, "login", "user", user.id)
    await session.commit()
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.post("/locale")
async def set_locale_route(
    request: Request,
    session: SessionDep,
    locale: Annotated[str, Form()] = "fr",
):
    if locale not in available_locales():
        locale = "fr"
    user = await get_current_user(request, session)
    if user is not None:
        user.locale = locale
        session.add(user)
        await session.commit()
    referer = request.headers.get("referer", "/")
    response = RedirectResponse(referer, status_code=303)
    response.set_cookie(LOCALE_COOKIE, locale, max_age=365 * 24 * 3600, httponly=True, samesite="lax")
    return response
