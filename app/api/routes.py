"""Routes de l'API v1. Toute la logique métier est dans `app/services/inventory.py`."""

import ipaddress
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app import __version__
from app.api.auth import ApiError, Reader, Writer
from app.api.schemas import (
    AuditOut,
    ErrorResponse,
    IpAllocate,
    IpCreate,
    IpOut,
    IpUpdate,
    MonitorCreate,
    MonitorOut,
    MonitorUpdate,
    NetworkOut,
    NetworkUpdate,
    NextFree,
    Page,
    Problem,
    Summary,
    VlanCreate,
    VlanOut,
    VlanUpdate,
    WhoAmI,
)
from app.deps import SessionDep
from app.i18n import gettext as _
from app.models import (
    RESEAU_SINGLETON_ID,
    AuditLog,
    IPAddress,
    IPStatus,
    MonitorTarget,
    Protocol,
    Reseau,
    Subnet,
)
from app.routers.dashboard import load_dashboard
from app.routers.subnets import _filter_ips
from app.services import inventory, ipam
from app.services.monitor import SEVERITY, Health, health, ip_health
from app.templating import ip_last_checked

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing, invalid, expired or revoked API key."},
    422: {"model": ErrorResponse, "description": "Validation error or business rule violated."},
}
WRITE_ERRORS = {**ERRORS, 403: {"model": ErrorResponse, "description": "The API key is read-only."}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Resource not found."}}

router = APIRouter(responses=ERRORS)


# ------------------------------------------------------------------ Sérialisation


def monitor_out(target: MonitorTarget) -> MonitorOut:
    return MonitorOut(
        id=target.id,
        ip_id=target.ip_id,
        protocol=target.protocol,
        port=target.port,
        label=target.label,
        enabled=target.enabled,
        interval_seconds=target.interval_seconds,
        last_status=target.last_status,
        last_checked_at=target.last_checked_at,
        last_ok_at=target.last_ok_at,
        latency_ms=target.latency_ms,
        consecutive_failures=target.consecutive_failures,
        health=health(target),
    )


def ip_out(ip: IPAddress) -> IpOut:
    return IpOut(
        id=ip.id,
        vlan_id=ip.subnet_id,
        address=ip.address,
        status=ip.status,
        hostname=ip.hostname,
        mac=ip.mac,
        device_label=ip.device_label,
        hardware=ip.hardware,
        location=ip.location,
        description=ip.description,
        health=ip_health(ip.monitors),
        last_checked_at=ip_last_checked(ip),
        monitors=[monitor_out(t) for t in ip.monitors],
        created_at=ip.created_at,
        updated_at=ip.updated_at,
    )


def vlan_out(subnet: Subnet, ips: list[IPAddress]) -> VlanOut:
    stats = ipam.subnet_stats(subnet, len(ips))
    worst: Health | None = None
    for ip in ips:
        h = ip_health(ip.monitors)
        if h is not None and (worst is None or SEVERITY[h] > SEVERITY[worst]):
            worst = h
    return VlanOut(
        id=subnet.id,
        name=subnet.name,
        description=subnet.description,
        vlan_tag=subnet.vlan_id,
        cidr=subnet.cidr,
        gateway=subnet.gateway,
        notes=subnet.notes,
        netmask=stats.netmask,
        first_usable=stats.first_usable,
        last_usable=stats.last_usable,
        capacity=stats.capacity,
        recorded_ips=stats.used,
        occupancy_percent=stats.occupancy_percent,
        health=worst,
        created_at=subnet.created_at,
        updated_at=subnet.updated_at,
    )


# ----------------------------------------------------------------------- Chargement

_WITH_MONITORS = selectinload(IPAddress.monitors)  # type: ignore[arg-type]


def not_found(message: str) -> ApiError:
    return ApiError(404, "not_found", message)


async def load_vlan(session: SessionDep, vlan_id: int) -> Subnet:
    subnet = await session.get(Subnet, vlan_id)
    if subnet is None:
        raise not_found(_("VLAN not found."))
    return subnet


async def load_vlan_ips(session: SessionDep, vlan_id: int) -> list[IPAddress]:
    result = await session.exec(
        select(IPAddress).where(IPAddress.subnet_id == vlan_id).options(_WITH_MONITORS)
    )
    return list(result.all())


async def load_ip(session: SessionDep, ip_id: int) -> IPAddress:
    result = await session.exec(
        select(IPAddress)
        .where(IPAddress.id == ip_id)
        .options(_WITH_MONITORS)
        .execution_options(populate_existing=True)
    )
    ip = result.first()
    if ip is None:
        raise not_found(_("IP address not found."))
    return ip


async def load_monitor(session: SessionDep, monitor_id: int) -> MonitorTarget:
    target = await session.get(MonitorTarget, monitor_id)
    if target is None:
        raise not_found(_("Monitor target not found."))
    return target


def changes(body: Any, required: tuple[str, ...] = ()) -> dict[str, Any]:
    """Champs réellement envoyés dans un PATCH ; un null sur un champ obligatoire = inchangé."""
    data = body.model_dump(exclude_unset=True)
    return {k: v for k, v in data.items() if not (v is None and k in required)}


# --------------------------------------------------------------------------- Méta


@router.get("/whoami", tags=["meta"], summary="Identify the calling key and its rights")
async def whoami(principal: Reader) -> WhoAmI:
    return WhoAmI(
        service_account=principal.account.name,
        role=principal.account.role,
        key_name=principal.key.name,
        key_prefix=principal.key.prefix,
        key_scope=principal.key.scope,
        can_write=principal.can_write,
        expires_at=principal.key.expires_at,
        version=__version__,
    )


@router.get("/summary", tags=["meta"], summary="Global counters (dashboard)")
async def summary(principal: Reader, session: SessionDep) -> Summary:
    summaries, _attention, data = await load_dashboard(session)
    return Summary(
        vlans=len(summaries),
        recorded_ips=data.total,
        used=data.used,
        reserved=data.reserved,
        free=data.free,
        down=data.red_count,
    )


@router.get("/network", tags=["network"], summary="Get the network managed by this instance")
async def get_network(principal: Reader, session: SessionDep) -> NetworkOut:
    reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
    return NetworkOut.model_validate(reseau, from_attributes=True)


@router.patch("/network", tags=["network"], summary="Update the network settings", responses=WRITE_ERRORS)
async def update_network(principal: Writer, session: SessionDep, body: NetworkUpdate) -> NetworkOut:
    reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
    values = {**inventory.reseau_dict(reseau), **changes(body, required=("name", "default_locale"))}
    reseau = await inventory.update_reseau(session, principal.actor, reseau, **values)
    return NetworkOut.model_validate(reseau, from_attributes=True)


# --------------------------------------------------------------------------- VLAN


@router.get("/vlans", tags=["vlans"], summary="List VLANs with occupancy and health")
async def list_vlans(principal: Reader, session: SessionDep) -> list[VlanOut]:
    result = await session.exec(
        select(Subnet).options(selectinload(Subnet.ips).selectinload(IPAddress.monitors))  # type: ignore[arg-type]
    )
    subnets = sorted(result.all(), key=lambda s: int(ipaddress.ip_network(s.cidr).network_address))
    return [vlan_out(subnet, subnet.ips) for subnet in subnets]


@router.post(
    "/vlans", tags=["vlans"], summary="Create a VLAN", status_code=201, responses=WRITE_ERRORS
)
async def create_vlan(principal: Writer, session: SessionDep, body: VlanCreate) -> VlanOut:
    data = body.model_dump()
    data["vlan_id"] = data.pop("vlan_tag")
    subnet = await inventory.create_subnet(session, principal.actor, **data)
    return vlan_out(subnet, [])


@router.get("/vlans/{vlan_id}", tags=["vlans"], summary="Get a VLAN", responses=NOT_FOUND)
async def get_vlan(principal: Reader, session: SessionDep, vlan_id: int) -> VlanOut:
    subnet = await load_vlan(session, vlan_id)
    return vlan_out(subnet, await load_vlan_ips(session, vlan_id))


@router.patch(
    "/vlans/{vlan_id}",
    tags=["vlans"],
    summary="Update a VLAN (only the fields sent are changed)",
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def update_vlan(principal: Writer, session: SessionDep, vlan_id: int, body: VlanUpdate) -> VlanOut:
    subnet = await load_vlan(session, vlan_id)
    data = changes(body, required=("name", "cidr"))
    if "vlan_tag" in data:
        data["vlan_id"] = data.pop("vlan_tag")
    subnet = await inventory.update_subnet(
        session, principal.actor, subnet, **{**inventory.subnet_dict(subnet), **data}
    )
    return vlan_out(subnet, await load_vlan_ips(session, vlan_id))


@router.delete(
    "/vlans/{vlan_id}",
    tags=["vlans"],
    summary="Delete a VLAN with all its addresses and monitor targets",
    status_code=204,
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def delete_vlan(principal: Writer, session: SessionDep, vlan_id: int) -> Response:
    subnet = await load_vlan(session, vlan_id)
    await inventory.delete_subnet(session, principal.actor, subnet)
    return Response(status_code=204)


# ----------------------------------------------------------------------------- IP

StatusFilter = Annotated[IPStatus | None, Query(description="Filter by status.")]
HealthFilter = Annotated[
    str | None,
    Query(
        pattern="^(ok|unknown|warn|red|dark_red|none)$",
        description="Filter by health; `none` = addresses without any enabled monitor target.",
    ),
]
SearchFilter = Annotated[
    str | None,
    Query(description="Case-insensitive search in address, hostname, MAC, device label, hardware, location, description."),
]


def paginate(ips: list[IPAddress], limit: int, offset: int) -> Page[IpOut]:
    return Page[IpOut](
        items=[ip_out(ip) for ip in ips[offset : offset + limit]],
        total=len(ips),
        limit=limit,
        offset=offset,
    )


@router.get("/ips", tags=["ips"], summary="Search IP addresses across all VLANs")
async def list_ips(
    principal: Reader,
    session: SessionDep,
    q: SearchFilter = None,
    status: StatusFilter = None,
    health: HealthFilter = None,
    address: Annotated[str | None, Query(description="Exact address match.")] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IpOut]:
    statement = select(IPAddress).options(_WITH_MONITORS)
    if address:
        statement = statement.where(IPAddress.address == address.strip())
    ips = list((await session.exec(statement)).all())
    filtered = _filter_ips(ips, status.value if status else "", health or "", q or "", True)
    return paginate(filtered, limit, offset)


@router.get(
    "/vlans/{vlan_id}/ips", tags=["ips"], summary="List the IP addresses of a VLAN", responses=NOT_FOUND
)
async def list_vlan_ips(
    principal: Reader,
    session: SessionDep,
    vlan_id: int,
    q: SearchFilter = None,
    status: StatusFilter = None,
    health: HealthFilter = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IpOut]:
    await load_vlan(session, vlan_id)
    ips = await load_vlan_ips(session, vlan_id)
    filtered = _filter_ips(ips, status.value if status else "", health or "", q or "", True)
    return paginate(filtered, limit, offset)


@router.post(
    "/vlans/{vlan_id}/ips",
    tags=["ips"],
    summary="Record a specific IP address in a VLAN",
    status_code=201,
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def create_ip(principal: Writer, session: SessionDep, vlan_id: int, body: IpCreate) -> IpOut:
    subnet = await load_vlan(session, vlan_id)
    ip = await inventory.create_ip(session, principal.actor, subnet, **body.model_dump())
    return ip_out(await load_ip(session, ip.id))


@router.get(
    "/vlans/{vlan_id}/next-free",
    tags=["ips"],
    summary="Peek at the next free address of a VLAN (does not reserve it)",
    responses={**NOT_FOUND, 409: {"model": ErrorResponse, "description": "The VLAN is full."}},
)
async def next_free_ip(principal: Reader, session: SessionDep, vlan_id: int) -> NextFree:
    subnet = await load_vlan(session, vlan_id)
    found = inventory.next_free_address(subnet, await load_vlan_ips(session, vlan_id))
    if found is None:
        raise ApiError(409, "subnet_full", _("No free address left in subnet %s.") % subnet.cidr)
    return NextFree(address=str(ipaddress.ip_address(found[0])))


@router.post(
    "/vlans/{vlan_id}/allocate",
    tags=["ips"],
    summary="Allocate the next free address of a VLAN and reserve it",
    description=(
        "Atomically picks the lowest free address of the VLAN and records it with the given "
        "fields (status `reservee` by default). Free = usable address that is not recorded, or "
        "recorded with status `libre`; the VLAN gateway is never returned. Two concurrent calls "
        "never get the same address. Returns 409 `subnet_full` when nothing is left."
    ),
    status_code=201,
    responses={
        **WRITE_ERRORS,
        **NOT_FOUND,
        409: {"model": ErrorResponse, "description": "The VLAN is full."},
    },
)
async def allocate_ip(principal: Writer, session: SessionDep, vlan_id: int, body: IpAllocate) -> IpOut:
    ip = await inventory.allocate_ip(session, principal.actor, vlan_id, **body.model_dump())
    if ip is None:
        raise not_found(_("VLAN not found."))
    return ip_out(await load_ip(session, ip.id))


@router.get("/ips/{ip_id}", tags=["ips"], summary="Get an IP address", responses=NOT_FOUND)
async def get_ip(principal: Reader, session: SessionDep, ip_id: int) -> IpOut:
    return ip_out(await load_ip(session, ip_id))


@router.patch(
    "/ips/{ip_id}",
    tags=["ips"],
    summary="Update an IP address (only the fields sent are changed)",
    description="To release an address, either set `status` to `libre` or delete it.",
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def update_ip(principal: Writer, session: SessionDep, ip_id: int, body: IpUpdate) -> IpOut:
    ip = await load_ip(session, ip_id)
    values = {**inventory.ip_dict(ip), **changes(body, required=("address", "status"))}
    values["status"] = IPStatus(values["status"])
    await inventory.update_ip(session, principal.actor, ip, **values)
    return ip_out(await load_ip(session, ip_id))


@router.delete(
    "/ips/{ip_id}",
    tags=["ips"],
    summary="Delete an IP address and its monitor targets",
    status_code=204,
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def delete_ip(principal: Writer, session: SessionDep, ip_id: int) -> Response:
    ip = await load_ip(session, ip_id)
    await inventory.delete_ip(session, principal.actor, ip)
    return Response(status_code=204)


# -------------------------------------------------------------------- Supervision


@router.get(
    "/problems",
    tags=["monitoring"],
    summary="What is down right now",
    description="IP addresses whose health is `red` or `dark_red`, worst first (same as the dashboard panel).",
)
async def list_problems(principal: Reader, session: SessionDep) -> list[Problem]:
    _summaries, attention, _data = await load_dashboard(session)
    return [
        Problem(
            health=item.health,
            last_ok_at=item.last_ok_at,
            vlan_id=item.subnet.id,
            vlan_name=item.subnet.name,
            ip=ip_out(item.ip),
        )
        for item in attention
    ]


@router.post(
    "/ips/{ip_id}/check",
    tags=["monitoring"],
    summary="Run all enabled monitor targets of an IP now",
    description="Allowed with a read-only key, like the “Check” button for read-only users.",
    responses=NOT_FOUND,
)
async def check_ip(principal: Reader, session: SessionDep, ip_id: int) -> IpOut:
    ip = await inventory.check_ip(session, principal.actor, ip_id)
    if ip is None:
        raise not_found(_("IP address not found."))
    return ip_out(ip)


@router.post(
    "/ips/{ip_id}/monitors",
    tags=["monitoring"],
    summary="Add a monitor target (TCP port or ICMP ping) to an IP",
    status_code=201,
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def create_monitor(principal: Writer, session: SessionDep, ip_id: int, body: MonitorCreate) -> MonitorOut:
    ip = await load_ip(session, ip_id)
    return monitor_out(await inventory.create_monitor(session, principal.actor, ip, **body.model_dump()))


@router.get("/monitors/{monitor_id}", tags=["monitoring"], summary="Get a monitor target", responses=NOT_FOUND)
async def get_monitor(principal: Reader, session: SessionDep, monitor_id: int) -> MonitorOut:
    return monitor_out(await load_monitor(session, monitor_id))


@router.patch(
    "/monitors/{monitor_id}",
    tags=["monitoring"],
    summary="Update a monitor target (only the fields sent are changed)",
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def update_monitor(
    principal: Writer, session: SessionDep, monitor_id: int, body: MonitorUpdate
) -> MonitorOut:
    target = await load_monitor(session, monitor_id)
    values = {
        **inventory.target_dict(target),
        **changes(body, required=("protocol", "enabled", "interval_seconds")),
    }
    values["protocol"] = Protocol(values["protocol"])
    return monitor_out(await inventory.update_monitor(session, principal.actor, target, **values))


@router.delete(
    "/monitors/{monitor_id}",
    tags=["monitoring"],
    summary="Delete a monitor target",
    status_code=204,
    responses={**WRITE_ERRORS, **NOT_FOUND},
)
async def delete_monitor(principal: Writer, session: SessionDep, monitor_id: int) -> Response:
    target = await load_monitor(session, monitor_id)
    await inventory.delete_monitor(session, principal.actor, target)
    return Response(status_code=204)


@router.post(
    "/monitors/{monitor_id}/check",
    tags=["monitoring"],
    summary="Run one monitor target now",
    description="Allowed with a read-only key.",
    responses=NOT_FOUND,
)
async def check_monitor(principal: Reader, session: SessionDep, monitor_id: int) -> MonitorOut:
    target = await load_monitor(session, monitor_id)
    return monitor_out(await inventory.check_monitor(session, principal.actor, target))


# -------------------------------------------------------------------------- Audit


@router.get("/audit", tags=["audit"], summary="Read the audit log, newest first")
async def list_audit(
    principal: Reader,
    session: SessionDep,
    action: Annotated[str | None, Query(description="create, update, delete, login, check, import, export")] = None,
    entity_type: Annotated[
        str | None, Query(description="reseau, subnet (= VLAN), ip, monitor, user, service_account, api_key")
    ] = None,
    entity_id: int | None = None,
    username: Annotated[str | None, Query(description="Substring of the user / service-account name.")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[AuditOut]:
    statement = select(AuditLog)
    if action:
        statement = statement.where(AuditLog.action == action)
    if entity_type:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditLog.entity_id == entity_id)
    if username:
        statement = statement.where(AuditLog.username.contains(username))  # type: ignore[attr-defined]
    total = (await session.exec(select(func.count()).select_from(statement.subquery()))).one()
    rows = await session.exec(
        statement.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).offset(offset).limit(limit)  # type: ignore[attr-defined]
    )
    items = [
        AuditOut(
            id=row.id,
            ts=row.ts,
            username=row.username,
            via_api=row.api_key_id is not None,
            api_key=row.api_key_label,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            changes=row.changes,
        )
        for row in rows.all()
    ]
    return Page[AuditOut](items=items, total=total, limit=limit, offset=offset)
