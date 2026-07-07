"""CRUD VLAN + vue VLAN + vue plan + filtres de la grille des IP."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import IPAddress, IPStatus, MonitorTarget, Subnet, utcnow
from app.services import audit, ipam
from app.services.monitor import SEVERITY, Health, ip_health
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])


async def _get_subnet(session: SessionDep, subnet_id: int) -> Subnet:
    subnet = await session.get(Subnet, subnet_id)
    if subnet is None:
        raise HTTPException(status_code=404, detail=_("VLAN not found."))
    return subnet


def _subnet_dict(subnet: Subnet) -> dict:
    return {
        "name": subnet.name,
        "description": subnet.description,
        "vlan_id": subnet.vlan_id,
        "cidr": subnet.cidr,
        "gateway": subnet.gateway,
        "notes": subnet.notes,
    }


def _parse_vlan_id(raw: str, errors: list[str]) -> int | None:
    value = raw.strip()
    if not value:
        return None
    try:
        vlan_id = int(value)
    except ValueError:
        errors.append(_("VLAN tag must be a number between 1 and 4094."))
        return None
    if not 1 <= vlan_id <= 4094:
        errors.append(_("VLAN tag must be a number between 1 and 4094."))
        return None
    return vlan_id


async def _validate_subnet_form(
    session: SessionDep,
    name: str,
    vlan_id_raw: str,
    cidr: str,
    gateway: str,
    exclude_id: int | None = None,
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if not name.strip():
        errors.append(_("Name is required."))
    vlan_id = _parse_vlan_id(vlan_id_raw, errors)
    existing = list((await session.exec(select(Subnet))).all())
    network = None
    try:
        network = ipam.validate_subnet(cidr, gateway or None, existing, exclude_id=exclude_id)
    except ipam.ConflictError as exc:
        errors.append(exc.message)
    values = {
        "name": name.strip(),
        "vlan_id": vlan_id,
        "cidr": str(network) if network else cidr.strip(),
        "gateway": gateway.strip() or None,
    }
    return values, errors


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
    values, errors = await _validate_subnet_form(session, name, vlan_id, cidr, gateway)
    if errors:
        return render(
            request, "partials/_subnet_form.html", {"subnet": None, "errors": errors}, status_code=422
        )
    subnet = Subnet(
        name=values["name"],
        description=description.strip() or None,
        vlan_id=values["vlan_id"],
        cidr=values["cidr"],
        gateway=values["gateway"],
        notes=notes.strip() or None,
    )
    session.add(subnet)
    await session.flush()
    await audit.record(session, user, "create", "subnet", subnet.id, audit.diff({}, _subnet_dict(subnet)))
    await session.commit()
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
    values, errors = await _validate_subnet_form(
        session, name, vlan_id, cidr, gateway, exclude_id=subnet_id
    )
    if not errors and values["cidr"] != subnet.cidr:
        # Changement de CIDR : toutes les IP existantes doivent rester dedans.
        result = await session.exec(select(IPAddress).where(IPAddress.subnet_id == subnet_id))
        import ipaddress as ipa

        network = ipa.ip_network(values["cidr"])
        outside = [ip.address for ip in result.all() if ipa.ip_address(ip.address) not in network]
        if outside:
            errors.append(
                _("Cannot change CIDR: %(count)d addresses would fall outside (e.g. %(example)s).")
                % {"count": len(outside), "example": outside[0]}
            )
    if errors:
        return render(
            request, "partials/_subnet_form.html", {"subnet": subnet, "errors": errors}, status_code=422
        )

    before = _subnet_dict(subnet)
    subnet.name = values["name"]
    subnet.description = description.strip() or None
    subnet.vlan_id = values["vlan_id"]
    subnet.cidr = values["cidr"]
    subnet.gateway = values["gateway"]
    subnet.notes = notes.strip() or None
    subnet.updated_at = utcnow()
    session.add(subnet)
    await audit.record(session, user, "update", "subnet", subnet.id, audit.diff(before, _subnet_dict(subnet)))
    await session.commit()
    flash(request, _("VLAN “%s” updated.") % subnet.name)
    return hx_refresh()


@router.delete("/subnets/{subnet_id}")
async def delete_subnet(request: Request, user: ManagerUser, session: SessionDep, subnet_id: int):
    subnet = await _get_subnet(session, subnet_id)
    before = _subnet_dict(subnet)
    name = subnet.name
    await session.delete(subnet)  # cascade : IP + cibles
    await audit.record(session, user, "delete", "subnet", subnet_id, audit.diff(before, {}))
    await session.commit()
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
