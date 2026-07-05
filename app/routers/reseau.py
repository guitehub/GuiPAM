"""Édition du réseau singleton (manager)."""

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request

from app.deps import ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import available_locales, gettext as _
from app.models import RESEAU_SINGLETON_ID, Reseau, utcnow
from app.services import audit
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


def parse_root_prefixes(raw: str) -> tuple[list[str], list[str]]:
    """Préfixes racine informatifs, un par ligne ou séparés par des virgules."""
    prefixes: list[str] = []
    errors: list[str] = []
    for chunk in raw.replace(",", "\n").splitlines():
        value = chunk.strip()
        if not value:
            continue
        try:
            prefixes.append(str(ipaddress.ip_network(value, strict=False)))
        except ValueError:
            errors.append(_("“%s” is not a valid network prefix.") % value)
    return prefixes, errors


@router.get("/reseau/edit")
async def reseau_form(request: Request, user: ManagerUser, session: SessionDep):
    reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
    return render(request, "partials/_reseau_form.html", {"reseau": reseau, "errors": []})


@router.post("/reseau")
async def update_reseau(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    root_prefixes: Annotated[str, Form()] = "",
    default_locale: Annotated[str, Form()] = "fr",
):
    reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
    errors: list[str] = []
    if not name.strip():
        errors.append(_("Name is required."))
    prefixes, prefix_errors = parse_root_prefixes(root_prefixes)
    errors.extend(prefix_errors)
    if errors:
        return render(
            request,
            "partials/_reseau_form.html",
            {"reseau": reseau, "errors": errors},
            status_code=422,
        )

    before = {
        "name": reseau.name,
        "description": reseau.description,
        "notes": reseau.notes,
        "root_prefixes": reseau.root_prefixes,
        "default_locale": reseau.default_locale,
    }
    reseau.name = name.strip()
    reseau.description = description.strip() or None
    reseau.notes = notes.strip() or None
    reseau.root_prefixes = prefixes or None
    if default_locale in available_locales():
        reseau.default_locale = default_locale
    reseau.updated_at = utcnow()
    after = {
        "name": reseau.name,
        "description": reseau.description,
        "notes": reseau.notes,
        "root_prefixes": reseau.root_prefixes,
        "default_locale": reseau.default_locale,
    }
    session.add(reseau)
    await audit.record(
        session, user, "update", "reseau", reseau.id, audit.diff(before, after)
    )
    await session.commit()
    flash(request, _("Network settings saved."))
    return hx_refresh()
