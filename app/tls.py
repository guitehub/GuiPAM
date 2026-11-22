"""TLS natif : certificat fourni ou auto-signé persistant, empreintes, renouvellement.

Mode `auto` (défaut) : si GUIPAM_TLS_CERTFILE et GUIPAM_TLS_KEYFILE sont définis, ils sont servis tels
quels ; sinon GuiPAM crée (au premier démarrage) puis réutilise un certificat auto-signé dans
`<dossier de la base>/tls/` (`guipam.crt`, `guipam.key` en 0600). La clé ECDSA P-256 n'est jamais
régénérée : réémission (SAN modifiés) et renouvellement (30 jours avant l'échéance) la réutilisent, si
bien que l'épingle SPKI d'un client survit au renouvellement.

Ligne de commande : `python -m app.tls show [--json]` affiche les empreintes depuis l'hôte
(`docker exec guipam python -m app.tls show`), sans rien écrire.
"""

import base64
import hashlib
import ipaddress
import logging
import os
import re
import socket
import ssl
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.config import Settings, split_list

logger = logging.getLogger("guipam.tls")

SELF_SIGNED = "self-signed"
PROVIDED = "provided"
CERT_NAME = "guipam.crt"
KEY_NAME = "guipam.key"
# 825 jours : plafond accepté par les clients Apple, y compris pour un certificat installé à la main.
VALIDITY = timedelta(days=825)
RENEW_BEFORE = timedelta(days=30)
# Marge contre les horloges de clients en retard.
BACKDATE = timedelta(hours=1)

_DNS_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class TlsError(RuntimeError):
    """Configuration TLS inutilisable : le message est destiné à l'administrateur."""


@dataclass(frozen=True)
class TlsInfo:
    """Certificat servi par l'instance, tel qu'exposé (journaux, interface, API, CLI)."""

    mode: str  # "auto" | "off"
    source: str | None = None  # SELF_SIGNED | PROVIDED
    certfile: Path | None = None
    keyfile: Path | None = None
    not_before: datetime | None = None  # UTC naïf, comme le reste de l'application
    not_after: datetime | None = None
    sha256: str | None = None  # empreinte du certificat, « AB:CD:… » comme openssl et les navigateurs
    spki_sha256: str | None = None  # base64 du SHA-256 de la clé publique (SubjectPublicKeyInfo)
    sans: list[str] = field(default_factory=list)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def expires_within(self, delta: timedelta, now: datetime | None = None) -> bool:
        return self.not_after is not None and self.not_after - (now or _utcnow()) < delta


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------- Empreintes


def cert_sha256(cert: x509.Certificate) -> str:
    """Empreinte SHA-256 du certificat (DER), format `openssl x509 -fingerprint -sha256`."""
    return ":".join(f"{b:02X}" for b in cert.fingerprint(hashes.SHA256()))


def spki_sha256(cert: x509.Certificate) -> str:
    """Épingle SPKI : base64 du SHA-256 de la clé publique DER (format HPKP / curl --pinnedpubkey)."""
    der = cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


def cert_sans(cert: x509.Certificate) -> list[str]:
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return [str(v) for v in ext.get_values_for_type(x509.DNSName)] + [
        str(v) for v in ext.get_values_for_type(x509.IPAddress)
    ]


def describe(cert: x509.Certificate, source: str, certfile: Path, keyfile: Path) -> TlsInfo:
    return TlsInfo(
        mode="auto",
        source=source,
        certfile=certfile,
        keyfile=keyfile,
        not_before=cert.not_valid_before_utc.replace(tzinfo=None),
        not_after=cert.not_valid_after_utc.replace(tzinfo=None),
        sha256=cert_sha256(cert),
        spki_sha256=spki_sha256(cert),
        sans=cert_sans(cert),
    )


# --------------------------------------------------------------------------- SAN


def normalize_san(raw: str) -> str:
    """Nom DNS (minuscules, joker `*.` en tête admis) ou IP (forme canonique). Lève TlsError sinon."""
    value = raw.strip().strip("[]")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    name = value.lower().rstrip(".")
    labels = name.split(".")
    if labels and labels[0] == "*":
        labels = labels[1:]
    if not name or len(name) > 253 or not labels or not all(_DNS_LABEL.match(label) for label in labels):
        raise TlsError(f"GUIPAM_TLS_SANS : « {raw.strip()} » n'est ni un nom DNS ni une adresse IP.")
    return name


CN_PREFIX = "GuiPAM "


def _hostname_san(hostname: str | None) -> list[str]:
    try:
        return [normalize_san(hostname)] if hostname else []
    except TlsError:
        return []  # nom d'hôte exotique : on s'en passe


def requested_sans(settings: Settings, hostname: str | None = None) -> list[str]:
    """SAN du certificat auto-signé : boucle locale, nom d'hôte, puis GUIPAM_TLS_SANS (sans doublons).

    hostname : nom d'hôte à inclure (par défaut celui du moment).
    """
    candidates = ["localhost", "127.0.0.1", "::1"]
    candidates += _hostname_san(socket.gethostname() if hostname is None else hostname)
    candidates += [normalize_san(item) for item in split_list(settings.tls_sans)]
    return list(dict.fromkeys(candidates))


def _issued_hostname(cert: x509.Certificate) -> str:
    """Nom d'hôte au moment de l'émission, consigné dans le CN (« GuiPAM <hôte> »)."""
    names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    value = str(names[0].value) if names else ""
    return value.removeprefix(CN_PREFIX) if value.startswith(CN_PREFIX) else ""


def _sans_up_to_date(sans: list[str], settings: Settings, cert: x509.Certificate) -> bool:
    """SAN conformes à la configuration, au nom d'hôte de l'émission près (CN, éventuellement tronqué)."""
    expected = set(requested_sans(settings, hostname=""))
    extra = set(sans) - expected
    if not expected <= set(sans):
        return False
    issued = _issued_hostname(cert)
    return not extra or (len(extra) == 1 and bool(issued) and next(iter(extra)).startswith(issued.lower()))


def _san_extension(sans: list[str]) -> x509.SubjectAlternativeName:
    names: list[x509.GeneralName] = []
    for san in sans:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(san)))
        except ValueError:
            names.append(x509.DNSName(san))
    return x509.SubjectAlternativeName(names)


# --------------------------------------------------------------------------- Fichiers


def tls_dir(settings: Settings) -> Path:
    return Path(settings.db_path).resolve().parent / "tls"


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Écrit à côté puis renomme : un fichier n'est jamais lu à moitié écrit."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _load_key(path: Path):
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise TlsError(f"Clé privée {path} illisible (PEM sans mot de passe attendu) : {exc}") from None
    return key


def _load_cert(path: Path) -> x509.Certificate:
    """Premier certificat d'un fichier PEM (le reste, s'il existe, est la chaîne intermédiaire)."""
    try:
        certs = x509.load_pem_x509_certificates(path.read_bytes())
    except ValueError as exc:
        raise TlsError(f"Certificat {path} illisible (PEM attendu) : {exc}") from None
    return certs[0]


def _same_public_key(cert: x509.Certificate, key) -> bool:
    fmt = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return cert.public_key().public_bytes(*fmt) == key.public_key().public_bytes(*fmt)


def _issue(key: ec.EllipticCurvePrivateKey, sans: list[str], now: datetime) -> x509.Certificate:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{CN_PREFIX}{socket.gethostname()}"[:64])])
    public_key = key.public_key()
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - BACKDATE)
        .not_valid_after(now + VALIDITY)
        .add_extension(_san_extension(sans), critical=False)
        # Certificat feuille (CA:FALSE) : Firefox refuse un certificat d'AC servi comme feuille.
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .sign(key, hashes.SHA256())
    )


# --------------------------------------------------------------------------- Résolution


def ensure_self_signed(settings: Settings, now: datetime | None = None) -> tuple[TlsInfo, str | None]:
    """Crée, réémet ou renouvelle si besoin le certificat auto-signé ; renvoie (infos, action).

    action : "created", "reissued" (GUIPAM_TLS_SANS changée ou certificat étranger à la clé), "renewed"
    (échéance à moins de 30 jours) ou None (rien à faire). La clé existante est toujours conservée.
    """
    now = now or _utcnow()
    directory = tls_dir(settings)
    directory.mkdir(parents=True, exist_ok=True)
    certfile, keyfile = directory / CERT_NAME, directory / KEY_NAME
    sans = requested_sans(settings)

    if keyfile.exists():
        key = _load_key(keyfile)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise TlsError(f"{keyfile} n'est pas une clé ECDSA : supprimez {directory} pour en générer une.")
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        _write_atomic(keyfile, pem, 0o600)

    action = "created"
    if certfile.exists():
        current = _load_cert(certfile)
        info = describe(current, SELF_SIGNED, certfile, keyfile)
        # Le nom d'hôte attendu est celui de l'émission : un conteneur recréé change de nom d'hôte,
        # et ce seul changement ne doit pas modifier l'empreinte. Seul GUIPAM_TLS_SANS déclenche la réémission.
        if not _same_public_key(current, key) or not _sans_up_to_date(info.sans, settings, current):
            action = "reissued"
        elif info.expires_within(RENEW_BEFORE, now):
            action = "renewed"
        else:
            return info, None

    cert = _issue(key, sans, now)
    _write_atomic(certfile, cert.public_bytes(serialization.Encoding.PEM), 0o644)
    return describe(cert, SELF_SIGNED, certfile, keyfile), action


def load_provided(settings: Settings) -> TlsInfo:
    """Certificat fourni (GUIPAM_TLS_CERTFILE/KEYFILE) : vérifie sa présence et l'accord avec la clé."""
    if not settings.tls_certfile or not settings.tls_keyfile:
        missing = "GUIPAM_TLS_KEYFILE" if settings.tls_certfile else "GUIPAM_TLS_CERTFILE"
        raise TlsError(
            f"{missing} n'est pas définie : un certificat fourni exige GUIPAM_TLS_CERTFILE et "
            "GUIPAM_TLS_KEYFILE (ou aucune des deux pour le certificat auto-signé)."
        )
    certfile, keyfile = Path(settings.tls_certfile), Path(settings.tls_keyfile)
    for var, path in (("GUIPAM_TLS_CERTFILE", certfile), ("GUIPAM_TLS_KEYFILE", keyfile)):
        if not path.is_file():
            raise TlsError(f"{var} : fichier {path} introuvable.")
        if not os.access(path, os.R_OK):
            raise TlsError(f"{var} : fichier {path} illisible par l'utilisateur de GuiPAM (uid {os.getuid()}).")
    cert, key = _load_cert(certfile), _load_key(keyfile)
    if not _same_public_key(cert, key):
        raise TlsError(f"La clé {keyfile} ne correspond pas au certificat {certfile}.")
    return describe(cert, PROVIDED, certfile, keyfile)


def resolve(settings: Settings, now: datetime | None = None) -> tuple[TlsInfo, str | None]:
    """Certificat à servir selon la configuration (créé ou renouvelé si auto-signé)."""
    if not settings.tls_enabled:
        return TlsInfo(mode="off"), None
    if settings.tls_certfile or settings.tls_keyfile:
        return load_provided(settings), None
    return ensure_self_signed(settings, now)


def inspect(settings: Settings) -> TlsInfo:
    """Comme resolve(), sans jamais écrire (CLI). Lève TlsError si le certificat n'existe pas encore."""
    if not settings.tls_enabled:
        return TlsInfo(mode="off")
    if settings.tls_certfile or settings.tls_keyfile:
        return load_provided(settings)
    directory = tls_dir(settings)
    certfile, keyfile = directory / CERT_NAME, directory / KEY_NAME
    if not certfile.exists():
        raise TlsError(f"Pas encore de certificat dans {directory} : il est créé au premier démarrage de GuiPAM.")
    return describe(_load_cert(certfile), SELF_SIGNED, certfile, keyfile)


# --------------------------------------------------------------------------- État du processus

_current: TlsInfo | None = None
_contexts: list[ssl.SSLContext] = []


def current() -> TlsInfo | None:
    """Certificat servi par ce processus (None tant que prepare() n'a pas tourné)."""
    return _current


def reset() -> None:
    """Oublie l'état (tests)."""
    global _current
    _current = None
    _contexts.clear()


def register_context(context: ssl.SSLContext) -> None:
    """Contexte TLS d'un écouteur, rechargé à chaud par refresh() quand le certificat change."""
    _contexts.append(context)


_ACTIONS = {
    None: "Certificat TLS {source}",
    "created": "Certificat TLS {source} créé",
    "reissued": "Certificat TLS {source} réémis (même clé)",
    "renewed": "Certificat TLS {source} renouvelé (même clé)",
}


def log_info(info: TlsInfo, action: str | None = None) -> None:
    if not info.enabled:
        return
    source = "auto-signé" if info.source == SELF_SIGNED else "fourni"
    logger.info(
        "%s : %s, échéance %s UTC.",
        _ACTIONS[action].format(source=source),
        info.certfile,
        f"{info.not_after:%Y-%m-%d %H:%M}",
    )
    logger.info("TLS SHA-256 : %s", info.sha256)
    logger.info("TLS SPKI SHA-256 (épingle) : %s", info.spki_sha256)
    logger.info("TLS SAN : %s", ", ".join(info.sans) or "aucun")
    if info.expires_within(timedelta(0)):
        logger.error("Le certificat TLS %s a expiré le %s UTC.", info.certfile, f"{info.not_after:%Y-%m-%d}")
    elif info.source == PROVIDED and info.expires_within(RENEW_BEFORE):
        logger.warning("Le certificat TLS fourni %s expire le %s UTC.", info.certfile, f"{info.not_after:%Y-%m-%d}")


def prepare(settings: Settings, now: datetime | None = None) -> TlsInfo:
    """Résout le certificat au démarrage, le journalise et le retient pour l'interface et l'API."""
    global _current
    info, action = resolve(settings, now)
    if info.source == SELF_SIGNED and not split_list(settings.tls_sans):
        logger.warning(
            "GUIPAM_TLS_SANS est vide : le certificat auto-signé ne couvre que localhost et le nom d'hôte "
            "« %s » (peu significatif dans un conteneur). Ajoutez les noms et IP par lesquels on joint GuiPAM.",
            socket.gethostname(),
        )
    log_info(info, action)
    _current = info
    return info


def refresh(settings: Settings, now: datetime | None = None) -> bool:
    """Vérification périodique : renouvelle si besoin, recharge les écouteurs si le certificat a changé.

    Couvre aussi un certificat fourni remplacé sur disque (renouvellement ACME externe…). Renvoie True
    si le certificat servi a changé.
    """
    global _current
    try:
        info, action = resolve(settings, now)
    except TlsError as exc:
        logger.error("Vérification du certificat TLS impossible, l'ancien reste servi : %s", exc)
        return False
    if _current is not None and info.sha256 == _current.sha256:
        return False
    log_info(info, action)
    for context in _contexts:
        context.load_cert_chain(str(info.certfile), str(info.keyfile))
    if _contexts:
        logger.info("Nouveau certificat TLS chargé à chaud (nouvelles connexions).")
    _current = info
    return True


# --------------------------------------------------------------------------- Ligne de commande


def _cli(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="python -m app.tls", description="Certificat TLS de GuiPAM.")
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show", help="affiche l'origine, l'échéance et les empreintes du certificat servi")
    show.add_argument("--json", action="store_true", help="sortie JSON (mêmes champs que GET /api/v1/instance)")
    args = parser.parse_args(argv)

    try:
        info = inspect(Settings())
    except (TlsError, ValueError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(as_dict(info), indent=2))
    elif not info.enabled:
        print("TLS désactivé (GUIPAM_TLS=off).")
    else:
        print(f"Origine      : {'auto-signé' if info.source == SELF_SIGNED else 'fourni'} ({info.certfile})")
        print(f"Validité     : {info.not_before:%Y-%m-%d %H:%M} → {info.not_after:%Y-%m-%d %H:%M} UTC")
        print(f"SAN          : {', '.join(info.sans) or 'aucun'}")
        print(f"SHA-256      : {info.sha256}")
        print(f"SPKI SHA-256 : {info.spki_sha256}")
    return 0


def as_dict(info: TlsInfo) -> dict:
    """Champs publics (JSON), dates en ISO 8601 UTC suffixe Z comme l'API."""
    return {
        "mode": info.mode,
        "source": info.source,
        "not_after": info.not_after.isoformat() + "Z" if info.not_after else None,
        "sha256": info.sha256,
        "spki_sha256": info.spki_sha256,
        "sans": info.sans,
    }


if __name__ == "__main__":
    raise SystemExit(_cli())
