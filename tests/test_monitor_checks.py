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
