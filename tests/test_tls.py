"""Certificat TLS : auto-signé persistant, certificat fourni, SAN, renouvellement, empreintes, CLI."""

import json
import logging
import shutil
import ssl
import stat
import subprocess
from datetime import timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import tls
from app.config import Settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.delenv("GUIPAM_TLS_SANS", raising=False)
    return Settings(_env_file=None, db_path=str(tmp_path / "data" / "guipam.db"), tls_sans="guipam.example.net, 10.0.0.5")


def make_provided(directory, sans=("provided.example.net",)):
    """Certificat « fourni » (RSA, comme une CA interne en émettrait) ; renvoie (certfile, keyfile)."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = tls._utcnow()
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, sans[0])])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(s) for s in sans]), critical=False)
        .sign(key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    certfile, keyfile = directory / "fullchain.pem", directory / "privkey.pem"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return certfile, keyfile


class TestAutoSigne:
    def test_premier_demarrage_cree_cert_et_cle_0600(self, settings, caplog):
        caplog.set_level(logging.INFO, logger="guipam")
        info = tls.prepare(settings)
        directory = tls.tls_dir(settings)
        assert info.certfile == directory / "guipam.crt" and info.keyfile == directory / "guipam.key"
        assert stat.S_IMODE(info.keyfile.stat().st_mode) == 0o600
        assert info.source == tls.SELF_SIGNED and info.mode == "auto"
        key = serialization.load_pem_private_key(info.keyfile.read_bytes(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey) and key.curve.name == "secp256r1"
        # Empreintes et échéance journalisées.
        assert info.sha256 in caplog.text and info.spki_sha256 in caplog.text
        assert "créé" in caplog.text and f"{info.not_after:%Y-%m-%d}" in caplog.text
        assert tls.current() == info

    def test_validite_825_jours_feuille_serveur(self, settings):
        info = tls.prepare(settings)
        cert = x509.load_pem_x509_certificate(info.certfile.read_bytes())
        assert info.not_after - info.not_before == tls.VALIDITY + tls.BACKDATE
        assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
        assert cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value == x509.ExtendedKeyUsage(
            [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]
        )

    def test_redemarrage_meme_certificat(self, settings, caplog):
        first = tls.prepare(settings)
        # Nouveau processus (recréation du conteneur) : même volume, rien n'est réécrit.
        tls.reset()
        mtime = first.certfile.stat().st_mtime_ns
        caplog.set_level(logging.INFO, logger="guipam")
        second = tls.prepare(settings)
        assert second.sha256 == first.sha256 and second.spki_sha256 == first.spki_sha256
        assert first.certfile.stat().st_mtime_ns == mtime
        assert "créé" not in caplog.text and "réémis" not in caplog.text

    def test_avertissement_si_sans_vide(self, settings, caplog):
        caplog.set_level(logging.INFO, logger="guipam")
        tls.prepare(settings.model_copy(update={"tls_sans": ""}))
        assert "GUIPAM_TLS_SANS est vide" in caplog.text
        caplog.clear()
        tls.prepare(settings)
        assert "GUIPAM_TLS_SANS est vide" not in caplog.text


class TestSAN:
    def test_san_conformes(self, settings):
        info = tls.prepare(settings)
        assert {"localhost", "127.0.0.1", "::1", "guipam.example.net", "10.0.0.5"} <= set(info.sans)
        cert = x509.load_pem_x509_certificate(info.certfile.read_bytes())
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert "guipam.example.net" in ext.get_values_for_type(x509.DNSName)
        assert "10.0.0.5" in [str(ip) for ip in ext.get_values_for_type(x509.IPAddress)]

    def test_reemission_meme_cle_si_liste_change(self, settings):
        first = tls.prepare(settings)
        info, action = tls.resolve(settings.model_copy(update={"tls_sans": "guipam.example.net,[fd00::1],*.lab.example"}))
        assert action == "reissued"
        assert "fd00::1" in info.sans and "*.lab.example" in info.sans and "10.0.0.5" not in info.sans
        assert info.spki_sha256 == first.spki_sha256 and info.sha256 != first.sha256
        # Même liste, autre ordre/casse : pas de réémission.
        _info, action = tls.resolve(settings.model_copy(update={"tls_sans": "*.LAB.example, fd00:0::1,guipam.example.net"}))
        assert action is None

    @pytest.mark.parametrize("bad", ["exa mple.com", "-bad.example", "a..b", "http://x"])
    def test_san_invalide_refuse(self, settings, bad):
        with pytest.raises(tls.TlsError, match="GUIPAM_TLS_SANS"):
            tls.prepare(settings.model_copy(update={"tls_sans": bad}))


class TestRenouvellement:
    def test_renouvelle_a_moins_de_30_jours_meme_spki(self, settings):
        first = tls.prepare(settings)
        _info, action = tls.resolve(settings, now=first.not_after - timedelta(days=31))
        assert action is None
        renewed, action = tls.resolve(settings, now=first.not_after - timedelta(days=29))
        assert action == "renewed"
        assert renewed.spki_sha256 == first.spki_sha256
        assert renewed.sha256 != first.sha256 and renewed.not_after > first.not_after

    def test_refresh_recharge_les_contextes(self, settings, caplog):
        first = tls.prepare(settings)
        reloaded = []

        class FakeContext:
            def load_cert_chain(self, certfile, keyfile):
                reloaded.append((certfile, keyfile))

        real = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        real.load_cert_chain(str(first.certfile), str(first.keyfile))
        tls.register_context(FakeContext())
        tls.register_context(real)  # un vrai SSLContext accepte le rechargement sur place
        assert tls.refresh(settings) is False and reloaded == []
        caplog.set_level(logging.INFO, logger="guipam")
        assert tls.refresh(settings, now=first.not_after - timedelta(days=10)) is True
        assert reloaded == [(str(first.certfile), str(first.keyfile))]
        assert tls.current().spki_sha256 == first.spki_sha256 and tls.current().sha256 != first.sha256
        assert "renouvelé" in caplog.text and "chargé à chaud" in caplog.text

    def test_refresh_garde_l_ancien_si_erreur(self, settings, caplog):
        first = tls.prepare(settings)
        first.keyfile.write_text("garbage")
        assert tls.refresh(settings, now=first.not_after - timedelta(days=10)) is False
        assert tls.current() == first
        assert "l'ancien reste servi" in caplog.text


class TestFourni:
    def test_prioritaire_sur_auto_signe(self, settings, tmp_path):
        certfile, keyfile = make_provided(tmp_path / "certs")
        info = tls.prepare(settings.model_copy(update={"tls_certfile": str(certfile), "tls_keyfile": str(keyfile)}))
        assert info.source == tls.PROVIDED and info.certfile == certfile
        assert info.sans == ["provided.example.net"]
        assert not tls.tls_dir(settings).exists()  # aucun auto-signé créé

    @pytest.mark.parametrize("missing", ["tls_certfile", "tls_keyfile"])
    def test_erreur_si_l_un_manque(self, settings, tmp_path, missing):
        certfile, keyfile = make_provided(tmp_path / "certs")
        values = {"tls_certfile": str(certfile), "tls_keyfile": str(keyfile), missing: None}
        expected = "GUIPAM_TLS_CERTFILE" if missing == "tls_certfile" else "GUIPAM_TLS_KEYFILE"
        with pytest.raises(tls.TlsError, match=f"{expected} n'est pas définie"):
            tls.prepare(settings.model_copy(update=values))

    def test_erreur_si_fichier_absent(self, settings, tmp_path):
        certfile, _keyfile = make_provided(tmp_path / "certs")
        values = {"tls_certfile": str(certfile), "tls_keyfile": str(tmp_path / "nope.key")}
        with pytest.raises(tls.TlsError, match="GUIPAM_TLS_KEYFILE : fichier .* introuvable"):
            tls.prepare(settings.model_copy(update=values))

    def test_erreur_si_cle_et_certificat_ne_correspondent_pas(self, settings, tmp_path):
        certfile, _ = make_provided(tmp_path / "a")
        _, other_key = make_provided(tmp_path / "b")
        values = {"tls_certfile": str(certfile), "tls_keyfile": str(other_key)}
        with pytest.raises(tls.TlsError, match="ne correspond pas"):
            tls.prepare(settings.model_copy(update=values))

    def test_variable_vide_vaut_non_definie(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GUIPAM_TLS_CERTFILE", "")
        monkeypatch.setenv("GUIPAM_TLS_KEYFILE", "")
        settings = Settings(_env_file=None, db_path=str(tmp_path / "guipam.db"))
        assert tls.prepare(settings).source == tls.SELF_SIGNED


class TestTlsOff:
    def test_off_ne_cree_rien(self, settings):
        info = tls.prepare(settings.model_copy(update={"tls": "off"}))
        assert info.mode == "off" and not info.enabled and info.sha256 is None
        assert not tls.tls_dir(settings).exists()


class TestCli:
    def test_show_sans_certificat(self, settings, monkeypatch, capsys):
        monkeypatch.setenv("GUIPAM_DB_PATH", settings.db_path)
        assert tls._cli(["show"]) == 1
        assert "premier démarrage" in capsys.readouterr().err

    def test_show_texte_et_json(self, settings, monkeypatch, capsys):
        monkeypatch.setenv("GUIPAM_DB_PATH", settings.db_path)
        monkeypatch.setenv("GUIPAM_TLS_SANS", settings.tls_sans)
        info = tls.prepare(settings)
        assert tls._cli(["show"]) == 0
        out = capsys.readouterr().out
        assert info.sha256 in out and info.spki_sha256 in out and "auto-signé" in out
        assert tls._cli(["show", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data == tls.as_dict(info)
        assert data["not_after"].endswith("Z")

    def test_show_n_ecrit_rien(self, settings, monkeypatch, capsys):
        """Même si le renouvellement est dû ou les SAN changés, show se contente de lire."""
        monkeypatch.setenv("GUIPAM_DB_PATH", settings.db_path)
        monkeypatch.setenv("GUIPAM_TLS_SANS", "autre.example.net")
        info = tls.prepare(settings)
        assert tls._cli(["show", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["sha256"] == info.sha256

    @pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl absent")
    def test_empreintes_identiques_a_openssl(self, settings):
        info = tls.prepare(settings)
        out = subprocess.run(
            ["openssl", "x509", "-in", str(info.certfile), "-noout", "-fingerprint", "-sha256"],
            capture_output=True, text=True, check=True,
        ).stdout
        assert out.strip().split("=", 1)[1] == info.sha256
        pubkey = subprocess.run(
            ["openssl", "x509", "-in", str(info.certfile), "-pubkey", "-noout"], capture_output=True, check=True
        ).stdout
        der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "der"], input=pubkey, capture_output=True, check=True).stdout
        digest = subprocess.run(["openssl", "dgst", "-sha256", "-binary"], input=der, capture_output=True, check=True).stdout
        import base64

        assert base64.b64encode(digest).decode() == info.spki_sha256
