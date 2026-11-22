"""Édition du réseau singleton (manager)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request

from app import tls
from app.deps import ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import RESEAU_SINGLETON_ID, Reseau
from app.services import inventory, monitor
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])

DURATION_UNITS = {"minutes": 60, "hours": 3600, "days": 86400}


def _int_or_none(raw: str) -> int | None:
    """Champ numérique facultatif : vide → None (valeur d'instance), illisible → refusé par le service."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return -1


def _duration(raw: str, unit: str) -> int | None:
    value = _int_or_none(raw)
    if value is None or value < 0:
        return value
    return value * DURATION_UNITS.get(unit, 86400)


def _form_context(reseau: Reseau) -> dict:
    """Réglages du suivi pour le formulaire : valeurs affichées et valeurs d'instance (indices)."""
    dark = monitor.effective_monitoring(reseau).health_dark_red_seconds
    unit = next((u for u in ("days", "hours") if dark % DURATION_UNITS[u] == 0), "minutes")
    return {
        "reseau": reseau,
        "tracking": monitor.effective_monitoring(reseau),
        "instance": monitor.instance_monitoring(),
        "dark_value": max(1, round(dark / DURATION_UNITS[unit])),
        "dark_unit": unit,
        "limits": inventory.MONITORING_LIMITS,
        "tls_info": tls.current(),
    }


@router.get("/reseau/edit")
async def reseau_form(request: Request, user: ManagerUser, session: SessionDep):
    reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
    return render(request, "partials/_reseau_form.html", {**_form_context(reseau), "errors": []})


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
    default_check_interval: Annotated[str, Form()] = "",
    health_warn_intervals: Annotated[str, Form()] = "",
    health_red_failures: Annotated[str, Form()] = "",
    health_dark_red_value: Annotated[str, Form()] = "",
    health_dark_red_unit: Annotated[str, Form()] = "days",
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
            default_check_interval=_int_or_none(default_check_interval),
            health_warn_intervals=_int_or_none(health_warn_intervals),
            health_red_failures=_int_or_none(health_red_failures),
            health_dark_red_seconds=_duration(health_dark_red_value, health_dark_red_unit),
        )
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_reseau_form.html",
            {
                **_form_context(reseau),
                "errors": exc.messages,
                # Le seuil rouge foncé est saisi en « valeur + unité » : son champ porte un autre nom.
                "error_fields": [
                    "health_dark_red_value" if f == "health_dark_red_seconds" else f for f in exc.fields
                ],
            },
            status_code=422,
        )
    flash(request, _("Network settings saved."))
    return hx_refresh()
