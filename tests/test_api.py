"""API v1 : clés de comptes de service, moindre privilège, règles métier partagées, audit."""

import html
import re
from datetime import timedelta

from sqlmodel import select

from app.database import session_factory
from app.models import ApiKey, AuditLog, ServiceAccount, utcnow
from app.services import apikeys
from tests.conftest import ADMIN_PASSWORD, login

API = "/api/v1"


async def make_key(http, csrf: str, account: str, role: str = "user", scope: str = "read", **extra) -> str:
    """Crée (si besoin) un compte de service via l'UI puis une clé ; retourne la clé en clair."""
    async with session_factory()() as session:
        existing = (await session.exec(select(ServiceAccount).where(ServiceAccount.name == account))).first()
    if existing is None:
        response = await http.post(
            "/service-accounts", data={"name": account, "role": role}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 204, response.text
        async with session_factory()() as session:
            existing = (await session.exec(select(ServiceAccount).where(ServiceAccount.name == account))).first()
    response = await http.post(
        f"/service-accounts/{existing.id}/keys",
        data={"name": f"{account}-key", "scope": scope, **extra},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    match = re.search(r'value="(gpm_[^"]+)"', response.text)
    assert match, response.text
    return html.unescape(match.group(1))


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def setup(client) -> tuple[str, dict, dict]:
    """(csrf admin, en-têtes clé lecture, en-têtes clé écriture) ; session UI fermée ensuite."""
    csrf = await login(client, "admin", ADMIN_PASSWORD)
    reader = bearer(await make_key(client, csrf, "lecteur"))
    writer = bearer(await make_key(client, csrf, "ansible", role="manager", scope="write"))
    client.cookies.clear()  # l'API ne doit dépendre d'aucune session
    return csrf, reader, writer


async def new_vlan(client, writer, cidr="10.20.0.0/29", **extra) -> dict:
    response = await client.post(f"{API}/vlans", json={"name": "lab", "cidr": cidr, **extra}, headers=writer)
    assert response.status_code == 201, response.text
    return response.json()


class TestAuthentification:
    async def test_sans_cle_401(self, client):
        response = await client.get(f"{API}/vlans")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
        assert response.headers["www-authenticate"] == "Bearer"

    async def test_cle_inconnue_401(self, client):
        for value in ["n-importe-quoi", "gpm_deadbeef_faux", ""]:
            response = await client.get(f"{API}/whoami", headers=bearer(value))
            assert response.status_code == 401, value

    async def test_session_ui_ne_suffit_pas(self, client):
        await login(client, "admin", ADMIN_PASSWORD)
        assert (await client.get(f"{API}/vlans")).status_code == 401

    async def test_whoami_et_pas_de_cookie(self, client):
        _csrf, reader, writer = await setup(client)
        response = await client.get(f"{API}/whoami", headers=reader)
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        body = response.json()
        assert body["service_account"] == "lecteur" and body["can_write"] is False
        assert (await client.get(f"{API}/whoami", headers=writer)).json()["can_write"] is True

    async def test_cle_stockee_hachee_uniquement(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        raw = await make_key(client, csrf, "lecteur")
        async with session_factory()() as session:
            key = (await session.exec(select(ApiKey))).one()
            audits = (await session.exec(select(AuditLog).where(AuditLog.entity_type == "api_key"))).all()
        assert key.key_hash == apikeys.hash_key(raw) and raw not in key.key_hash
        assert key.created_by == "admin"
        assert raw not in str([a.changes for a in audits])
        # La page de gestion ne réaffiche jamais la clé.
        assert raw not in (await client.get("/service-accounts")).text

    async def test_revocation(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        key = bearer(await make_key(client, csrf, "lecteur"))
        assert (await client.get(f"{API}/whoami", headers=key)).status_code == 200
        response = await client.post("/api-keys/1/revoke", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 204
        assert (await client.get(f"{API}/whoami", headers=key)).status_code == 401

    async def test_expiration(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        tomorrow = (utcnow() + timedelta(days=1)).date().isoformat()
        key = bearer(await make_key(client, csrf, "lecteur", expires_on=tomorrow))
        assert (await client.get(f"{API}/whoami", headers=key)).status_code == 200
        async with session_factory()() as session:
            row = (await session.exec(select(ApiKey))).one()
            row.expires_at = utcnow() - timedelta(seconds=1)
            session.add(row)
            await session.commit()
        assert (await client.get(f"{API}/whoami", headers=key)).status_code == 401

    async def test_date_expiration_passee_refusee(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await make_key(client, csrf, "lecteur")
        response = await client.post(
            "/service-accounts/1/keys",
            data={"name": "x", "expires_on": "2020-01-01"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 422

    async def test_compte_desactive(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        key = bearer(await make_key(client, csrf, "lecteur"))
        response = await client.patch(
            "/service-accounts/1", data={"name": "lecteur", "role": "user"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 204
        assert (await client.get(f"{API}/whoami", headers=key)).status_code == 401


class TestMoindrePrivilege:
    async def test_cle_lecture_ne_peut_pas_ecrire(self, client):
        _csrf, reader, writer = await setup(client)
        vlan = await new_vlan(client, writer)
        assert (await client.get(f"{API}/vlans", headers=reader)).status_code == 200
        for method, url, body in [
            ("POST", "/vlans", {"name": "x", "cidr": "10.9.0.0/24"}),
            ("PATCH", f"/vlans/{vlan['id']}", {"name": "y"}),
            ("DELETE", f"/vlans/{vlan['id']}", None),
            ("POST", f"/vlans/{vlan['id']}/ips", {"address": "10.20.0.2"}),
            ("POST", f"/vlans/{vlan['id']}/allocate", {}),
            ("PATCH", "/network", {"name": "x"}),
        ]:
            response = await client.request(method, API + url, json=body, headers=reader)
            assert response.status_code == 403, f"{method} {url} → {response.status_code}"
            assert response.json()["error"]["code"] == "read_only"

    async def test_cle_ecriture_refusee_sur_compte_non_manager(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await make_key(client, csrf, "lecteur")
        response = await client.post(
            "/service-accounts/1/keys", data={"name": "rw", "scope": "write"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 422

    async def test_compte_retrograde_perd_l_ecriture(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        writer = bearer(await make_key(client, csrf, "ansible", role="manager", scope="write"))
        await new_vlan(client, writer)
        await client.patch(
            "/service-accounts/1",
            data={"name": "ansible", "role": "user", "is_active": "on"},
            headers={"X-CSRF-Token": csrf},
        )
        response = await client.post(f"{API}/vlans", json={"name": "x", "cidr": "10.9.0.0/24"}, headers=writer)
        assert response.status_code == 403
        assert (await client.get(f"{API}/vlans", headers=writer)).status_code == 200

    async def test_gestion_des_comptes_reservee_aux_managers(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await client.post(
            "/users", data={"username": "bob", "password": "bobpassword", "role": "user"},
            headers={"X-CSRF-Token": csrf},
        )
        await client.post("/logout", headers={"X-CSRF-Token": csrf})
        csrf_bob = await login(client, "bob", "bobpassword")
        assert (await client.get("/service-accounts")).status_code == 403
        response = await client.post(
            "/service-accounts", data={"name": "x", "role": "manager"}, headers={"X-CSRF-Token": csrf_bob}
        )
        assert response.status_code == 403


class TestReglesMetier:
    async def test_crud_vlan_et_ip(self, client):
        _csrf, _reader, writer = await setup(client)
        vlan = await new_vlan(client, writer, cidr="192.168.50.0/24", vlan_tag=50, gateway="192.168.50.1")
        assert vlan["capacity"] == 254 and vlan["vlan_tag"] == 50

        response = await client.post(
            f"{API}/vlans/{vlan['id']}/ips",
            json={"address": "192.168.50.10", "hostname": "nas", "mac": "AA-BB-CC-DD-EE-FF"},
            headers=writer,
        )
        assert response.status_code == 201, response.text
        ip = response.json()
        assert ip["mac"] == "aa:bb:cc:dd:ee:ff" and ip["status"] == "utilisee" and ip["health"] is None
        assert ip["created_at"].endswith("Z")

        # PATCH partiel : les champs non envoyés sont conservés, null efface.
        response = await client.patch(f"{API}/ips/{ip['id']}", json={"location": "baie 1"}, headers=writer)
        assert response.status_code == 200, response.text
        assert response.json()["hostname"] == "nas" and response.json()["location"] == "baie 1"
        response = await client.patch(f"{API}/ips/{ip['id']}", json={"hostname": None}, headers=writer)
        assert response.json()["hostname"] is None and response.json()["location"] == "baie 1"

        response = await client.patch(f"{API}/vlans/{vlan['id']}", json={"name": "serveurs"}, headers=writer)
        assert response.json()["name"] == "serveurs" and response.json()["gateway"] == "192.168.50.1"

        found = (await client.get(f"{API}/ips", params={"q": "baie"}, headers=writer)).json()
        assert found["total"] == 1 and found["items"][0]["address"] == "192.168.50.10"

        assert (await client.delete(f"{API}/ips/{ip['id']}", headers=writer)).status_code == 204
        assert (await client.get(f"{API}/ips/{ip['id']}", headers=writer)).status_code == 404
        assert (await client.delete(f"{API}/vlans/{vlan['id']}", headers=writer)).status_code == 204

    async def test_memes_conflits_que_l_ui(self, client):
        _csrf, _reader, writer = await setup(client)
        vlan = await new_vlan(client, writer, cidr="10.20.0.0/24")
        ips = f"{API}/vlans/{vlan['id']}/ips"
        cases = [
            (f"{API}/vlans", {"name": "x", "cidr": "10.20.0.128/25"}, "cidr"),  # chevauchement
            (f"{API}/vlans", {"name": "x", "cidr": "10.21.0.1/24"}, "cidr"),  # bits hôte
            (f"{API}/vlans", {"name": "x", "cidr": "10.22.0.0/24", "gateway": "10.9.9.9"}, "gateway"),
            (f"{API}/vlans", {"name": " ", "cidr": "10.23.0.0/24"}, "name"),
            (f"{API}/vlans", {"name": "x", "cidr": "10.24.0.0/24", "vlan_tag": 5000}, "vlan_id"),
            (ips, {"address": "10.99.0.1"}, "address"),  # hors subnet
            (ips, {"address": "10.20.0.0"}, "address"),  # adresse réseau
            (ips, {"address": "10.20.0.5", "mac": "zz"}, "mac"),
        ]
        for url, body, field in cases:
            response = await client.post(url, json=body, headers=writer)
            assert response.status_code == 422, f"{body} → {response.status_code}"
            error = response.json()["error"]
            assert error["code"] == "validation_error"
            assert field in [d["field"] for d in error["details"]], error

        assert (await client.post(ips, json={"address": "10.20.0.5"}, headers=writer)).status_code == 201
        response = await client.post(ips, json={"address": "10.20.0.5"}, headers=writer)
        assert response.status_code == 422 and "already exists" in response.json()["error"]["message"]
        # Messages localisables.
        response = await client.post(
            ips, json={"address": "10.20.0.5"}, headers={**writer, "Accept-Language": "fr"}
        )
        assert "existe déjà" in response.json()["error"]["message"]
        # Rétrécir le CIDR en laissant une IP dehors : refusé.
        response = await client.patch(f"{API}/vlans/{vlan['id']}", json={"cidr": "10.20.0.128/25"}, headers=writer)
        assert response.status_code == 422

    async def test_corps_invalide_format_d_erreur_commun(self, client):
        _csrf, _reader, writer = await setup(client)
        response = await client.post(f"{API}/vlans", json={"name": "x", "inconnu": 1}, headers=writer)
        assert response.status_code == 422
        fields = [d["field"] for d in response.json()["error"]["details"]]
        assert "cidr" in fields and "inconnu" in fields
        assert (await client.get(f"{API}/vlans/999", headers=writer)).json()["error"]["code"] == "not_found"
        assert (await client.get(f"{API}/nexiste-pas", headers=writer)).json()["error"]["code"] == "not_found"

    async def test_api_et_ui_voient_les_memes_donnees(self, client):
        _csrf, _reader, writer = await setup(client)
        vlan = await new_vlan(client, writer, cidr="10.20.0.0/24")
        await client.post(
            f"{API}/vlans/{vlan['id']}/ips", json={"address": "10.20.0.7", "hostname": "via-api"}, headers=writer
        )
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        assert "via-api" in (await client.get(f"/subnets/{vlan['id']}")).text
        # … et l'UI refuse le doublon créé par l'API.
        response = await client.post(
            f"/subnets/{vlan['id']}/ips", data={"address": "10.20.0.7"}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 422


class TestAllocation:
    async def test_prochaine_ip_libre(self, client):
        _csrf, reader, writer = await setup(client)
        # /29 : utilisables .1 à .6 ; passerelle .1 jamais proposée.
        vlan = await new_vlan(client, writer, cidr="10.20.0.0/29", gateway="10.20.0.1")
        base = f"{API}/vlans/{vlan['id']}"
        await client.post(f"{base}/ips", json={"address": "10.20.0.2"}, headers=writer)
        await client.post(f"{base}/ips", json={"address": "10.20.0.3", "status": "libre"}, headers=writer)

        assert (await client.get(f"{base}/next-free", headers=reader)).json() == {"address": "10.20.0.3"}

        response = await client.post(f"{base}/allocate", json={"hostname": "vm-1"}, headers=writer)
        assert response.status_code == 201, response.text
        first = response.json()
        # La ligne « libre » existante est réutilisée, pas dupliquée.
        assert first["address"] == "10.20.0.3" and first["status"] == "reservee" and first["hostname"] == "vm-1"

        got = []
        for _ in range(3):
            response = await client.post(f"{base}/allocate", json={"status": "utilisee"}, headers=writer)
            assert response.status_code == 201
            got.append(response.json()["address"])
        assert got == ["10.20.0.4", "10.20.0.5", "10.20.0.6"]

        response = await client.post(f"{base}/allocate", json={}, headers=writer)
        assert response.status_code == 409 and response.json()["error"]["code"] == "subnet_full"
        assert (await client.get(f"{base}/next-free", headers=reader)).status_code == 409

    async def test_allocation_statut_libre_refuse(self, client):
        _csrf, _reader, writer = await setup(client)
        vlan = await new_vlan(client, writer)
        response = await client.post(f"{API}/vlans/{vlan['id']}/allocate", json={"status": "libre"}, headers=writer)
        assert response.status_code == 422
        assert (await client.post(f"{API}/vlans/999/allocate", json={}, headers=writer)).status_code == 404


class TestSupervision:
    async def test_cibles_et_pannes(self, client):
        _csrf, reader, writer = await setup(client)
        vlan = await new_vlan(client, writer, cidr="127.0.0.0/24")
        ip = (
            await client.post(f"{API}/vlans/{vlan['id']}/ips", json={"address": "127.0.0.1"}, headers=writer)
        ).json()
        monitors = f"{API}/ips/{ip['id']}/monitors"
        response = await client.post(monitors, json={"protocol": "tcp"}, headers=writer)
        assert response.status_code == 422 and response.json()["error"]["details"][0]["field"] == "port"
        response = await client.post(monitors, json={"port": 80, "interval_seconds": 1}, headers=writer)
        assert response.status_code == 422

        response = await client.post(monitors, json={"port": 1, "label": "ferme"}, headers=writer)
        assert response.status_code == 201, response.text
        target = response.json()
        assert target["health"] == "unknown" and target["interval_seconds"] == 60

        # Le check est permis en lecture seule (comme le bouton « Vérifier » de l'UI).
        response = await client.post(f"{API}/ips/{ip['id']}/check", headers=reader)
        assert response.status_code == 200, response.text
        checked = response.json()
        assert checked["health"] == "red" and checked["monitors"][0]["last_status"] == "down"

        problems = (await client.get(f"{API}/problems", headers=reader)).json()
        assert [p["ip"]["address"] for p in problems] == ["127.0.0.1"]
        assert (await client.get(f"{API}/summary", headers=reader)).json()["down"] == 1
        assert (await client.get(f"{API}/ips", params={"health": "red"}, headers=reader)).json()["total"] == 1

        response = await client.patch(f"{API}/monitors/{target['id']}", json={"enabled": False}, headers=writer)
        assert response.json()["enabled"] is False and response.json()["port"] == 1
        assert (await client.get(f"{API}/problems", headers=reader)).json() == []
        assert (await client.delete(f"{API}/monitors/{target['id']}", headers=writer)).status_code == 204


class TestAudit:
    async def test_actions_api_tracees_avec_compte_et_cle(self, client):
        _csrf, reader, writer = await setup(client)
        vlan = await new_vlan(client, writer)
        async with session_factory()() as session:
            entry = (await session.exec(select(AuditLog).where(AuditLog.entity_type == "subnet"))).one()
            key = (await session.exec(select(ApiKey).where(ApiKey.name == "ansible-key"))).one()
        assert entry.username == "ansible" and entry.user_id is None
        assert entry.api_key_id == key.id and entry.service_account_id == key.service_account_id
        assert entry.api_key_label == f"ansible-key ({key.prefix})"

        page = (await client.get(f"{API}/audit", params={"entity_type": "subnet"}, headers=reader)).json()
        assert page["total"] == 1
        item = page["items"][0]
        assert item["via_api"] is True and item["entity_id"] == vlan["id"] and item["username"] == "ansible"

        await login(client, "admin", ADMIN_PASSWORD)
        text = (await client.get("/audit")).text
        assert "ansible-key" in text and ">API<" in text


class TestInstance:
    async def test_cle_requise(self, client):
        assert (await client.get(f"{API}/instance")).status_code == 401

    async def test_empreintes_du_certificat_servi(self, client):
        import shutil
        import subprocess

        from app import __version__, tls

        _csrf, reader, _writer = await setup(client)
        response = await client.get(f"{API}/instance", headers=reader)
        assert response.status_code == 200, response.text
        data = response.json()
        info = tls.current()
        assert data["version"] == __version__
        assert data["tls"] == tls.as_dict(info)  # mêmes champs que `python -m app.tls show --json`
        assert data["tls"]["mode"] == "auto" and data["tls"]["source"] == "self-signed"
        assert data["tls"]["not_after"].endswith("Z") and "localhost" in data["tls"]["sans"]
        if shutil.which("openssl"):
            out = subprocess.run(
                ["openssl", "x509", "-in", str(info.certfile), "-noout", "-fingerprint", "-sha256"],
                capture_output=True, text=True, check=True,
            ).stdout
            assert out.strip().split("=", 1)[1] == data["tls"]["sha256"]

    async def test_tls_off(self, test_env, monkeypatch):
        from httpx import ASGITransport, AsyncClient

        import app.config as config_module
        from app.main import create_app

        monkeypatch.setenv("GUIPAM_TLS", "off")
        config_module.get_settings.cache_clear()
        application = create_app()
        async with application.router.lifespan_context(application):
            async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as http:
                _csrf, reader, _writer = await setup(http)
                data = (await http.get(f"{API}/instance", headers=reader)).json()
        assert data["tls"] == {
            "mode": "off", "source": None, "not_after": None, "sha256": None, "spki_sha256": None, "sans": []
        }


class TestSpecification:
    async def test_openapi_public_et_complet(self, client):
        response = await client.get(f"{API}/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert spec["info"]["title"] == "GuiPAM API"
        assert "Authorization: Bearer" in spec["info"]["description"]
        assert spec["components"]["securitySchemes"]["ApiKey"]["scheme"] == "bearer"
        operations = {
            op["operationId"]: op for path in spec["paths"].values() for op in path.values()
        }
        for name in ["list_vlans", "allocate_ip", "list_problems", "create_monitor", "whoami", "update_ip", "instance"]:
            assert name in operations, name
            assert operations[name]["summary"] and operations[name]["security"]
        tls_schema = spec["components"]["schemas"]["TlsOut"]["properties"]
        assert "pin" in tls_schema["spki_sha256"]["description"]
        # Les routes HTML de l'UI n'apparaissent pas dans la spécification.
        assert "/login" not in spec["paths"] and "/subnets" not in spec["paths"]
        assert (await client.get(f"{API}/docs")).status_code == 200
