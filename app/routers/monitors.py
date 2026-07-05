"""CRUD des cibles de suivi + check immédiat par cible."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from app.config import get_settings
from app.deps import CurrentUser, ManagerUser, SessionDep, csrf_protect
from app.flash import flash
from app.i18n import gettext as _
from app.models import IPAddress, MonitorTarget, Protocol
from app.services import audit
from app.services.monitor import check_target_now
from app.templating import hx_refresh, render

router = APIRouter(dependencies=[Depends(csrf_protect)])

MIN_INTERVAL = 5
MAX_INTERVAL = 86400


async def _get_target(session: SessionDep, monitor_id: int) -> MonitorTarget:
    target = await session.get(MonitorTarget, monitor_id)
    if target is None:
        raise HTTPException(status_code=404, detail=_("Monitor target not found."))
    return target


def _target_dict(target: MonitorTarget) -> dict:
    return {
        "protocol": target.protocol.value,
        "port": target.port,
        "label": target.label,
        "enabled": target.enabled,
        "interval_seconds": target.interval_seconds,
    }


def _validate_monitor_form(protocol: str, port: str, interval: str) -> tuple[dict, list[str]]:
    errors: list[str] = []
    try:
        proto = Protocol(protocol)
    except ValueError:
        proto = Protocol.tcp
    port_value: int | None = None
    if proto == Protocol.tcp:
        try:
            port_value = int(port.strip())
        except (ValueError, AttributeError):
            port_value = None
        if port_value is None or not 1 <= port_value <= 65535:
            errors.append(_("A TCP check requires a port between 1 and 65535."))
    else:
        if not get_settings().enable_ping:
            errors.append(_("ICMP ping is disabled on this instance (GUIPAM_ENABLE_PING=false)."))
    try:
        interval_value = int(interval.strip()) if interval.strip() else get_settings().default_check_interval
    except ValueError:
        interval_value = -1
    if not MIN_INTERVAL <= interval_value <= MAX_INTERVAL:
        errors.append(
            _("Interval must be between %(min)d and %(max)d seconds.")
            % {"min": MIN_INTERVAL, "max": MAX_INTERVAL}
        )
    return {"protocol": proto, "port": port_value, "interval": interval_value}, errors


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
    values, errors = _validate_monitor_form(protocol, port, interval_seconds)
    if errors:
        return render(
            request,
            "partials/_monitor_form.html",
            {"ip": ip, "target": None, "errors": errors},
            status_code=422,
        )
    target = MonitorTarget(
        ip_id=ip_id,
        protocol=values["protocol"],
        port=values["port"] if values["protocol"] == Protocol.tcp else None,
        label=label.strip() or None,
        interval_seconds=values["interval"],
        enabled=enabled == "on",
    )
    session.add(target)
    await session.flush()
    await audit.record(session, user, "create", "monitor", target.id, audit.diff({}, _target_dict(target)))
    await session.commit()
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
    values, errors = _validate_monitor_form(protocol, port, interval_seconds)
    if errors:
        return render(
            request,
            "partials/_monitor_form.html",
            {"ip": ip, "target": target, "errors": errors},
            status_code=422,
        )
    before = _target_dict(target)
    target.protocol = values["protocol"]
    target.port = values["port"] if values["protocol"] == Protocol.tcp else None
    target.label = label.strip() or None
    target.interval_seconds = values["interval"]
    target.enabled = enabled == "on"
    session.add(target)
    await audit.record(session, user, "update", "monitor", target.id, audit.diff(before, _target_dict(target)))
    await session.commit()
    flash(request, _("Monitor target updated."))
    return hx_refresh()


@router.delete("/monitors/{monitor_id}")
async def delete_monitor(request: Request, user: ManagerUser, session: SessionDep, monitor_id: int):
    target = await _get_target(session, monitor_id)
    before = _target_dict(target)
    await session.delete(target)
    await audit.record(session, user, "delete", "monitor", monitor_id, audit.diff(before, {}))
    await session.commit()
    flash(request, _("Monitor target deleted."))
    return hx_refresh()


@router.post("/monitors/{monitor_id}/check")
async def check_monitor(request: Request, user: CurrentUser, session: SessionDep, monitor_id: int):
    """Check immédiat d'une cible, renvoie la ligne cible mise à jour."""
    target = await _get_target(session, monitor_id)
    target = await check_target_now(session, target)
    await audit.record(session, user, "check", "monitor", target.id)
    await session.commit()
    ip = await session.get(IPAddress, target.ip_id)
    return render(request, "partials/_monitor_row.html", {"target": target, "ip": ip})
