"""Opérations métier sur l'inventaire : VLAN, IP, cibles de suivi, réseau.

Point de passage unique des mutations : l'UI (formulaires HTMX) et l'API JSON
appellent ces fonctions, donc appliquent exactement les mêmes règles, et chaque
mutation est tracée dans l'audit avec son auteur (utilisateur ou clé d'API).

Convention : les fonctions valident, écrivent, auditent et committent. En cas de
règle violée, elles lèvent `ValidationFailed` (liste d'erreurs localisées) sans
rien écrire.
"""

import ipaddress
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.i18n import available_locales, gettext as _
from app.models import (
    IPAddress,
    IPStatus,
    MonitorTarget,
    Protocol,
    Reseau,
    Subnet,
    User,
    utcnow,
)
from app.services import audit, ipam
from app.services.ipam import ConflictError
from app.services import monitor
from app.services.monitor import check_target_now

Author = User | audit.Actor | None

MIN_INTERVAL = 5
MAX_INTERVAL = 86400
# Bornes des réglages du suivi (Paramètres du réseau) : (min, max) par champ de MonitoringSettings.
MONITORING_LIMITS: dict[str, tuple[int, int]] = {
    "default_check_interval": (MIN_INTERVAL, MAX_INTERVAL),
    "health_warn_intervals": (1, 100),
    "health_red_failures": (1, 1000),
    "health_dark_red_seconds": (60, 366 * 86400),
}
ALLOCATE_RETRIES = 3


class ValidationFailed(Exception):
    """Une ou plusieurs règles métier violées (messages localisés, champ fautif)."""

    def __init__(self, errors: list[ConflictError]) -> None:
        super().__init__("; ".join(e.message for e in errors))
        self.errors = errors

    @property
    def messages(self) -> list[str]:
        return [e.message for e in self.errors]

    @property
    def fields(self) -> list[str]:
        """Champs fautifs (noms des champs de formulaire), pour les marquer en rouge."""
        return [e.field for e in self.errors if e.field]


class SubnetFullError(ValidationFailed):
    """Plus aucune adresse libre à allouer dans le VLAN."""


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


# --------------------------------------------------------------------------- VLAN


def subnet_dict(subnet: Subnet) -> dict[str, Any]:
    return {
        "name": subnet.name,
        "description": subnet.description,
        "vlan_id": subnet.vlan_id,
        "cidr": subnet.cidr,
        "gateway": subnet.gateway,
        "notes": subnet.notes,
    }


async def _validate_subnet(
    session: AsyncSession,
    *,
    name: str | None,
    vlan_id: int | None,
    cidr: str | None,
    gateway: str | None,
    exclude_id: int | None = None,
) -> dict[str, Any]:
    errors: list[ConflictError] = []
    if not _clean(name):
        errors.append(ConflictError(_("Name is required."), "name"))
    if vlan_id is not None and not 1 <= vlan_id <= 4094:
        errors.append(ConflictError(_("VLAN tag must be a number between 1 and 4094."), "vlan_id"))
    existing = list((await session.exec(select(Subnet))).all())
    network = None
    try:
        network = ipam.validate_subnet(cidr or "", _clean(gateway), existing, exclude_id=exclude_id)
    except ConflictError as exc:
        errors.append(exc)
    if network is not None and exclude_id is not None:
        # Changement de CIDR : toutes les IP existantes doivent rester dedans.
        result = await session.exec(select(IPAddress).where(IPAddress.subnet_id == exclude_id))
        outside = [ip.address for ip in result.all() if ipaddress.ip_address(ip.address) not in network]
        if outside:
            errors.append(
                ConflictError(
                    _("Cannot change CIDR: %(count)d addresses would fall outside (e.g. %(example)s).")
                    % {"count": len(outside), "example": outside[0]},
                    "cidr",
                )
            )
    if errors:
        raise ValidationFailed(errors)
    return {
        "name": _clean(name),
        "vlan_id": vlan_id,
        "cidr": str(network),
        "gateway": _clean(gateway),
    }


async def create_subnet(
    session: AsyncSession,
    author: Author,
    *,
    name: str | None,
    cidr: str | None,
    vlan_id: int | None = None,
    gateway: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> Subnet:
    values = await _validate_subnet(session, name=name, vlan_id=vlan_id, cidr=cidr, gateway=gateway)
    subnet = Subnet(**values, description=_clean(description), notes=_clean(notes))
    session.add(subnet)
    await session.flush()
    await audit.record(session, author, "create", "subnet", subnet.id, audit.diff({}, subnet_dict(subnet)))
    await session.commit()
    return subnet


async def update_subnet(
    session: AsyncSession,
    author: Author,
    subnet: Subnet,
    *,
    name: str | None,
    cidr: str | None,
    vlan_id: int | None = None,
    gateway: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> Subnet:
    values = await _validate_subnet(
        session, name=name, vlan_id=vlan_id, cidr=cidr, gateway=gateway, exclude_id=subnet.id
    )
    before = subnet_dict(subnet)
    subnet.name = values["name"]
    subnet.vlan_id = values["vlan_id"]
    subnet.cidr = values["cidr"]
    subnet.gateway = values["gateway"]
    subnet.description = _clean(description)
    subnet.notes = _clean(notes)
    subnet.updated_at = utcnow()
    session.add(subnet)
    await audit.record(session, author, "update", "subnet", subnet.id, audit.diff(before, subnet_dict(subnet)))
    await session.commit()
    return subnet


async def delete_subnet(session: AsyncSession, author: Author, subnet: Subnet) -> None:
    before = subnet_dict(subnet)
    subnet_id = subnet.id
    await session.delete(subnet)  # cascade : IP + cibles
    await audit.record(session, author, "delete", "subnet", subnet_id, audit.diff(before, {}))
    await session.commit()


# ----------------------------------------------------------------------------- IP


def ip_dict(ip: IPAddress) -> dict[str, Any]:
    return {
        "address": ip.address,
        "hostname": ip.hostname,
        "mac": ip.mac,
        "device_label": ip.device_label,
        "hardware": ip.hardware,
        "location": ip.location,
        "description": ip.description,
        "status": ip.status.value,
    }


async def _subnet_ips(session: AsyncSession, subnet_id: int) -> list[IPAddress]:
    return list((await session.exec(select(IPAddress).where(IPAddress.subnet_id == subnet_id))).all())


def _normalize_mac(mac: str | None, errors: list[ConflictError]) -> str | None:
    try:
        return ipam.normalize_mac(mac or None)
    except ConflictError as exc:
        errors.append(exc)
        return None


def _apply_ip_fields(
    ip: IPAddress,
    *,
    status: IPStatus,
    hostname: str | None,
    mac: str | None,
    device_label: str | None,
    hardware: str | None,
    location: str | None,
    description: str | None,
) -> None:
    ip.status = status
    ip.hostname = _clean(hostname)
    ip.mac = mac
    ip.device_label = _clean(device_label)
    ip.hardware = _clean(hardware)
    ip.location = _clean(location)
    ip.description = _clean(description)


async def create_ip(
    session: AsyncSession,
    author: Author,
    subnet: Subnet,
    *,
    address: str | None,
    status: IPStatus = IPStatus.utilisee,
    hostname: str | None = None,
    mac: str | None = None,
    device_label: str | None = None,
    hardware: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> IPAddress:
    errors: list[ConflictError] = []
    parsed = None
    try:
        parsed = ipam.validate_ip(address or "", subnet, await _subnet_ips(session, subnet.id))
    except ConflictError as exc:
        errors.append(exc)
    normalized_mac = _normalize_mac(mac, errors)
    if errors or parsed is None:
        raise ValidationFailed(errors)
    subnet_name = subnet.name
    ip = IPAddress(subnet_id=subnet.id, address=str(parsed), address_int=int(parsed))
    _apply_ip_fields(
        ip,
        status=status,
        hostname=hostname,
        mac=normalized_mac,
        device_label=device_label,
        hardware=hardware,
        location=location,
        description=description,
    )
    session.add(ip)
    try:
        await session.flush()
    except IntegrityError:
        # Création concurrente de la même adresse (contrainte d'unicité).
        await session.rollback()
        raise ValidationFailed(
            [
                ConflictError(
                    _("Address %(address)s already exists in VLAN “%(name)s”.")
                    % {"address": str(parsed), "name": subnet_name},
                    "address",
                )
            ]
        ) from None
    await audit.record(session, author, "create", "ip", ip.id, audit.diff({}, ip_dict(ip)))
    await session.commit()
    return ip


async def update_ip(
    session: AsyncSession,
    author: Author,
    ip: IPAddress,
    *,
    address: str | None,
    status: IPStatus,
    hostname: str | None = None,
    mac: str | None = None,
    device_label: str | None = None,
    hardware: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> IPAddress:
    subnet = await session.get(Subnet, ip.subnet_id)
    errors: list[ConflictError] = []
    parsed = None
    try:
        parsed = ipam.validate_ip(
            address or "", subnet, await _subnet_ips(session, subnet.id), exclude_id=ip.id
        )
    except ConflictError as exc:
        errors.append(exc)
    normalized_mac = _normalize_mac(mac, errors)
    if errors or parsed is None:
        raise ValidationFailed(errors)
    before = ip_dict(ip)
    ip.address = str(parsed)
    ip.address_int = int(parsed)
    _apply_ip_fields(
        ip,
        status=status,
        hostname=hostname,
        mac=normalized_mac,
        device_label=device_label,
        hardware=hardware,
        location=location,
        description=description,
    )
    ip.updated_at = utcnow()
    session.add(ip)
    await audit.record(session, author, "update", "ip", ip.id, audit.diff(before, ip_dict(ip)))
    await session.commit()
    return ip


async def delete_ip(session: AsyncSession, author: Author, ip: IPAddress) -> None:
    before = ip_dict(ip)
    ip_id = ip.id
    await session.delete(ip)  # cascade : cibles
    await audit.record(session, author, "delete", "ip", ip_id, audit.diff(before, {}))
    await session.commit()


def next_free_address(subnet: Subnet, ips: list[IPAddress]) -> tuple[int, IPAddress | None] | None:
    """Plus petite adresse allouable du VLAN : (entier, ligne « libre » à réutiliser ou None).

    Allouable = adresse utilisable sans ligne en base, ou ligne au statut `libre`.
    La passerelle du VLAN n'est jamais proposée. None si le VLAN est plein.
    """
    network = ipaddress.ip_network(subnet.cidr)
    first, last = ipam.usable_range(network)
    gateway = int(ipaddress.ip_address(subnet.gateway)) if subnet.gateway else None
    by_int = {ip.address_int: ip for ip in ips}
    for candidate in range(int(first), int(last) + 1):
        if candidate == gateway:
            continue
        row = by_int.get(candidate)
        if row is None or row.status == IPStatus.libre:
            return candidate, row
    return None


async def allocate_ip(
    session: AsyncSession,
    author: Author,
    subnet_id: int,
    *,
    status: IPStatus = IPStatus.reservee,
    hostname: str | None = None,
    mac: str | None = None,
    device_label: str | None = None,
    hardware: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> IPAddress | None:
    """Trouve la prochaine adresse libre du VLAN et la réserve, atomiquement.

    Retourne None si le VLAN n'existe pas. Deux appels concurrents n'obtiennent
    jamais la même adresse (contrainte d'unicité + nouvel essai).
    """
    errors: list[ConflictError] = []
    if status == IPStatus.libre:
        errors.append(
            ConflictError(_("An allocated address cannot have the status “libre”."), "status")
        )
    normalized_mac = _normalize_mac(mac, errors)
    if errors:
        raise ValidationFailed(errors)
    fields = dict(
        status=status,
        hostname=hostname,
        mac=normalized_mac,
        device_label=device_label,
        hardware=hardware,
        location=location,
        description=description,
    )
    for _attempt in range(ALLOCATE_RETRIES):
        subnet = await session.get(Subnet, subnet_id)
        if subnet is None:
            return None
        found = next_free_address(subnet, await _subnet_ips(session, subnet_id))
        if found is None:
            raise SubnetFullError(
                [ConflictError(_("No free address left in subnet %s.") % subnet.cidr, "address")]
            )
        candidate, row = found
        if row is not None:
            before = ip_dict(row)
            _apply_ip_fields(row, **fields)
            row.updated_at = utcnow()
            session.add(row)
            await audit.record(session, author, "update", "ip", row.id, audit.diff(before, ip_dict(row)))
            await session.commit()
            return row
        ip = IPAddress(
            subnet_id=subnet_id,
            address=str(ipaddress.ip_address(candidate)),
            address_int=candidate,
        )
        _apply_ip_fields(ip, **fields)
        session.add(ip)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()  # adresse prise entre-temps : on recommence
            continue
        await audit.record(session, author, "create", "ip", ip.id, audit.diff({}, ip_dict(ip)))
        await session.commit()
        return ip
    raise ValidationFailed(
        [ConflictError(_("Could not allocate an address (concurrent updates). Try again."), "address")]
    )


async def check_ip(session: AsyncSession, author: Author, ip_id: int) -> IPAddress | None:
    """Vérifie tout de suite toutes les cibles actives de l'IP."""
    statement = (
        select(IPAddress).where(IPAddress.id == ip_id).options(selectinload(IPAddress.monitors))  # type: ignore[arg-type]
    )
    ip = (await session.exec(statement)).first()
    if ip is None:
        return None
    for target in ip.monitors:
        if target.enabled:
            await check_target_now(session, target)
    await audit.record(session, author, "check", "ip", ip.id)
    await session.commit()
    return (await session.exec(statement.execution_options(populate_existing=True))).first()


# -------------------------------------------------------------------------- Pause

# Durées proposées par l'UI (l'API accepte une date quelconque).
PAUSE_DURATIONS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=30),
}
PAUSE_REASON_MAX = 200


def pause_dict(ip: IPAddress) -> dict[str, Any]:
    return {
        "paused_at": ip.paused_at.isoformat() if ip.paused_at else None,
        "pause_reason": ip.pause_reason,
        "pause_until": ip.pause_until.isoformat() if ip.pause_until else None,
        "pause_until_recovery": ip.pause_until_recovery,
    }


async def pause_ip(
    session: AsyncSession,
    author: Author,
    ip: IPAddress,
    *,
    reason: str | None = None,
    until: datetime | None = None,
    until_recovery: bool = False,
) -> IPAddress:
    """Met une IP en pause volontaire (ou modifie une pause en cours).

    Les checks continuent ; l'IP sort de « À traiter » et des compteurs de pannes.
    Reprise : à `until` (UTC naïf), au retour de l'hôte si `until_recovery`, la
    première des deux qui arrive ; sans aucune des deux, reprise manuelle.
    """
    errors: list[ConflictError] = []
    reason = _clean(reason)
    if reason and len(reason) > PAUSE_REASON_MAX:
        errors.append(ConflictError(_("The reason is too long (%d characters max).") % PAUSE_REASON_MAX, "reason"))
    if until is not None and until <= utcnow():
        errors.append(ConflictError(_("The end of the pause must be in the future."), "until"))
    if errors:
        raise ValidationFailed(errors)
    before = pause_dict(ip)
    if ip.paused_at is None:
        ip.paused_at = utcnow()
    ip.pause_reason = reason
    ip.pause_until = until
    ip.pause_until_recovery = until_recovery
    session.add(ip)
    await audit.record(session, author, "pause", "ip", ip.id, audit.diff(before, pause_dict(ip)))
    await session.commit()
    return ip


def _clear_pause(ip: IPAddress) -> dict[str, Any]:
    before = pause_dict(ip)
    ip.paused_at = None
    ip.pause_reason = None
    ip.pause_until = None
    ip.pause_until_recovery = False
    return before


async def resume_ip(session: AsyncSession, author: Author, ip: IPAddress) -> IPAddress:
    """Lève la pause : l'IP redevient suivie normalement (sans effet si elle n'est pas en pause)."""
    if ip.paused_at is None:
        return ip
    before = _clear_pause(ip)
    session.add(ip)
    await audit.record(session, author, "resume", "ip", ip.id, audit.diff(before, pause_dict(ip)))
    await session.commit()
    return ip


async def resume_due_pauses(session: AsyncSession, recovered_ip_ids: Iterable[int] = ()) -> int:
    """Reprises automatiques (auteur « système ») : échéance dépassée, ou hôte en pause
    « jusqu'au retour » dont une cible vient de répondre à nouveau. Commit laissé à l'appelant."""
    now = utcnow()
    recovered = set(recovered_ip_ids)
    paused = (await session.exec(select(IPAddress).where(IPAddress.paused_at != None))).all()  # noqa: E711
    count = 0
    for ip in paused:
        expired = ip.pause_until is not None and ip.pause_until <= now
        came_back = ip.pause_until_recovery and ip.id in recovered
        if not (expired or came_back):
            continue
        before = _clear_pause(ip)
        session.add(ip)
        await audit.record(
            session, None, "resume", "ip", ip.id,
            # Cause de la reprise, au format {before, after} du journal comme les autres champs.
            {**audit.diff(before, pause_dict(ip)), "trigger": {"before": None, "after": "expired" if expired else "recovered"}},
        )
        count += 1
    return count


# ------------------------------------------------------------------------- Cibles


def target_dict(target: MonitorTarget) -> dict[str, Any]:
    return {
        "protocol": target.protocol.value,
        "port": target.port,
        "label": target.label,
        "enabled": target.enabled,
        "interval_seconds": target.interval_seconds,
    }


def _validate_monitor(protocol: Protocol, port: int | None, interval_seconds: int | None) -> dict[str, Any]:
    settings = get_settings()
    errors: list[ConflictError] = []
    if protocol == Protocol.tcp:
        if port is None or not 1 <= port <= 65535:
            errors.append(ConflictError(_("A TCP check requires a port between 1 and 65535."), "port"))
    elif not settings.enable_ping:
        errors.append(
            ConflictError(
                _("ICMP ping is disabled on this instance (GUIPAM_ENABLE_PING=false)."), "protocol"
            )
        )
    interval = interval_seconds if interval_seconds is not None else monitor.monitoring().default_check_interval
    if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
        errors.append(
            ConflictError(
                _("Interval must be between %(min)d and %(max)d seconds.")
                % {"min": MIN_INTERVAL, "max": MAX_INTERVAL},
                "interval_seconds",
            )
        )
    if errors:
        raise ValidationFailed(errors)
    return {
        "protocol": protocol,
        "port": port if protocol == Protocol.tcp else None,
        "interval_seconds": interval,
    }


async def create_monitor(
    session: AsyncSession,
    author: Author,
    ip: IPAddress,
    *,
    protocol: Protocol = Protocol.tcp,
    port: int | None = None,
    label: str | None = None,
    interval_seconds: int | None = None,
    enabled: bool = True,
) -> MonitorTarget:
    values = _validate_monitor(protocol, port, interval_seconds)
    target = MonitorTarget(ip_id=ip.id, **values, label=_clean(label), enabled=enabled)
    session.add(target)
    await session.flush()
    await audit.record(session, author, "create", "monitor", target.id, audit.diff({}, target_dict(target)))
    await session.commit()
    return target


async def update_monitor(
    session: AsyncSession,
    author: Author,
    target: MonitorTarget,
    *,
    protocol: Protocol,
    port: int | None = None,
    label: str | None = None,
    interval_seconds: int | None = None,
    enabled: bool = True,
) -> MonitorTarget:
    values = _validate_monitor(protocol, port, interval_seconds)
    before = target_dict(target)
    target.protocol = values["protocol"]
    target.port = values["port"]
    target.interval_seconds = values["interval_seconds"]
    target.label = _clean(label)
    target.enabled = enabled
    session.add(target)
    await audit.record(session, author, "update", "monitor", target.id, audit.diff(before, target_dict(target)))
    await session.commit()
    return target


async def delete_monitor(session: AsyncSession, author: Author, target: MonitorTarget) -> None:
    before = target_dict(target)
    target_id = target.id
    await session.delete(target)
    await audit.record(session, author, "delete", "monitor", target_id, audit.diff(before, {}))
    await session.commit()


async def check_monitor(session: AsyncSession, author: Author, target: MonitorTarget) -> MonitorTarget:
    target = await check_target_now(session, target)
    await audit.record(session, author, "check", "monitor", target.id)
    await session.commit()
    return target


# ------------------------------------------------------------------------- Réseau


def reseau_dict(reseau: Reseau) -> dict[str, Any]:
    return {
        "name": reseau.name,
        "description": reseau.description,
        "notes": reseau.notes,
        "root_prefixes": reseau.root_prefixes,
        "default_locale": reseau.default_locale,
        **{name: getattr(reseau, name) for name in monitor.MONITORING_FIELDS},
    }


def _monitoring_labels() -> dict[str, str]:
    return {
        "default_check_interval": _("Default check interval"),
        "health_warn_intervals": _("Green → amber threshold"),
        "health_red_failures": _("Amber → red threshold"),
        "health_dark_red_seconds": _("Red → dark red threshold"),
    }


async def update_reseau(
    session: AsyncSession,
    author: Author,
    reseau: Reseau,
    *,
    name: str | None,
    description: str | None = None,
    notes: str | None = None,
    root_prefixes: list[str] | None = None,
    default_locale: str | None = None,
    default_check_interval: int | None = None,
    health_warn_intervals: int | None = None,
    health_red_failures: int | None = None,
    health_dark_red_seconds: int | None = None,
) -> Reseau:
    """Met à jour le réseau. Réglages du suivi : None = revenir à la valeur d'instance (GUIPAM_*)."""
    tracking = {
        "default_check_interval": default_check_interval,
        "health_warn_intervals": health_warn_intervals,
        "health_red_failures": health_red_failures,
        "health_dark_red_seconds": health_dark_red_seconds,
    }
    errors: list[ConflictError] = []
    labels = _monitoring_labels()
    for field, value in tracking.items():
        low, high = MONITORING_LIMITS[field]
        if value is not None and not low <= value <= high:
            errors.append(
                ConflictError(
                    _("%(label)s: the value must be between %(min)d and %(max)d.")
                    % {"label": labels[field], "min": low, "max": high},
                    field,
                )
            )
    if not _clean(name):
        errors.append(ConflictError(_("Name is required."), "name"))
    prefixes: list[str] = []
    for chunk in root_prefixes or []:
        value = chunk.strip()
        if not value:
            continue
        try:
            prefixes.append(str(ipaddress.ip_network(value, strict=False)))
        except ValueError:
            errors.append(ConflictError(_("“%s” is not a valid network prefix.") % value, "root_prefixes"))
    if errors:
        raise ValidationFailed(errors)
    before = reseau_dict(reseau)
    reseau.name = _clean(name)
    reseau.description = _clean(description)
    reseau.notes = _clean(notes)
    reseau.root_prefixes = prefixes or None
    if default_locale in available_locales():
        reseau.default_locale = default_locale
    for field, value in tracking.items():
        setattr(reseau, field, value)
    reseau.updated_at = utcnow()
    session.add(reseau)
    await audit.record(session, author, "update", "reseau", reseau.id, audit.diff(before, reseau_dict(reseau)))
    await session.commit()
    monitor.configure_monitoring(reseau)
    return reseau
