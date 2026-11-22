"""Configuration de l'application via variables d'environnement GUIPAM_*."""

import ipaddress
from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valeurs refusées comme clé de session en production.
TRIVIAL_SECRETS = {"", "changeme", "change-me", "secret", "secret-key", "guipam", "dev", "test"}
MIN_SECRET_LENGTH = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GUIPAM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = False

    db_path: str = "/data/guipam.db"
    secret_key: str = ""

    admin_username: str = "admin"
    admin_password: str | None = None

    default_locale: str = "fr"

    host: str = "0.0.0.0"
    # Écouteurs (voir app/server.py) : HTTPS principal, HTTP selon http_mode.
    https_port: int = 8443
    http_port: int = 8080
    # redirect : 308 vers l'HTTPS (seul /healthz répond) ; proxy : application complète en HTTP pour
    # un reverse proxy qui termine le TLS (non destiné à être publié) ; off : pas d'écouteur HTTP.
    http_mode: Literal["redirect", "proxy", "off"] = "redirect"
    # Port HTTPS vu des navigateurs, si le port publié diffère de https_port (cible des redirections).
    public_https_port: int | None = None
    # IP/CIDR des reverse proxies dont on accepte X-Forwarded-For/-Proto (écouteur proxy), séparés par des virgules.
    trusted_proxies: str = ""
    # Alias déprécié de http_port (GuiPAM ≤ 0.5).
    port: int | None = None

    # TLS natif (voir app/tls.py) : auto = certificat fourni s'il est défini, sinon auto-signé persistant.
    tls: Literal["auto", "off"] = "auto"
    tls_certfile: str | None = None
    tls_keyfile: str | None = None
    # Noms DNS et IP ajoutés aux SAN du certificat auto-signé, séparés par des virgules.
    tls_sans: str = ""

    secure_cookies: bool = True
    # Session ordinaire : cookie effacé à la fermeture du navigateur, refusé après cette
    # durée d'inactivité. « Rester connecté » : cookie persistant de remember_max_age.
    session_max_age: int = 43200  # 12 heures
    remember_max_age: int = 2592000  # 30 jours

    monitor_tick_seconds: int = 15
    default_check_interval: int = 60  # valeur initiale, redéfinissable dans les Paramètres du réseau
    monitor_concurrency: int = 50
    tcp_timeout_seconds: float = 3.0
    enable_ping: bool = True

    # Instantanés SQLite conservés dans <dossier de la base>/backups (0 = désactivé).
    backup_keep_pre_migration: int = 5
    backup_keep_daily: int = 7

    # Valeurs initiales du suivi : elles s'appliquent tant que les « Paramètres du réseau »
    # (table reseau) ne les redéfinissent pas. Voir monitor.MonitoringSettings.
    health_warn_intervals: int = 2  # vert → ambre : dernier succès plus vieux que N intervalles
    health_red_failures: int = 10  # ambre → rouge : N échecs consécutifs
    health_dark_red_seconds: int = 604800  # rouge → rouge foncé : durée sans succès (1 semaine)
    health_poll_seconds: int = 30

    @field_validator("tls_certfile", "tls_keyfile", "public_https_port", "port", mode="before")
    @classmethod
    def _empty_is_none(cls, value):
        """Une variable définie mais vide (`GUIPAM_TLS_CERTFILE=`) vaut « non définie »."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("tls", "http_mode", mode="before")
    @classmethod
    def _lowercase(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("trusted_proxies")
    @classmethod
    def _check_proxies(cls, value: str) -> str:
        # uvicorn prend silencieusement une valeur illisible pour un nom littéral : on refuse net.
        for item in split_list(value):
            try:
                ipaddress.ip_network(item, strict=False)
            except ValueError:
                raise ValueError(
                    f"GUIPAM_TRUSTED_PROXIES : « {item} » n'est ni une adresse IP ni un réseau CIDR."
                ) from None
        return value

    @model_validator(mode="after")
    def _port_alias(self):
        if self.port is not None and "http_port" not in self.model_fields_set:
            self.http_port = self.port
        return self

    @property
    def trusted_proxy_list(self) -> list[str]:
        return split_list(self.trusted_proxies)

    @property
    def tls_enabled(self) -> bool:
        return self.tls != "off"

    @property
    def redirect_https_port(self) -> int:
        """Port HTTPS annoncé dans les redirections de l'écouteur HTTP."""
        return self.public_https_port or self.https_port

    def startup_warnings(self) -> list[str]:
        """Configurations déconseillées, journalisées au démarrage du serveur."""
        warnings = []
        if self.port is not None:
            warnings.append(
                "GUIPAM_PORT est dépréciée : utilisez GUIPAM_HTTP_PORT"
                + (" (GUIPAM_PORT est ignorée, GUIPAM_HTTP_PORT étant définie)." if "http_port" in self.model_fields_set else ".")
            )
        if not self.tls_enabled:
            warnings.append(
                "GUIPAM_TLS=off : GuiPAM ne sert que du HTTP en clair. Réservé au développement et aux tests "
                "(ou à un reverse proxy qui termine le TLS)."
            )
        elif not self.secure_cookies:
            warnings.append(
                "GUIPAM_SECURE_COOKIES=false alors que le TLS est actif : le cookie de session part sans "
                "l'attribut Secure. Retirez cette variable (défaut : true)."
            )
        if self.tls_enabled and self.http_mode == "proxy" and not self.trusted_proxy_list:
            warnings.append(
                "GUIPAM_HTTP_MODE=proxy sans GUIPAM_TRUSTED_PROXIES : X-Forwarded-For est ignoré, tous les "
                "clients partagent l'IP du proxy (journal, anti-brute-force). Déclarez l'IP du reverse proxy."
            )
        return warnings

    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    def validate_secret_key(self) -> None:
        """Refuse de démarrer en production avec une clé absente ou triviale."""
        if self.debug:
            return
        key = self.secret_key.strip()
        if key.lower() in TRIVIAL_SECRETS or len(key) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                "GUIPAM_SECRET_KEY est absente ou triviale. Définissez une clé "
                "aléatoire d'au moins 16 caractères (ex. `openssl rand -hex 32`) "
                "avant de démarrer GuiPAM."
            )


def split_list(raw: str) -> list[str]:
    """Liste « a, b,c » → ["a", "b", "c"] (éléments vides ignorés)."""
    return [item.strip() for item in raw.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
