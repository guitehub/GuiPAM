"""Check TCP réel : serveur factice ouvert (up) / port fermé (down)."""

import asyncio

from app.models import CheckStatus, MonitorTarget, Protocol
from app.services.monitor import apply_result, check_tcp


async def test_check_tcp_up():
    async def handler(reader, writer):
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        ok, latency = await check_tcp("127.0.0.1", port, timeout=3.0)
    finally:
        server.close()
        await server.wait_closed()
    assert ok is True
    assert latency is not None and latency >= 0


async def test_check_tcp_down():
    # Port fermé : on réserve un port puis on le libère aussitôt.
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    ok, latency = await check_tcp("127.0.0.1", port, timeout=1.0)
    assert ok is False
    assert latency is None


def test_apply_result_up_puis_down():
    target = MonitorTarget(ip_id=1, protocol=Protocol.tcp, port=80)
    apply_result(target, ok=True, latency_ms=12.5)
    assert target.last_status == CheckStatus.up
    assert target.last_ok_at is not None
    assert target.consecutive_failures == 0
    first_ok = target.last_ok_at

    apply_result(target, ok=False, latency_ms=None)
    assert target.last_status == CheckStatus.down
    assert target.last_ok_at == first_ok  # le dernier succès est conservé
    assert target.consecutive_failures == 1
    apply_result(target, ok=False, latency_ms=None)
    assert target.consecutive_failures == 2


async def test_badge_d_etat_aux_couleurs_de_sante(client):
    """« up » en vert (couleur de santé, pas la couleur de marque), « down » en rouge, jamais vérifié en neutre."""
    from sqlmodel import select

    from app.database import session_factory
    from tests.conftest import ADMIN_PASSWORD, login

    csrf = await login(client, "admin", ADMIN_PASSWORD)
    h = {"X-CSRF-Token": csrf}
    await client.post("/subnets", data={"name": "LAN", "cidr": "192.168.1.0/24"}, headers=h)
    await client.post("/subnets/1/ips", data={"address": "192.168.1.10"}, headers=h)
    for port in ("22", "80", "443"):
        await client.post("/ips/1/monitors", data={"protocol": "tcp", "port": port}, headers=h)
    async with session_factory()() as session:
        targets = (await session.exec(select(MonitorTarget).order_by(MonitorTarget.port))).all()  # type: ignore[arg-type]
        apply_result(targets[0], ok=True, latency_ms=1.0)
        apply_result(targets[1], ok=False, latency_ms=None)
        session.add_all(targets)
        await session.commit()

    page = (await client.get("/ips/1")).text
    assert '<span class="badge status-up">up</span>' in page
    assert '<span class="badge-destructive">down</span>' in page
    assert '<span class="badge-outline">inconnu</span>' in page
    assert 'badge-primary">up<' not in page
    css = (await client.get("/static/health.css")).text
    assert ".badge.status-up" in css and "var(--health-ok)" in css
