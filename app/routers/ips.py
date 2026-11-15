"""CRUD IP + détail inline + pastille santé + check immédiat."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import IPAddress, IPStatus, Subnet, utcnow
from app.services import inventory
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


async def _get_ip(session: SessionDep, ip_id: int, with_monitors: bool = True) -> IPAddress:
    statement = select(IPAddress).where(IPAddress.id == ip_id)
    if with_monitors:
        statement = statement.options(selectinload(IPAddress.monitors))  # type: ignore[arg-type]
    ip = (await session.exec(statement)).first()
    if ip is None:
        raise HTTPException(status_code=404, detail=_("IP address not found."))
    return ip


def _parse_status(raw: str) -> IPStatus:
    try:
        return IPStatus(raw)
    except ValueError:
        return IPStatus.utilisee


@router.get("/subnets/{subnet_id}/ips/new")
async def ip_new_form(request: Request, user: ManagerUser, session: SessionDep, subnet_id: int):
    subnet = await session.get(Subnet, subnet_id)
    if subnet is None:
        raise HTTPException(status_code=404, detail=_("VLAN not found."))
    return render(request, "partials/_ip_form.html", {"subnet": subnet, "ip": None, "errors": []})


@router.get("/ips/{ip_id}/edit")
async def ip_edit_form(request: Request, user: ManagerUser, session: SessionDep, ip_id: int):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    subnet = await session.get(Subnet, ip.subnet_id)
    return render(request, "partials/_ip_form.html", {"subnet": subnet, "ip": ip, "errors": []})


@router.post("/subnets/{subnet_id}/ips")
async def create_ip(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    subnet_id: int,
    address: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "utilisee",
    hostname: Annotated[str, Form()] = "",
    mac: Annotated[str, Form()] = "",
    device_label: Annotated[str, Form()] = "",
    hardware: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
):
    subnet = await session.get(Subnet, subnet_id)
    if subnet is None:
        raise HTTPException(status_code=404, detail=_("VLAN not found."))
    try:
        ip = await inventory.create_ip(
            session,
            user,
            subnet,
            address=address,
            status=_parse_status(status),
            hostname=hostname,
            mac=mac,
            device_label=device_label,
            hardware=hardware,
            location=location,
            description=description,
        )
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_ip_form.html",
            {"subnet": subnet, "ip": None, "errors": exc.messages, "error_fields": exc.fields},
            status_code=422,
        )
    flash(request, _("Address %s created.") % ip.address)
    return hx_refresh()


@router.patch("/ips/{ip_id}")
async def update_ip(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    ip_id: int,
    address: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "utilisee",
    hostname: Annotated[str, Form()] = "",
    mac: Annotated[str, Form()] = "",
    device_label: Annotated[str, Form()] = "",
    hardware: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    subnet = await session.get(Subnet, ip.subnet_id)
    try:
        ip = await inventory.update_ip(
            session,
            user,
            ip,
            address=address,
            status=_parse_status(status),
            hostname=hostname,
            mac=mac,
            device_label=device_label,
            hardware=hardware,
            location=location,
            description=description,
        )
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_ip_form.html",
            {"subnet": subnet, "ip": ip, "errors": exc.messages, "error_fields": exc.fields},
            status_code=422,
        )
    flash(request, _("Address %s updated.") % ip.address)
    return hx_refresh()


@router.delete("/ips/{ip_id}")
async def delete_ip(request: Request, user: ManagerUser, session: SessionDep, ip_id: int):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    address = ip.address
    await inventory.delete_ip(session, user, ip)
    flash(request, _("Address %s deleted.") % address)
    return hx_refresh()


@router.get("/ips/{ip_id}")
async def ip_detail(request: Request, user: CurrentUser, session: SessionDep, ip_id: int):
    """Partial détail (accordéon inline dans la grille)."""
    ip = await _get_ip(session, ip_id)
    return render(request, "partials/_ip_detail.html", {"ip": ip})


@router.get("/ips/{ip_id}/health")
async def ip_health_cell(request: Request, user: CurrentUser, session: SessionDep, ip_id: int):
    """Partial pastille santé (polling HTMX)."""
    ip = await _get_ip(session, ip_id)
    return render(request, "partials/_health_cell.html", {"ip": ip})


@router.get("/ips/{ip_id}/row")
async def ip_row(request: Request, user: CurrentUser, session: SessionDep, ip_id: int):
    ip = await _get_ip(session, ip_id)
    return render(request, "partials/_ip_row.html", {"ip": ip})


@router.post("/ips/{ip_id}/check")
async def check_ip(request: Request, user: CurrentUser, session: SessionDep, ip_id: int):
    """Vérifie toutes les cibles actives de l'IP, renvoie la ligne mise à jour."""
    ip = await inventory.check_ip(session, user, ip_id)
    if ip is None:
        raise HTTPException(status_code=404, detail=_("IP address not found."))
    return render(request, "partials/_ip_row.html", {"ip": ip})


# -------------------------------------------------------------------------- Pause


@router.get("/ips/{ip_id}/pause")
async def pause_form(request: Request, user: ManagerUser, session: SessionDep, ip_id: int):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    return render(request, "partials/_pause_form.html", {"ip": ip, "form": None, "errors": []})


@router.post("/ips/{ip_id}/pause")
async def pause_ip(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    ip_id: int,
    reason: Annotated[str, Form()] = "",
    resume: Annotated[str, Form()] = "recovery",
):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    if resume == "keep" and ip.is_paused:
        until, until_recovery = ip.pause_until, ip.pause_until_recovery
    elif resume in inventory.PAUSE_DURATIONS:
        until, until_recovery = utcnow() + inventory.PAUSE_DURATIONS[resume], False
    else:
        until, until_recovery = None, resume != "manual"
    try:
        await inventory.pause_ip(session, user, ip, reason=reason, until=until, until_recovery=until_recovery)
    except inventory.ValidationFailed as exc:
        return render(
            request,
            "partials/_pause_form.html",
            {"ip": ip, "form": {"reason": reason, "resume": resume}, "errors": exc.messages, "error_fields": exc.fields},
            status_code=422,
        )
    flash(request, _("Address %s paused.") % ip.address)
    return hx_refresh()


@router.post("/ips/{ip_id}/resume")
async def resume_ip(request: Request, user: ManagerUser, session: SessionDep, ip_id: int):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    await inventory.resume_ip(session, user, ip)
    flash(request, _("Monitoring of %s resumed.") % ip.address)
    return hx_refresh()
