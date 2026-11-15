"""Pause volontaire d'une IP : hors « À traiter », reprises automatiques, UI, API, audit."""

from datetime import timedelta

from sqlmodel import select

from app.database import session_factory
from app.models import AuditLog, CheckStatus, IPAddress, MonitorTarget, utcnow
from app.routers.dashboard import load_dashboard
from app.services import inventory
from app.services.monitor import apply_result
from tests.conftest import ADMIN_PASSWORD, login
from tests.test_api import API, setup
from tests.test_authz import create_user


async def down_ip(client, writer, address="10.20.0.2") -> dict:
    """IP avec une cible en panne depuis longtemps (rouge foncé)."""
    vlan = (await client.post(f"{API}/vlans", json={"name": "lab", "cidr": "10.20.0.0/29"}, headers=writer)).json()
    ip = (await client.post(f"{API}/vlans/{vlan['id']}/ips", json={"address": address, "hostname": "vrainas"}, headers=writer)).json()
    async with session_factory()() as session:
        session.add(MonitorTarget(
            ip_id=ip["id"], protocol="icmp", last_status=CheckStatus.down, consecutive_failures=10,
            last_checked_at=utcnow(), last_ok_at=utcnow() - timedelta(days=30),
        ))
        await session.commit()
    return ip


async def get_ip(ip_id: int) -> IPAddress:
    async with session_factory()() as session:
        return await session.get(IPAddress, ip_id)


def test_apply_result_signale_seulement_un_retour():
    target = MonitorTarget(ip_id=1, last_status=CheckStatus.unknown)
    assert apply_result(target, True, 1.0) is False  # premier succès : pas un « retour »
    assert apply_result(target, True, 1.0) is False  # déjà up
    assert apply_result(target, False, None) is False
    assert apply_result(target, True, 1.0) is True  # down → up


class TestTableauDeBord:
    async def test_ip_en_pause_hors_a_traiter_et_listee_a_part(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        async with session_factory()() as session:
            _s, attention, data = await load_dashboard(session)
        assert [a.ip.id for a in attention] == [ip["id"]] and data.red_count == 1

        response = await client.post(f"{API}/ips/{ip['id']}/pause", json={"reason": "éteint exprès"}, headers=writer)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["paused"] is True and body["pause"]["reason"] == "éteint exprès"
        assert body["pause"]["until_recovery"] is True  # défaut : reprise au retour
        assert body["health"] == "dark_red"  # l'état réel reste publié

        async with session_factory()() as session:
            summaries, attention, data = await load_dashboard(session)
        assert attention == [] and data.red_count == 0
        assert [p.ip.id for p in data.paused] == [ip["id"]]
        assert summaries[0].health is None  # le VLAN n'hérite pas du rouge d'une IP en pause

    async def test_page_tableau_de_bord(self, client):
        csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        await client.post(f"{API}/ips/{ip['id']}/pause", json={"reason": "éteint exprès"}, headers=writer)
        await login(client, "admin", ADMIN_PASSWORD)
        page = (await client.get("/")).text
        assert "Adresses dont les cibles ne répondent plus" not in page  # panneau « À traiter » absent
        assert "éteint exprès" in page and "Reprise quand l'hôte répondra de nouveau." in page


class TestReprisesAutomatiques:
    async def test_retour_de_l_hote_leve_la_pause(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        await client.post(f"{API}/ips/{ip['id']}/pause", json={}, headers=writer)
        async with session_factory()() as session:
            assert await inventory.resume_due_pauses(session, recovered_ip_ids={ip["id"]}) == 1
            await session.commit()
        assert (await get_ip(ip["id"])).paused_at is None
        async with session_factory()() as session:
            entry = (await session.exec(select(AuditLog).where(AuditLog.action == "resume"))).one()
        assert entry.username == "système" and entry.changes["trigger"]["after"] == "recovered"

    async def test_retour_ignore_si_reprise_manuelle(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        await client.post(f"{API}/ips/{ip['id']}/pause", json={"until_recovery": False}, headers=writer)
        async with session_factory()() as session:
            assert await inventory.resume_due_pauses(session, recovered_ip_ids={ip["id"]}) == 0
        assert (await get_ip(ip["id"])).is_paused

    async def test_echeance_depassee(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        async with session_factory()() as session:
            row = await session.get(IPAddress, ip["id"])
            row.paused_at, row.pause_until = utcnow() - timedelta(hours=2), utcnow() - timedelta(minutes=1)
            session.add(row)
            await session.commit()
        assert not (await get_ip(ip["id"])).is_paused  # déjà considérée reprise avant le scheduler
        async with session_factory()() as session:
            assert await inventory.resume_due_pauses(session) == 1
            await session.commit()
        assert (await get_ip(ip["id"])).paused_at is None

    async def test_echeance_dans_le_passe_refusee(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        response = await client.post(
            f"{API}/ips/{ip['id']}/pause", json={"until": "2020-01-01T00:00:00Z"}, headers=writer
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "until"


class TestApi:
    async def test_problems_summary_et_filtre(self, client):
        _csrf, reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        assert len((await client.get(f"{API}/problems", headers=reader)).json()) == 1
        assert (await client.post(f"{API}/ips/{ip['id']}/pause", json={}, headers=reader)).status_code == 403
        await client.post(f"{API}/ips/{ip['id']}/pause", json={}, headers=writer)

        assert (await client.get(f"{API}/problems", headers=reader)).json() == []
        summary = (await client.get(f"{API}/summary", headers=reader)).json()
        assert summary["down"] == 0 and summary["paused"] == 1
        paused = (await client.get(f"{API}/ips", params={"health": "paused"}, headers=reader)).json()
        assert [i["id"] for i in paused["items"]] == [ip["id"]]
        assert (await client.get(f"{API}/ips", params={"health": "dark_red"}, headers=reader)).json()["total"] == 0

        resumed = (await client.post(f"{API}/ips/{ip['id']}/resume", headers=writer)).json()
        assert resumed["paused"] is False and resumed["pause"] is None
        assert len((await client.get(f"{API}/problems", headers=reader)).json()) == 1
        async with session_factory()() as session:
            actions = [e.action for e in (await session.exec(select(AuditLog).where(AuditLog.entity_type == "ip"))).all()]
        assert "pause" in actions and "resume" in actions


class TestUi:
    async def test_manager_met_en_pause_et_reprend(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        headers = {"X-CSRF-Token": csrf}
        form = await client.get(f"/ips/{ip['id']}/pause")
        assert form.status_code == 200 and "Quand l'hôte répond de nouveau" in form.text

        response = await client.post(f"/ips/{ip['id']}/pause", data={"reason": "coupé", "resume": "1w"}, headers=headers)
        assert response.status_code == 204
        row = await get_ip(ip["id"])
        assert row.is_paused and not row.pause_until_recovery
        assert timedelta(days=6) < row.pause_until - utcnow() <= timedelta(days=7)

        page = (await client.get(f"/subnets/{ip['vlan_id']}")).text
        assert "health-paused" in page and "Reprendre le suivi" in page

        assert (await client.post(f"/ips/{ip['id']}/resume", headers=headers)).status_code == 204
        assert not (await get_ip(ip["id"])).is_paused

    async def test_lecture_seule_ne_peut_pas_mettre_en_pause(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await down_ip(client, writer)
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await create_user(client, csrf, "bob", "bobpassword", "user")
        await client.post("/logout", headers={"X-CSRF-Token": csrf})
        csrf_bob = await login(client, "bob", "bobpassword")
        response = await client.post(f"/ips/{ip['id']}/pause", data={}, headers={"X-CSRF-Token": csrf_bob})
        assert response.status_code == 403
        assert "Mettre en pause" not in (await client.get(f"/subnets/{ip['vlan_id']}")).text


async def test_scheduler_reprend_un_hote_revenu(client):
    """Bout en bout : hôte en pause « jusqu'au retour », coupé puis rallumé (vrai port TCP local)."""
    import asyncio

    from app.services.monitor import run_due_checks

    _csrf, _reader, writer = await setup(client)
    vlan = (await client.post(f"{API}/vlans", json={"name": "lo", "cidr": "127.0.0.0/29"}, headers=writer)).json()
    ip = (await client.post(f"{API}/vlans/{vlan['id']}/ips", json={"address": "127.0.0.1"}, headers=writer)).json()

    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()  # port fermé : l'hôte est « éteint »
    await client.post(f"{API}/ips/{ip['id']}/monitors", json={"protocol": "tcp", "port": port}, headers=writer)
    await client.post(f"{API}/ips/{ip['id']}/pause", json={"reason": "coupé"}, headers=writer)

    async def tick() -> None:
        async with session_factory()() as session:
            for target in (await session.exec(select(MonitorTarget))).all():
                target.last_checked_at = None  # rend la cible « due »
                session.add(target)
            await session.commit()
            await run_due_checks(session)

    await tick()  # toujours éteint : reste en pause
    assert (await get_ip(ip["id"])).is_paused

    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)  # rallumé
    try:
        await tick()
    finally:
        server.close()
        await server.wait_closed()
    assert not (await get_ip(ip["id"])).is_paused
