"""Configuration de l'application via variables d'environnement GUIPAM_*."""

from functools import lru_cache

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
    port: int = 8080

    secure_cookies: bool = True
    session_max_age: int = 1209600  # 14 jours

    monitor_tick_seconds: int = 15
    default_check_interval: int = 60
    monitor_concurrency: int = 50
    tcp_timeout_seconds: float = 3.0
    enable_ping: bool = True

    health_warn_seconds: int = 120
    health_red_seconds: int = 600
    health_dark_red_seconds: int = 3600
    health_poll_seconds: int = 30

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
