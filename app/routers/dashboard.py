"""Tableau de bord : infos réseau, stats, panneau « à traiter », liste des VLAN."""

from dataclasses import dataclass, field

from fastapi import APIRouter, Depends
from fastapi.requests import Request
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.deps import CurrentUser, SessionDep, csrf_protect
from app.models import IPAddress, IPStatus, MonitorTarget, Subnet, utcnow
from app.services import ipam
from app.services.monitor import SEVERITY, Health, ip_health
from app.templating import render

router = APIRouter(dependencies=[Depends(csrf_protect)])


@dataclass
class SubnetSummary:
    subnet: Subnet
    stats: ipam.SubnetStats
    health: Health | None
    ip_count: int


@dataclass
class Attention:
    ip: IPAddress
    subnet: Subnet
    health: Health
    last_ok_at: object


@dataclass
class Paused:
    ip: IPAddress
    subnet: Subnet
    health: Health | None  # état réel, les checks continuant pendant la pause


@dataclass
class DashboardData:
    total: int = 0
    used: int = 0
    free: int = 0
    reserved: int = 0
    red_count: int = 0  # pannes à traiter (IP en pause exclues)
    paused: list[Paused] = field(default_factory=list)


async def load_dashboard(session: SessionDep) -> tuple[list[SubnetSummary], list[Attention], DashboardData]:
    now = utcnow()
    result = await session.exec(
        select(Subnet)
        .options(selectinload(Subnet.ips).selectinload(IPAddress.monitors))  # type: ignore[arg-type]
    )
    subnets = sorted(result.all(), key=lambda s: ipam.network_sort_key(s.cidr))

    summaries: list[SubnetSummary] = []
    attention: list[Attention] = []
    data = DashboardData()

    for subnet in subnets:
        worst: Health | None = None
        for ip in subnet.ips:
            data.total += 1
            if ip.status == IPStatus.utilisee:
                data.used += 1
            elif ip.status == IPStatus.libre:
                data.free += 1
            else:
                data.reserved += 1
            h = ip_health(ip.monitors, now)
            if ip.is_paused:
                # Pause volontaire : ni « à traiter », ni pire état du VLAN.
                data.paused.append(Paused(ip=ip, subnet=subnet, health=h))
                continue
            if h is not None and (worst is None or SEVERITY[h] > SEVERITY[worst]):
                worst = h
            if h in (Health.red, Health.dark_red):
                data.red_count += 1
                last_ok = max(
                    (t.last_ok_at for t in ip.monitors if t.enabled and t.last_ok_at), default=None
                )
                attention.append(Attention(ip=ip, subnet=subnet, health=h, last_ok_at=last_ok))
        summaries.append(
            SubnetSummary(
                subnet=subnet,
                stats=ipam.subnet_stats(subnet, len(subnet.ips)),
                health=worst,
                ip_count=len(subnet.ips),
            )
        )

    attention.sort(key=lambda a: (-SEVERITY[a.health], a.last_ok_at or utcnow(), a.ip.address_int))
    data.paused.sort(key=lambda p: (ipam.network_sort_key(p.subnet.cidr), p.ip.address_int))
    return summaries, attention, data


@router.get("/")
async def dashboard(request: Request, user: CurrentUser, session: SessionDep):
    summaries, attention, data = await load_dashboard(session)
    return render(
        request,
        "dashboard.html",
        {"summaries": summaries, "attention": attention, "data": data},
    )


@router.get("/dashboard/stats")
async def dashboard_stats(request: Request, user: CurrentUser, session: SessionDep):
    """Partial : bandeau de stats + panneau à traiter (polling HTMX)."""
    summaries, attention, data = await load_dashboard(session)
    return render(
        request,
        "partials/_stats_block.html",
        {"summaries": summaries, "attention": attention, "data": data},
    )
