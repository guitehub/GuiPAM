"""Suivi dynamique : checks TCP/ICMP, code couleur santé, scheduler.

Tous les seuils de santé (§7.3) sont centralisés ici, dans `health()` et
`ip_health()`. Tout est relatif à `last_ok_at`.
"""

import asyncio
import enum
import math
import re
import time
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.models import CheckStatus, IPAddress, MonitorTarget, Protocol, utcnow

# « jamais de succès » ne devient rouge foncé qu'après des échecs répétés.
DARK_RED_MIN_FAILURES = 3

_PING_TIME_RE = re.compile(r"time[=<]([\d.]+)\s*ms")


class Health(str, enum.Enum):
    unknown = "unknown"
    ok = "ok"
    warn = "warn"
    red = "red"
    dark_red = "dark_red"


# Ordre de gravité pour le rollup « pire cible » : un vert est meilleur
# qu'un jamais-vérifié, qui est meilleur qu'un ambre, etc.
SEVERITY: dict[Health, int] = {
    Health.ok: 0,
    Health.unknown: 1,
    Health.warn: 2,
    Health.red: 3,
    Health.dark_red: 4,
}


def health(
    target: MonitorTarget,
    now: datetime | None = None,
    *,
    warn_seconds: int | None = None,
    red_seconds: int | None = None,
    dark_red_seconds: int | None = None,
) -> Health:
    """Couleur d'une cible selon la fraîcheur de son dernier succès (§7.3)."""
    settings = get_settings()
    warn_s = warn_seconds if warn_seconds is not None else settings.health_warn_seconds
    red_s = red_seconds if red_seconds is not None else settings.health_red_seconds
    dark_s = dark_red_seconds if dark_red_seconds is not None else settings.health_dark_red_seconds
    reference = now or utcnow()

    if target.last_status == CheckStatus.unknown:
        return Health.unknown

    if target.last_ok_at is None:
        # Jamais de succès : rouge, rouge foncé après échecs répétés.
        if target.consecutive_failures >= DARK_RED_MIN_FAILURES:
            return Health.dark_red
        return Health.red

    age = (reference - target.last_ok_at).total_seconds()
    if target.last_status == CheckStatus.up:
        return Health.ok if age <= warn_s else Health.warn
    # down
    if age <= red_s:
        return Health.warn
    if age <= dark_s:
        return Health.red
    return Health.dark_red


def ip_health(targets: list[MonitorTarget], now: datetime | None = None) -> Health | None:
    """Santé d'une IP = la pire de ses cibles actives. None si aucune cible active."""
    active = [t for t in targets if t.enabled]
    if not active:
        return None
    reference = now or utcnow()
    return max((health(t, reference) for t in active), key=lambda h: SEVERITY[h])


async def check_tcp(host: str, port: int, timeout: float) -> tuple[bool, float | None]:
    """Connexion TCP : (succès, latence ms)."""
    start = time.perf_counter()
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (TimeoutError, OSError):
        return False, None
    latency = (time.perf_counter() - start) * 1000.0
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True, latency


async def check_icmp(host: str, timeout: float) -> tuple[bool, float | None]:
    """Ping ICMP via iputils (`ping -c 1`). Nécessite CAP_NET_RAW en conteneur."""
    wait = max(1, math.ceil(timeout))
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c",
            "1",
            "-W",
            str(wait),
            host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False, None
    try:
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 2)
    except TimeoutError:
        proc.kill()
        return False, None
    if proc.returncode != 0:
        return False, None
    match = _PING_TIME_RE.search(stdout.decode(errors="replace"))
    return True, float(match.group(1)) if match else None


async def run_check(target: MonitorTarget, host: str) -> tuple[bool, float | None]:
    settings = get_settings()
    if target.protocol == Protocol.tcp and target.port:
        return await check_tcp(host, target.port, settings.tcp_timeout_seconds)
    if not settings.enable_ping:
        return False, None
    return await check_icmp(host, settings.tcp_timeout_seconds)


def apply_result(target: MonitorTarget, ok: bool, latency_ms: float | None) -> bool:
    """Enregistre un résultat. Retourne True si la cible revient (était `down`, répond à nouveau) :
    c'est le signal de reprise des pauses « jusqu'au retour »."""
    recovered = ok and target.last_status == CheckStatus.down
    now = utcnow()
    target.last_checked_at = now
    target.latency_ms = latency_ms
    if ok:
        target.last_status = CheckStatus.up
        target.last_ok_at = now
        target.consecutive_failures = 0
    else:
        target.last_status = CheckStatus.down
        target.consecutive_failures += 1
    return recovered


async def check_target_now(session: AsyncSession, target: MonitorTarget) -> MonitorTarget:
    """Check immédiat d'une cible (bouton « Vérifier »)."""
    from app.services.inventory import resume_due_pauses  # import local : inventory importe ce module

    ip = await session.get(IPAddress, target.ip_id)
    ok, latency = await run_check(target, ip.address)
    recovered = apply_result(target, ok, latency)
    session.add(target)
    if recovered:
        await resume_due_pauses(session, recovered_ip_ids={target.ip_id})
    await session.commit()
    await session.refresh(target)
    return target


async def run_due_checks(session: AsyncSession) -> int:
    """Vérifie toutes les cibles actives « dues ». Retourne le nombre de checks."""
    settings = get_settings()
    now = utcnow()
    result = await session.exec(
        select(MonitorTarget, IPAddress.address)
        .join(IPAddress, MonitorTarget.ip_id == IPAddress.id)  # type: ignore[arg-type]
        .where(MonitorTarget.enabled == True)  # noqa: E712
    )
    from app.services.inventory import resume_due_pauses  # import local : inventory importe ce module

    rows = result.all()
    due = [
        (target, address)
        for target, address in rows
        if target.last_checked_at is None
        or (now - target.last_checked_at).total_seconds() >= target.interval_seconds
    ]
    recovered: set[int] = set()
    semaphore = asyncio.Semaphore(settings.monitor_concurrency)

    async def _one(target: MonitorTarget, address: str) -> None:
        async with semaphore:
            ok, latency = await run_check(target, address)
        if apply_result(target, ok, latency):
            recovered.add(target.ip_id)
        session.add(target)

    if due:
        await asyncio.gather(*(_one(t, a) for t, a in due))
    # Échéances de pause dépassées + hôtes en pause « jusqu'au retour » qui répondent à nouveau.
    await resume_due_pauses(session, recovered_ip_ids=recovered)
    await session.commit()
    return len(due)


async def scheduler_tick() -> None:
    """Job APScheduler : ouvre sa propre session et vérifie les cibles dues."""
    from app.database import session_factory

    async with session_factory()() as session:
        await run_due_checks(session)
