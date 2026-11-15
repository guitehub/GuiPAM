"""Édition du réseau singleton (manager)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request

from app.deps import ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import RESEAU_SINGLETON_ID, Reseau
from app.services import inventory
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


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
    try:
        await inventory.update_reseau(
            session,
            user,
            reseau,
            name=name,
            description=description,
            notes=notes,
            root_prefixes=root_prefixes.replace(",", "\n").splitlines(),
            default_locale=default_locale,
        )
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_reseau_form.html",
            {"reseau": reseau, "errors": exc.messages, "error_fields": exc.fields},
            status_code=422,
        )
    flash(request, _("Network settings saved."))
    return hx_refresh()
