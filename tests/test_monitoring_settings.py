"""Réglages du suivi dans les Paramètres du réseau : intervalle par défaut et seuils du code couleur.

Valeur d'instance (GUIPAM_*) tant que le réseau ne la redéfinit pas ; UI et API passent par
`inventory.update_reseau` et voient donc les mêmes règles.
"""

import json
from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from sqlmodel import select

import app.config as config_module
from app.database import session_factory
from app.models import RESEAU_SINGLETON_ID, AuditLog, CheckStatus, MonitorTarget, Reseau, utcnow
from app.services import monitor
from tests.conftest import ADMIN_PASSWORD, login
from tests.test_api import API, new_vlan, setup

DEFAULTS = {
    "default_check_interval": 60,
    "health_warn_intervals": 2,
    "health_red_failures": 10,
    "health_dark_red_seconds": 604800,
}


def settings_of(body: dict) -> dict:
    return {k: body[k] for k in DEFAULTS}


async def stored() -> dict:
    async with session_factory()() as session:
        reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
        return {k: getattr(reseau, k) for k in DEFAULTS}


async def new_ip(client, writer, address="127.0.0.1") -> dict:
    vlan = await new_vlan(client, writer, cidr="127.0.0.0/24")
    response = await client.post(f"{API}/vlans/{vlan['id']}/ips", json={"address": address}, headers=writer)
    assert response.status_code == 201, response.text
    return response.json()


async def fail_target(target_id: int, failures: int, ok_age: int) -> None:
    """Met une cible dans l'état « a déjà répondu, en panne depuis `failures` vérifications »."""
    async with session_factory()() as session:
        target = await session.get(MonitorTarget, target_id)
        target.last_status = CheckStatus.down
        target.consecutive_failures = failures
        target.last_ok_at = utcnow() - timedelta(seconds=ok_age)
        target.last_checked_at = utcnow()
        session.add(target)
        await session.commit()


class TestValeursParDefaut:
    async def test_instance_neuve_valeurs_d_instance(self, client):
        _csrf, reader, _writer = await setup(client)
        body = (await client.get(f"{API}/network", headers=reader)).json()
        assert settings_of(body) == DEFAULTS
        # Rien n'est écrit en base tant qu'on ne règle rien : la valeur d'instance s'applique.
        assert await stored() == dict.fromkeys(DEFAULTS)

    async def test_variables_d_environnement_valeur_initiale(self, test_env, monkeypatch):
        monkeypatch.setenv("GUIPAM_DEFAULT_CHECK_INTERVAL", "300")
        monkeypatch.setenv("GUIPAM_HEALTH_RED_FAILURES", "4")
        monkeypatch.setenv("GUIPAM_HEALTH_DARK_RED_SECONDS", "7200")
        # Anciennes variables en secondes (≤ v0.3) : ignorées, sans empêcher le démarrage.
        monkeypatch.setenv("GUIPAM_HEALTH_WARN_SECONDS", "120")
        monkeypatch.setenv("GUIPAM_HEALTH_RED_SECONDS", "600")
        config_module.get_settings.cache_clear()
        from app.main import create_app

        application = create_app()
        async with application.router.lifespan_context(application):
            async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
                _csrf, reader, writer = await setup(http)
                body = (await http.get(f"{API}/network", headers=reader)).json()
                assert settings_of(body) == {**DEFAULTS, "default_check_interval": 300, "health_red_failures": 4, "health_dark_red_seconds": 7200}
                # Le réglage du réseau prend le pas sur la variable ; null y revient.
                body = (await http.patch(f"{API}/network", json={"health_red_failures": 6}, headers=writer)).json()
                assert body["health_red_failures"] == 6
                body = (await http.patch(f"{API}/network", json={"health_red_failures": None}, headers=writer)).json()
                assert body["health_red_failures"] == 4

    async def test_reglages_remis_a_zero_a_l_arret(self, test_env):
        """Le cache des réglages ne survit pas à l'instance (sinon il fuirait d'un test à l'autre)."""
        from app.main import create_app

        application = create_app()
        async with application.router.lifespan_context(application):
            async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
                _csrf, _reader, writer = await setup(http)
                await http.patch(f"{API}/network", json={"health_red_failures": 3}, headers=writer)
                assert monitor.monitoring().health_red_failures == 3
        assert monitor.monitoring() == monitor.instance_monitoring()


class TestIntervalleParDefaut:
    async def test_nouvelles_cibles_seulement_et_toujours_modifiable(self, client):
        _csrf, _reader, writer = await setup(client)
        ip = await new_ip(client, writer)
        monitors = f"{API}/ips/{ip['id']}/monitors"
        ancienne = (await client.post(monitors, json={"port": 22}, headers=writer)).json()
        assert ancienne["interval_seconds"] == 60

        response = await client.patch(f"{API}/network", json={"default_check_interval": 180}, headers=writer)
        assert response.status_code == 200 and response.json()["default_check_interval"] == 180

        nouvelle = (await client.post(monitors, json={"port": 80}, headers=writer)).json()
        assert nouvelle["interval_seconds"] == 180
        # Toujours modifiable à la création de la cible.
        precise = (await client.post(monitors, json={"port": 443, "interval_seconds": 30}, headers=writer)).json()
        assert precise["interval_seconds"] == 30
        # Les cibles existantes gardent leur intervalle.
        assert (await client.get(f"{API}/monitors/{ancienne['id']}", headers=writer)).json()["interval_seconds"] == 60

    async def test_formulaire_de_cible_pre_rempli(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        h = {"X-CSRF-Token": csrf}
        await client.post("/subnets", data={"name": "LAN", "cidr": "192.168.1.0/24"}, headers=h)
        await client.post("/subnets/1/ips", data={"address": "192.168.1.10"}, headers=h)
        form = {"name": "Maison", "default_check_interval": "180", "health_dark_red_value": "7", "health_dark_red_unit": "days"}
        assert (await client.post("/reseau", data=form, headers=h)).status_code == 204
        page = (await client.get("/ips/1/monitors/new")).text
        assert 'name="interval_seconds" type="number" min="5" max="86400"' in page and 'value="180"' in page
        # Créée sans préciser l'intervalle : le défaut du réseau.
        assert (await client.post("/ips/1/monitors", data={"protocol": "tcp", "port": "22"}, headers=h)).status_code == 204
        async with session_factory()() as session:
            assert (await session.exec(select(MonitorTarget))).one().interval_seconds == 180


class TestSeuils:
    async def test_seuil_rouge_en_nombre_d_echecs(self, client):
        _csrf, reader, writer = await setup(client)
        ip = await new_ip(client, writer)
        target = (await client.post(f"{API}/ips/{ip['id']}/monitors", json={"port": 22}, headers=writer)).json()
        url = f"{API}/monitors/{target['id']}"
        await fail_target(target["id"], failures=3, ok_age=200)
        assert (await client.get(url, headers=reader)).json()["health"] == "warn"
        assert (await client.get(f"{API}/ips/{ip['id']}", headers=reader)).json()["health"] == "warn"

        await client.patch(f"{API}/network", json={"health_red_failures": 3}, headers=writer)
        assert (await client.get(url, headers=reader)).json()["health"] == "red"
        assert (await client.get(f"{API}/ips", params={"health": "red"}, headers=reader)).json()["total"] == 1

    async def test_seuil_rouge_fonce_en_duree(self, client):
        _csrf, reader, writer = await setup(client)
        ip = await new_ip(client, writer)
        target = (await client.post(f"{API}/ips/{ip['id']}/monitors", json={"port": 22}, headers=writer)).json()
        url = f"{API}/monitors/{target['id']}"
        await fail_target(target["id"], failures=50, ok_age=2 * 86400)
        assert (await client.get(url, headers=reader)).json()["health"] == "red"  # 2 jours < 1 semaine
        await client.patch(f"{API}/network", json={"health_dark_red_seconds": 86400}, headers=writer)
        assert (await client.get(url, headers=reader)).json()["health"] == "dark_red"

    async def test_seuil_ambre_relatif_a_l_intervalle_de_la_cible(self, client):
        _csrf, reader, writer = await setup(client)
        ip = await new_ip(client, writer)
        monitors = f"{API}/ips/{ip['id']}/monitors"
        rapide = (await client.post(monitors, json={"port": 22, "interval_seconds": 5}, headers=writer)).json()
        lente = (await client.post(monitors, json={"port": 80, "interval_seconds": 86400}, headers=writer)).json()
        async with session_factory()() as session:
            for item in (rapide, lente):
                target = await session.get(MonitorTarget, item["id"])
                target.last_status = CheckStatus.up
                # Dernier succès il y a 2 h : périmé pour la rapide (le tick des tests vaut 1 h), normal pour la lente.
                target.last_ok_at = target.last_checked_at = utcnow() - timedelta(hours=2)
                session.add(target)
            await session.commit()
        assert (await client.get(f"{API}/monitors/{rapide['id']}", headers=reader)).json()["health"] == "warn"
        assert (await client.get(f"{API}/monitors/{lente['id']}", headers=reader)).json()["health"] == "ok"

    async def test_valeurs_hors_bornes_refusees(self, client):
        _csrf, _reader, writer = await setup(client)
        for field, value in [
            ("default_check_interval", 1),
            ("health_warn_intervals", 0),
            ("health_red_failures", 0),
            ("health_dark_red_seconds", 5),
        ]:
            response = await client.patch(f"{API}/network", json={field: value}, headers=writer)
            assert response.status_code == 422, (field, response.text)
            assert response.json()["error"]["details"][0]["field"] == field
        assert await stored() == dict.fromkeys(DEFAULTS)

    async def test_patch_partiel_ne_touche_pas_aux_autres_reglages(self, client):
        _csrf, _reader, writer = await setup(client)
        await client.patch(f"{API}/network", json={"health_red_failures": 5, "default_check_interval": 120}, headers=writer)
        body = (await client.patch(f"{API}/network", json={"description": "labo"}, headers=writer)).json()
        assert body["description"] == "labo"
        assert settings_of(body) == {**DEFAULTS, "health_red_failures": 5, "default_check_interval": 120}


class TestFormulaire:
    async def test_affichage_et_enregistrement(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        h = {"X-CSRF-Token": csrf}
        page = (await client.get("/reseau/edit")).text
        assert 'name="default_check_interval"' in page and 'name="health_warn_intervals"' in page
        assert 'name="health_dark_red_value" min="1" class="flex-1" value="7"' in page  # 1 semaine = 7 jours
        assert '<option value="days" selected>' in page

        form = {
            "name": "Maison",
            "default_check_interval": "180",
            "health_warn_intervals": "3",
            "health_red_failures": "5",
            "health_dark_red_value": "36",
            "health_dark_red_unit": "hours",
        }
        assert (await client.post("/reseau", data=form, headers=h)).status_code == 204
        assert await stored() == {
            "default_check_interval": 180,
            "health_warn_intervals": 3,
            "health_red_failures": 5,
            "health_dark_red_seconds": 36 * 3600,
        }
        page = (await client.get("/reseau/edit")).text
        assert 'value="36"' in page and '<option value="hours" selected>' in page

        async with session_factory()() as session:
            entry = (
                await session.exec(select(AuditLog).where(AuditLog.entity_type == "reseau").order_by(AuditLog.id.desc()))  # type: ignore[union-attr]
            ).first()
        assert entry.action == "update" and "health_red_failures" in json.dumps(entry.changes)

    async def test_champ_vide_revient_a_la_valeur_d_instance(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        h = {"X-CSRF-Token": csrf}
        form = {"name": "Maison", "health_red_failures": "5", "health_dark_red_value": "2", "health_dark_red_unit": "days"}
        await client.post("/reseau", data=form, headers=h)
        assert (await stored())["health_red_failures"] == 5
        await client.post("/reseau", data={"name": "Maison"}, headers=h)
        assert await stored() == dict.fromkeys(DEFAULTS)
        assert monitor.monitoring().health_red_failures == 10

    async def test_erreur_champ_signale(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        form = {"name": "Maison", "health_red_failures": "0", "health_dark_red_value": "abc"}
        response = await client.post("/reseau", data=form, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 422
        assert 'data-error-fields="health_red_failures health_dark_red_value"' in response.text
        assert await stored() == dict.fromkeys(DEFAULTS)

    async def test_reserve_aux_managers(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        h = {"X-CSRF-Token": csrf}
        await client.post("/users", data={"username": "lecteur", "password": "motdepasse-lecteur", "role": "user"}, headers=h)
        client.cookies.clear()
        csrf = await login(client, "lecteur", "motdepasse-lecteur")
        response = await client.post("/reseau", data={"name": "x", "health_red_failures": "1"}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 403
        assert await stored() == dict.fromkeys(DEFAULTS)


class TestSauvegarde:
    async def test_reglages_restaures_et_reappliques(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        h = {"X-CSRF-Token": csrf}
        form = {"name": "Maison", "health_red_failures": "5", "health_dark_red_value": "3", "health_dark_red_unit": "days"}
        await client.post("/reseau", data=form, headers=h)
        saved = (await client.get("/backup.json")).json()
        assert saved["data"]["reseau"][0]["health_red_failures"] == 5

        await client.post("/reseau", data={"name": "Maison"}, headers=h)
        assert monitor.monitoring().health_red_failures == 10
        response = await client.post(
            "/restore", files={"file": ("b.json", json.dumps(saved), "application/json")}, headers=h
        )
        assert response.status_code == 204, response.text
        assert (await stored())["health_dark_red_seconds"] == 3 * 86400
        # Appliqués tout de suite, sans redémarrage ni passage par l'interface.
        assert monitor.monitoring().health_red_failures == 5

    async def test_export_d_avant_les_reglages_tolere(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        h = {"X-CSRF-Token": csrf}
        await client.post("/reseau", data={"name": "Maison", "health_red_failures": "5"}, headers=h)
        saved = (await client.get("/backup.json")).json()
        for row in saved["data"]["reseau"]:
            for field in DEFAULTS:
                del row[field]
        response = await client.post(
            "/restore", files={"file": ("b.json", json.dumps(saved), "application/json")}, headers=h
        )
        assert response.status_code == 204, response.text
        assert await stored() == dict.fromkeys(DEFAULTS)
        assert monitor.monitoring() == monitor.instance_monitoring()
