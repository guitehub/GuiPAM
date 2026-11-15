"""CRUD VLAN + vue VLAN + vue plan + filtres de la grille des IP."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import IPAddress, IPStatus, MonitorTarget, Subnet, utcnow
from app.services import inventory, ipam
from app.services.monitor import SEVERITY, Health, ip_health
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


async def _get_subnet(session: SessionDep, subnet_id: int) -> Subnet:
    subnet = await session.get(Subnet, subnet_id)
    if subnet is None:
        raise HTTPException(status_code=404, detail=_("VLAN not found."))
    return subnet


def _parse_vlan_id(raw: str) -> int | None:
    """Tag saisi dans le formulaire ; une valeur non numérique devient 0 (hors plage → refusée)."""
    value = raw.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return 0


@router.get("/subnets/new")
async def subnet_new_form(request: Request, user: ManagerUser):
    return render(request, "partials/_subnet_form.html", {"subnet": None, "errors": []})


@router.get("/subnets/{subnet_id}/edit")
async def subnet_edit_form(request: Request, user: ManagerUser, session: SessionDep, subnet_id: int):
    subnet = await _get_subnet(session, subnet_id)
    return render(request, "partials/_subnet_form.html", {"subnet": subnet, "errors": []})


@router.post("/subnets")
async def create_subnet(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    vlan_id: Annotated[str, Form()] = "",
    cidr: Annotated[str, Form()] = "",
    gateway: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    try:
        subnet = await inventory.create_subnet(
            session,
            user,
            name=name,
            cidr=cidr,
            vlan_id=_parse_vlan_id(vlan_id),
            gateway=gateway,
            description=description,
            notes=notes,
        )
    except inventory.ValidationFailed as exc:
        return render(
            request, "partials/_subnet_form.html", {"subnet": None, "errors": exc.messages, "error_fields": exc.fields}, status_code=422
        )
    flash(request, _("VLAN “%s” created.") % subnet.name)
    return hx_refresh()


@router.patch("/subnets/{subnet_id}")
async def update_subnet(
    request: Request,
    user: ManagerUser,
    session: SessionDep,
    subnet_id: int,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    vlan_id: Annotated[str, Form()] = "",
    cidr: Annotated[str, Form()] = "",
    gateway: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    subnet = await _get_subnet(session, subnet_id)
    try:
        subnet = await inventory.update_subnet(
            session,
            user,
            subnet,
            name=name,
            cidr=cidr,
            vlan_id=_parse_vlan_id(vlan_id),
            gateway=gateway,
            description=description,
            notes=notes,
        )
    except inventory.ValidationFailed as exc:
        return render(
            request, "partials/_subnet_form.html", {"subnet": subnet, "errors": exc.messages, "error_fields": exc.fields}, status_code=422
        )
    flash(request, _("VLAN “%s” updated.") % subnet.name)
    return hx_refresh()


@router.delete("/subnets/{subnet_id}")
async def delete_subnet(request: Request, user: ManagerUser, session: SessionDep, subnet_id: int):
    subnet = await _get_subnet(session, subnet_id)
    name = subnet.name
    await inventory.delete_subnet(session, user, subnet)
    flash(request, _("VLAN “%s” deleted (with its addresses and targets).") % name)
    response = hx_refresh()
    response.headers["HX-Redirect"] = "/"
    return response


def _filter_ips(
    ips: list[IPAddress],
    status: str,
    health_filter: str,
    q: str,
    show_free: bool,
) -> list[IPAddress]:
    now = utcnow()
    result = []
    for ip in ips:
        if status and ip.status.value != status:
            continue
        if not show_free and ip.status == IPStatus.libre and not status:
            continue
        h = ip_health(ip.monitors, now)
        if health_filter:
            if health_filter == "none" and h is not None:
                continue
            if health_filter != "none" and (h is None or h.value != health_filter):
                continue
        if q:
            needle = q.lower()
            haystack = " ".join(
                filter(
                    None,
                    [ip.address, ip.hostname, ip.device_label, ip.hardware, ip.location, ip.mac, ip.description],
                )
            ).lower()
            if needle not in haystack:
                continue
        result.append(ip)
    result.sort(key=lambda ip: ip.address_int)
    return result


async def _load_subnet_ips(session: SessionDep, subnet_id: int) -> list[IPAddress]:
    result = await session.exec(
        select(IPAddress)
        .where(IPAddress.subnet_id == subnet_id)
        .options(selectinload(IPAddress.monitors))  # type: ignore[arg-type]
    )
    return list(result.all())


@router.get("/subnets/{subnet_id}")
async def subnet_page(
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    subnet_id: int,
    status: Annotated[str, Query()] = "",
    health: Annotated[str, Query()] = "",
    q: Annotated[str, Query()] = "",
    show_free: Annotated[bool, Query()] = True,
):
    subnet = await _get_subnet(session, subnet_id)
    ips = await _load_subnet_ips(session, subnet_id)
    filtered = _filter_ips(ips, status, health, q, show_free)
    context = {
        "subnet": subnet,
        "stats": ipam.subnet_stats(subnet, len(ips)),
        "ips": filtered,
        "total_ips": len(ips),
        "filters": {"status": status, "health": health, "q": q, "show_free": show_free},
    }
    if request.headers.get("hx-request") and request.headers.get("hx-target") == "ip-rows":
        return render(request, "partials/_ip_rows.html", context)
    return render(request, "subnet.html", context)


@router.get("/subnets/{subnet_id}/plan")
async def subnet_plan(request: Request, user: CurrentUser, session: SessionDep, subnet_id: int):
    subnet = await _get_subnet(session, subnet_id)
    ips = await _load_subnet_ips(session, subnet_id)
    entries, truncated = ipam.build_plan(subnet, ips)
    return render(
        request,
        "subnet_plan.html",
        {
            "subnet": subnet,
            "stats": ipam.subnet_stats(subnet, len(ips)),
            "entries": entries,
            "truncated": truncated,
            "plan_max": ipam.PLAN_MAX_HOSTS,
        },
    )
