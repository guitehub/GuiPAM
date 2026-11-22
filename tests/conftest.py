"""Fixtures pytest : app complète (lifespan réel) + client HTTP + session DB isolée."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.config as config_module

ADMIN_PASSWORD = "testadminpassword"


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    """Environnement GUIPAM_* isolé ; vide le cache de settings."""
    monkeypatch.setenv("GUIPAM_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("GUIPAM_SECRET_KEY", "test-secret-key-0123456789abcdef")
    monkeypatch.setenv("GUIPAM_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("GUIPAM_SECURE_COOKIES", "false")
    monkeypatch.setenv("GUIPAM_MONITOR_TICK_SECONDS", "3600")
    config_module.get_settings.cache_clear()
    # L'anti-brute-force est en mémoire et global : sans remise à zéro, un test qui
    # verrouille « admin » ferait échouer les connexions des tests suivants.
    from app.services.auth import login_rate_limiter

    login_rate_limiter._states.clear()
    # Certificat retenu par le processus : chaque test a son propre dossier de données.
    from app import tls

    tls.reset()
    yield
    config_module.get_settings.cache_clear()
    tls.reset()


@pytest.fixture
async def client(test_env):
    """Client httpx sur l'app réelle, lifespan exécuté (migrations, bootstrap, scheduler)."""
    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
async def db_session():
    """Session SQLModel sur une base en mémoire (tests de services, sans app)."""
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
    await engine.dispose()


async def get_csrf(http: AsyncClient) -> str:
    response = await http.get("/login")
    marker = 'name="csrf_token" value="'
    body = response.text
    start = body.index(marker) + len(marker)
    return body[start : body.index('"', start)]


async def login(http: AsyncClient, username: str, password: str) -> str:
    """Connecte le client et retourne le jeton CSRF de la session."""
    csrf = await get_csrf(http)
    response = await http.post(
        "/login", data={"username": username, "password": password, "csrf_token": csrf}
    )
    assert response.status_code == 303, response.text
    return csrf
