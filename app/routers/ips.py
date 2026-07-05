"""CRUD IP + détail inline + pastille santé + check immédiat."""

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import IPAddress, IPStatus, Subnet, utcnow
from app.services import audit, ipam
from app.services.monitor import check_target_now
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


def _ip_dict(ip: IPAddress) -> dict:
    return {
        "address": ip.address,
        "hostname": ip.hostname,
        "mac": ip.mac,
        "device_label": ip.device_label,
        "description": ip.description,
        "status": ip.status.value,
    }


def _parse_status(raw: str) -> IPStatus:
    try:
        return IPStatus(raw)
    except ValueError:
        return IPStatus.utilisee


async def _validate_ip_form(
    session: SessionDep,
    subnet: Subnet,
    address: str,
    mac: str,
    exclude_id: int | None = None,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    parsed = None
    normalized_mac = None
    existing = list(
        (await session.exec(select(IPAddress).where(IPAddress.subnet_id == subnet.id))).all()
    )
    try:
        parsed = ipam.validate_ip(address, subnet, existing, exclude_id=exclude_id)
    except ipam.ConflictError as exc:
        errors.append(exc.message)
    try:
        normalized_mac = ipam.normalize_mac(mac or None)
    except ipam.ConflictError as exc:
        errors.append(exc.message)
    return {"address": parsed, "mac": normalized_mac}, errors


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
    description: Annotated[str, Form()] = "",
):
    subnet = await session.get(Subnet, subnet_id)
    if subnet is None:
        raise HTTPException(status_code=404, detail=_("VLAN not found."))
    values, errors = await _validate_ip_form(session, subnet, address, mac)
    if errors:
        return render(
            request,
            "partials/_ip_form.html",
            {"subnet": subnet, "ip": None, "errors": errors},
            status_code=422,
        )
    ip = IPAddress(
        subnet_id=subnet_id,
        address=str(values["address"]),
        address_int=int(values["address"]),
        hostname=hostname.strip() or None,
        mac=values["mac"],
        device_label=device_label.strip() or None,
        description=description.strip() or None,
        status=_parse_status(status),
    )
    session.add(ip)
    await session.flush()
    await audit.record(session, user, "create", "ip", ip.id, audit.diff({}, _ip_dict(ip)))
    await session.commit()
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
    description: Annotated[str, Form()] = "",
):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    subnet = await session.get(Subnet, ip.subnet_id)
    values, errors = await _validate_ip_form(session, subnet, address, mac, exclude_id=ip_id)
    if errors:
        return render(
            request,
            "partials/_ip_form.html",
            {"subnet": subnet, "ip": ip, "errors": errors},
            status_code=422,
        )
    before = _ip_dict(ip)
    ip.address = str(values["address"])
    ip.address_int = int(values["address"])
    ip.hostname = hostname.strip() or None
    ip.mac = values["mac"]
    ip.device_label = device_label.strip() or None
    ip.description = description.strip() or None
    ip.status = _parse_status(status)
    ip.updated_at = utcnow()
    session.add(ip)
    await audit.record(session, user, "update", "ip", ip.id, audit.diff(before, _ip_dict(ip)))
    await session.commit()
    flash(request, _("Address %s updated.") % ip.address)
    return hx_refresh()


@router.delete("/ips/{ip_id}")
async def delete_ip(request: Request, user: ManagerUser, session: SessionDep, ip_id: int):
    ip = await _get_ip(session, ip_id, with_monitors=False)
    before = _ip_dict(ip)
    address = ip.address
    await session.delete(ip)  # cascade : cibles
    await audit.record(session, user, "delete", "ip", ip_id, audit.diff(before, {}))
    await session.commit()
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
    ip = await _get_ip(session, ip_id)
    for target in ip.monitors:
        if target.enabled:
            await check_target_now(session, target)
    await audit.record(session, user, "check", "ip", ip.id)
    await session.commit()
    ip = await _get_ip(session, ip_id)
    return render(request, "partials/_ip_row.html", {"ip": ip})
