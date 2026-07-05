"""Import CSV tolérant (alias, doublons) et round-trip import/export."""

from app.models import IPStatus, Subnet
from app.services import csv_io

EXCEL_CSV = """Adresse IP;Nom;Adresse MAC;Statut;Commentaire;VLAN
192.168.10.20;imprimante;00-11-22-33-44-55;Utilisée;HP du bureau;192.168.10.0/24
192.168.10.20;doublon;;utilisée;doit être ignoré;
172.16.0.10;switch;AABB.CCDD.EEFF;réservée;;
pas-une-ip;oops;;;;
""".encode()


class TestMapColumns:
    def test_alias_excel_courants(self):
        header = ["Adresse IP", "Nom", "Adresse MAC", "Statut", "Commentaire", "VLAN"]
        mapping = csv_io.map_columns(header)
        assert set(mapping.values()) == {
            "address", "hostname", "mac", "status", "description", "subnet_cidr",
        }

    def test_colonnes_inconnues_ignorees(self):
        mapping = csv_io.map_columns(["ip", "n° de salle", "hostname"])
        assert set(mapping.values()) == {"address", "hostname"}


class TestParseStatus:
    def test_alias(self):
        assert csv_io.parse_status("Utilisée") == IPStatus.utilisee
        assert csv_io.parse_status("free") == IPStatus.libre
        assert csv_io.parse_status("Réservée") == IPStatus.reservee
        assert csv_io.parse_status("") == IPStatus.utilisee
        assert csv_io.parse_status("n'importe quoi") == IPStatus.utilisee


class TestImport:
    async def test_import_tolerant(self, db_session):
        report = await csv_io.import_csv(db_session, EXCEL_CSV)
        assert report.created == 2
        assert report.skipped == 1  # doublon dans le fichier
        assert len(report.errors) == 1  # pas-une-ip
        assert report.subnets_created == 2  # 192.168.10.0/24 (hint) + 172.16.0.0/24 (auto /24)

    async def test_doublons_en_base_ignores(self, db_session):
        await csv_io.import_csv(db_session, EXCEL_CSV)
        report = await csv_io.import_csv(db_session, EXCEL_CSV)
        assert report.created == 0
        assert report.skipped == 3  # 2 déjà en base + 1 doublon interne au fichier

    async def test_fichier_vide(self, db_session):
        report = await csv_io.import_csv(db_session, b"")
        assert report.created == 0
        assert report.errors

    async def test_sans_colonne_ip(self, db_session):
        report = await csv_io.import_csv(db_session, b"nom;commentaire\na;b\n")
        assert report.errors


class TestRoundTrip:
    async def test_import_export_import(self, db_session):
        await csv_io.import_csv(db_session, EXCEL_CSV)
        exported = await csv_io.export_csv(db_session)

        lines = exported.strip().splitlines()
        assert lines[0] == ",".join(csv_io.EXPORT_COLUMNS)
        assert len(lines) == 3  # 2 IP + en-tête
        assert "192.168.10.20" in exported
        assert "00:11:22:33:44:55" in exported  # MAC normalisée

        report = await csv_io.import_csv(db_session, exported.encode())
        assert report.created == 0
        assert report.skipped == 2
        assert not report.errors
