"""CRUD des cibles de suivi + check immédiat par cible."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import IPAddress, MonitorTarget, Protocol
from app.services import inventory
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])

async def _get_target(session: SessionDep, monitor_id: int) -> MonitorTarget:
    target = await session.get(MonitorTarget, monitor_id)
    if target is None:
        raise HTTPException(status_code=404, detail=_("Monitor target not found."))
    return target


def _parse_form(protocol: str, port: str, interval: str) -> dict:
    """Champs texte du formulaire → valeurs typées (la validation est dans le service)."""
    try:
        proto = Protocol(protocol)
    except ValueError:
        proto = Protocol.tcp
    try:
        port_value = int(port.strip())
    except ValueError:
        port_value = None
    try:
        interval_value = int(interval.strip()) if interval.strip() else None
    except ValueError:
        interval_value = -1  # hors plage → refusé par le service
    return {"protocol": proto, "port": port_value, "interval_seconds": interval_value}


@router.get("/ips/{ip_id}/monitors/new")
async def monitor_new_form(request: Request, user: ManagerUser, session: SessionDep, ip_id: int):
    ip = await session.get(IPAddress, ip_id)
    if ip is None:
        raise HTTPException(status_code=404, detail=_("IP address not found."))
    return render(request, "partials/_monitor_form.html", {"ip": ip, "target": None, "errors": []})


@router.get("/monitors/{monitor_id}/edit")
async def monitor_edit_form(request: Request, user: ManagerUser, session: SessionDep, monitor_id: int):
    target = await _get_target(session, monitor_id)
    ip = await session.get(IPAddress, target.ip_id)
    return render(request, "partials/_monitor_form.html", {"ip": ip, "target": target, "errors": []})


@router.post("/ips/{ip_id}/monitors")
async def create_monitor(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    ip_id: int,
    protocol: Annotated[str, Form()] = "tcp",
    port: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
    interval_seconds: Annotated[str, Form()] = "",
    enabled: Annotated[str, Form()] = "on",
):
    ip = await session.get(IPAddress, ip_id)
    if ip is None:
        raise HTTPException(status_code=404, detail=_("IP address not found."))
    try:
        await inventory.create_monitor(
            session,
            user,
            ip,
            **_parse_form(protocol, port, interval_seconds),
            label=label,
            enabled=enabled == "on",
        )
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_monitor_form.html",
            {"ip": ip, "target": None, "errors": exc.messages, "error_fields": exc.fields},
            status_code=422,
        )
    flash(request, _("Monitor target added on %s.") % ip.address)
    return hx_refresh()


@router.patch("/monitors/{monitor_id}")
async def update_monitor(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    monitor_id: int,
    protocol: Annotated[str, Form()] = "tcp",
    port: Annotated[str, Form()] = "",
    label: Annotated[str, Form()] = "",
    interval_seconds: Annotated[str, Form()] = "",
    enabled: Annotated[str, Form()] = "",
):
    target = await _get_target(session, monitor_id)
    ip = await session.get(IPAddress, target.ip_id)
    try:
        await inventory.update_monitor(
            session,
            user,
            target,
            **_parse_form(protocol, port, interval_seconds),
            label=label,
            enabled=enabled == "on",
        )
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_monitor_form.html",
            {"ip": ip, "target": target, "errors": exc.messages, "error_fields": exc.fields},
            status_code=422,
        )
    flash(request, _("Monitor target updated."))
    return hx_refresh()


@router.delete("/monitors/{monitor_id}")
async def delete_monitor(request: Request, user: ManagerUser, session: SessionDep, monitor_id: int):
    target = await _get_target(session, monitor_id)
    await inventory.delete_monitor(session, user, target)
    flash(request, _("Monitor target deleted."))
    return hx_refresh()


@router.post("/monitors/{monitor_id}/check")
async def check_monitor(request: Request, user: CurrentUser, session: SessionDep, monitor_id: int):
    """Check immédiat d'une cible, renvoie la ligne cible mise à jour."""
    target = await _get_target(session, monitor_id)
    target = await inventory.check_monitor(session, user, target)
    ip = await session.get(IPAddress, target.ip_id)
    return render(request, "partials/_monitor_row.html", {"target": target, "ip": ip})
