"""Suivi dynamique : checks TCP/ICMP, code couleur santé, scheduler.

Toutes les règles de santé (§7.3) sont centralisées ici, dans `health()` et
`ip_health()`. Elles sont relatives à chaque cible : sa fraîcheur se mesure en
nombre de ses propres intervalles, sa panne en nombre d'échecs consécutifs.
Seul le rouge foncé (« morte depuis longtemps ») est une durée.
"""

import asyncio
import enum
import math
import re
import time
from dataclasses import dataclass, fields
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_settings
from app.models import RESEAU_SINGLETON_ID, CheckStatus, IPAddress, MonitorTarget, Protocol, Reseau, utcnow

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


# --------------------------------------------------------------- Réglages du suivi


@dataclass(frozen=True)
class MonitoringSettings:
    """Réglages du suivi modifiables dans les « Paramètres du réseau ».

    Chaque champ porte le même nom que sa colonne (facultative) de `reseau` et que le
    réglage d'instance `GUIPAM_*` qui sert de valeur tant que la colonne est vide.
    """

    default_check_interval: int  # intervalle proposé pour une nouvelle cible (s)
    health_warn_intervals: int  # vert → ambre : dernier succès plus vieux que N intervalles
    health_red_failures: int  # ambre → rouge : N échecs consécutifs
    health_dark_red_seconds: int  # rouge → rouge foncé : durée sans succès (s)


MONITORING_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(MonitoringSettings))

# Réglages effectifs, mis en cache pour que `health()` reste synchrone et sans accès base.
# Rafraîchi au démarrage, à chaque modification du réseau, après une restauration et à
# chaque requête d'interface (qui charge déjà le réseau) ; None = réglages d'instance.
_configured: MonitoringSettings | None = None


def instance_monitoring() -> MonitoringSettings:
    """Réglages d'instance (variables GUIPAM_*) : la valeur initiale de chaque réglage."""
    settings = get_settings()
    return MonitoringSettings(**{name: getattr(settings, name) for name in MONITORING_FIELDS})


def effective_monitoring(reseau: Reseau | None) -> MonitoringSettings:
    """Réglages appliqués : ceux du réseau, sinon ceux de l'instance."""
    base = instance_monitoring()
    if reseau is None:
        return base
    return MonitoringSettings(
        **{
            name: value if (value := getattr(reseau, name, None)) is not None else getattr(base, name)
            for name in MONITORING_FIELDS
        }
    )


def configure_monitoring(reseau: Reseau | None) -> None:
    global _configured
    _configured = effective_monitoring(reseau) if reseau is not None else None


async def load_monitoring(session: AsyncSession) -> None:
    """Recharge les réglages depuis la base (démarrage, restauration)."""
    configure_monitoring(await session.get(Reseau, RESEAU_SINGLETON_ID))


def monitoring() -> MonitoringSettings:
    return _configured or instance_monitoring()


# ------------------------------------------------------------------- Code couleur


def health(
    target: MonitorTarget, now: datetime | None = None, *, rules: MonitoringSettings | None = None
) -> Health:
    """Couleur d'une cible (§7.3), jugée à son propre rythme.

    - joignable : verte tant que son dernier succès a moins de `health_warn_intervals` fois son
      intervalle (plus un battement du scheduler, qui ne la vérifie jamais pile à l'heure), ambre au-delà ;
    - en panne : ambre, rouge à partir de `health_red_failures` échecs consécutifs, rouge foncé
      quand le dernier succès a plus de `health_dark_red_seconds`.
    """
    rules = rules or monitoring()
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
        fresh = rules.health_warn_intervals * target.interval_seconds + get_settings().monitor_tick_seconds
        return Health.ok if age <= fresh else Health.warn
    # down
    if age > rules.health_dark_red_seconds:
        return Health.dark_red
    if target.consecutive_failures >= rules.health_red_failures:
        return Health.red
    return Health.warn


def ip_health(
    targets: list[MonitorTarget], now: datetime | None = None, *, rules: MonitoringSettings | None = None
) -> Health | None:
    """Santé d'une IP = la pire de ses cibles actives. None si aucune cible active."""
    active = [t for t in targets if t.enabled]
    if not active:
        return None
    reference = now or utcnow()
    return max((health(t, reference, rules=rules) for t in active), key=lambda h: SEVERITY[h])


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
