"""Continuité des données : migration depuis un ancien schéma, sauvegarde JSON, instantanés."""

import copy
import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlmodel import select

from app.database import session_factory
from app.models import IPAddress, Subnet, User
from app.services import backup
from tests.conftest import ADMIN_PASSWORD, login

ROOT = Path(__file__).parent.parent
# Schéma de la première version publiée (v0.1.0). Ne jamais changer : c'est le point
# de départ dont toute version future doit savoir migrer les données.
V0_1_REVISION = "8a68124c8405"


def alembic_config(db_path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


async def populate(client) -> str:
    csrf = await login(client, "admin", ADMIN_PASSWORD)
    h = {"X-CSRF-Token": csrf}
    await client.post("/subnets", data={"name": "LAN", "cidr": "192.168.1.0/24", "vlan_id": "10"}, headers=h)
    await client.post("/subnets/1/ips", data={"address": "192.168.1.32", "hostname": "pve", "mac": "aa:bb:cc:dd:ee:ff"}, headers=h)
    await client.post("/ips/1/monitors", data={"protocol": "tcp", "port": "8006", "label": "ui"}, headers=h)
    await client.post("/service-accounts", data={"name": "ansible", "role": "manager"}, headers=h)
    await client.post("/service-accounts/1/keys", data={"name": "k", "scope": "write"}, headers=h)
    return csrf


class TestMigrations:
    def test_une_seule_tete_et_chaine_lineaire(self):
        scripts = ScriptDirectory.from_config(alembic_config("unused"))
        assert len(scripts.get_heads()) == 1
        revisions = [rev.revision for rev in scripts.walk_revisions()]
        assert revisions[-1] == V0_1_REVISION, "la révision initiale publiée ne doit jamais disparaître"

    async def test_base_v0_1_migree_sans_perte(self, test_env, tmp_path):
        """Une base créée par la v0.1.0, avec des données, démarre sur la version courante."""
        db = tmp_path / "test.db"
        command.upgrade(alembic_config(db), V0_1_REVISION)
        conn = sqlite3.connect(db)
        conn.execute("INSERT INTO reseau(id,name,default_locale,created_at,updated_at) VALUES(1,'Maison','fr','2026-07-06','2026-07-06')")
        conn.execute("INSERT INTO user(username,hashed_password,role,is_active,created_at) VALUES('ancien','x','manager',1,'2026-07-06')")
        conn.execute("INSERT INTO subnet(name,cidr,created_at,updated_at) VALUES('LAN','192.168.1.0/24','2026-07-06','2026-07-06')")
        conn.execute("INSERT INTO ip_address(subnet_id,address,address_int,hostname,status,created_at,updated_at) VALUES(1,'192.168.1.32',3232235808,'pve','utilisee','2026-07-06','2026-07-06')")
        conn.execute("INSERT INTO monitor_target(ip_id,protocol,port,enabled,interval_seconds,last_status,consecutive_failures) VALUES(1,'tcp',8006,1,60,'unknown',0)")
        conn.execute("INSERT INTO audit_log(user_id,username,ts,action,entity_type,entity_id) VALUES(1,'ancien','2026-07-06','create','subnet',1)")
        conn.commit()
        conn.close()

        from app.main import create_app

        application = create_app()
        async with application.router.lifespan_context(application):
            async with session_factory()() as session:
                ip = (await session.exec(select(IPAddress))).one()
                assert (ip.address, ip.hostname, ip.hardware) == ("192.168.1.32", "pve", None)
                # v0.3 : colonnes de pause ajoutées, IP existantes non en pause.
                assert (ip.paused_at, ip.pause_until, ip.pause_until_recovery) == (None, None, False)
                assert not ip.is_paused
                assert (await session.exec(select(Subnet))).one().cidr == "192.168.1.0/24"
                assert (await session.exec(select(User))).one().username == "ancien"
                exported = await backup.export_data(session)
        assert len(exported["data"]["audit_log"]) == 1 and len(exported["data"]["monitor_target"]) == 1
        # Un instantané de la base d'origine a été pris avant de migrer.
        snapshots = list((tmp_path / "backups").glob(f"{backup.PRE_MIGRATION_PREFIX}*-{V0_1_REVISION}.db"))
        assert len(snapshots) == 1
        old = sqlite3.connect(snapshots[0])
        assert old.execute("SELECT version_num FROM alembic_version").fetchone()[0] == V0_1_REVISION
        assert old.execute("SELECT hostname FROM ip_address").fetchone()[0] == "pve"
        old.close()

    async def test_base_plus_recente_que_le_code_refusee(self, test_env, tmp_path):
        db = tmp_path / "test.db"
        command.upgrade(alembic_config(db), "head")
        conn = sqlite3.connect(db)
        conn.execute("UPDATE alembic_version SET version_num='revision_du_futur'")
        conn.commit()
        conn.close()
        from app.main import create_app

        application = create_app()
        with pytest.raises(RuntimeError, match="plus récente"):
            async with application.router.lifespan_context(application):
                pass

    async def test_pas_d_instantane_sans_migration(self, client, tmp_path):
        assert not list((tmp_path / "backups").glob(f"{backup.PRE_MIGRATION_PREFIX}*"))


class TestSauvegardeJson:
    async def test_aller_retour_complet(self, client):
        csrf = await populate(client)
        response = await client.get("/backup.json")
        assert response.status_code == 200
        saved = response.json()
        assert saved["format"] == "guipam-backup" and saved["format_version"] == backup.FORMAT_VERSION
        assert saved["schema_revision"] and saved["app_version"]

        # On abîme l'instance, puis on restaure.
        h = {"X-CSRF-Token": csrf}
        assert (await client.delete("/subnets/1", headers=h)).status_code == 204
        assert (await client.delete("/service-accounts/1", headers=h)).status_code == 204
        response = await client.post(
            "/restore", files={"file": ("b.json", json.dumps(saved), "application/json")}, headers=h
        )
        assert response.status_code == 204 and response.headers["hx-redirect"] == "/login"
        assert (await client.get("/")).status_code == 302  # déconnecté

        await login(client, "admin", ADMIN_PASSWORD)
        restored = (await client.get("/backup.json")).json()
        for table, rows in saved["data"].items():
            if table == "audit_log":
                continue  # la sauvegarde et la restauration y ajoutent leur propre trace
            if table == "user":
                rows = [{**r, "last_login_at": None} for r in rows]
                restored["data"][table] = [{**r, "last_login_at": None} for r in restored["data"][table]]
            assert restored["data"][table] == rows, table
        assert "pve" in (await client.get("/subnets/1")).text
        actions = [(r["action"], r["entity_type"]) for r in restored["data"]["audit_log"]]
        assert ("import", "backup") in actions and ("create", "subnet") in actions

    async def test_export_ancien_ou_enrichi_tolere(self, client):
        """Colonnes manquantes → défaut du schéma ; colonnes et tables inconnues → ignorées."""
        csrf = await populate(client)
        saved = (await client.get("/backup.json")).json()
        for row in saved["data"]["ip_address"]:
            del row["hardware"], row["location"]
            row["colonne_du_futur"] = 1
        saved["data"]["table_du_futur"] = [{"id": 1}]
        response = await client.post(
            "/restore", files={"file": ("b.json", json.dumps(saved), "application/json")},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 204, response.text
        async with session_factory()() as session:
            ip = (await session.exec(select(IPAddress))).one()
        assert ip.hostname == "pve" and ip.hardware is None

    async def test_sauvegardes_refusees_sans_rien_modifier(self, client):
        csrf = await populate(client)
        saved = (await client.get("/backup.json")).json()
        futur = {**saved, "format_version": backup.FORMAT_VERSION + 1}
        sans_manager = copy.deepcopy(saved)
        for row in sans_manager["data"]["user"]:
            row["role"] = "user"
        cassee = copy.deepcopy(saved)
        cassee["data"]["ip_address"][0]["subnet_id"] = 999  # clé étrangère invalide
        for content in [json.dumps(futur), json.dumps(sans_manager), json.dumps(cassee), "pas du json", '{"a": 1}']:
            response = await client.post(
                "/restore", files={"file": ("b.json", content, "application/json")}, headers={"X-CSRF-Token": csrf}
            )
            assert response.status_code == 422, content[:60]
        async with session_factory()() as session:
            assert (await session.exec(select(IPAddress))).one().hostname == "pve"
            assert (await session.exec(select(User))).one().role.value == "manager"

    async def test_upgrader_de_format_applique(self, client, monkeypatch):
        """Un export d'un ancien format passe par la chaîne d'upgraders avant import."""
        await populate(client)
        saved = (await client.get("/backup.json")).json()

        def v1_to_v2(payload):
            payload["data"]["subnet"][0]["name"] = "renommé par l'upgrader"
            return payload

        monkeypatch.setattr(backup, "FORMAT_VERSION", 2)
        monkeypatch.setattr(backup, "UPGRADERS", {1: v1_to_v2})
        async with session_factory()() as session:
            await backup.import_data(session, saved)
            assert (await session.exec(select(Subnet))).one().name == "renommé par l'upgrader"

    async def test_reserve_aux_managers(self, client):
        csrf = await login(client, "admin", ADMIN_PASSWORD)
        await client.post(
            "/users", data={"username": "bob", "password": "bobpassword", "role": "user"}, headers={"X-CSRF-Token": csrf}
        )
        await client.post("/logout", headers={"X-CSRF-Token": csrf})
        csrf_bob = await login(client, "bob", "bobpassword")
        assert (await client.get("/backup.json")).status_code == 403
        response = await client.post(
            "/restore", files={"file": ("b.json", "{}", "application/json")}, headers={"X-CSRF-Token": csrf_bob}
        )
        assert response.status_code == 403
        assert "Sauvegarde complète" not in (await client.get("/import")).text


class TestInstantanes:
    async def test_quotidien_et_rotation(self, client, tmp_path):
        await populate(client)
        db = str(tmp_path / "test.db")
        path = backup.daily_snapshot(db, keep=7)
        copy_conn = sqlite3.connect(path)
        assert copy_conn.execute("SELECT hostname FROM ip_address").fetchone()[0] == "pve"
        copy_conn.close()
        for day in range(10):
            backup.snapshot(db, backup.DAILY_PREFIX, f"202601{day:02d}", keep=3)
        assert len(list((tmp_path / "backups").glob(f"{backup.DAILY_PREFIX}*.db"))) == 3
        assert backup.snapshot(db, backup.DAILY_PREFIX, "x", keep=0) is None
