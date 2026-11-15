"""Point d'entrée FastAPI : middlewares, routers, lifespan (DB, admin, scheduler)."""

import asyncio
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import select
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api import create_api
from app.config import Settings, get_settings
from app.database import dispose_engine, init_engine, session_factory
from app.deps import NotAuthenticatedError
from app.i18n import LOCALE_COOKIE, negotiate_locale, set_locale
from app.models import RESEAU_SINGLETON_ID, Reseau, Role, Subnet, User
from app.routers import (
    audit as audit_router,
    auth as auth_router,
    dashboard as dashboard_router,
    health as health_router,
    import_export as import_export_router,
    ips as ips_router,
    monitors as monitors_router,
    reseau as reseau_router,
    service_accounts as service_accounts_router,
    subnets as subnets_router,
    users as users_router,
)
from app.services import backup, ipam
from app.services.auth import CSRF_SESSION_KEY, generate_csrf_token, hash_password
from app.services.monitor import scheduler_tick

logger = logging.getLogger("guipam")

BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent / "static"


def run_migrations(settings: Settings) -> None:
    """Alembic upgrade head (moteur sync, exécuté dans un thread au démarrage).

    Un instantané de la base est pris juste avant si le schéma va changer.
    """
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{settings.db_path}")
    scripts = ScriptDirectory.from_config(cfg)
    revision = backup.current_revision(settings.db_path)
    if revision is not None and revision not in {rev.revision for rev in scripts.walk_revisions()}:
        # Base créée par une version plus récente : on ne touche à rien.
        raise RuntimeError(
            f"La base {settings.db_path} est au schéma « {revision} », inconnu de GuiPAM {__version__} : "
            "elle vient d'une version plus récente. Réinstallez cette version (ou une plus récente), "
            "ou restaurez un instantané de /data/backups antérieur à la mise à jour."
        )
    backup.snapshot_before_migration(
        settings.db_path, scripts.get_current_head(), settings.backup_keep_pre_migration
    )
    command.upgrade(cfg, "head")


async def bootstrap(settings: Settings) -> None:
    """Premier admin depuis l'env (si table User vide) + réseau singleton."""
    async with session_factory()() as session:
        users = (await session.exec(select(User).limit(1))).first()
        if users is None:
            if not settings.admin_password:
                raise RuntimeError(
                    "Aucun utilisateur en base et GUIPAM_ADMIN_PASSWORD non définie. "
                    "Définissez GUIPAM_ADMIN_USERNAME / GUIPAM_ADMIN_PASSWORD pour créer "
                    "le premier compte manager, puis redémarrez."
                )
            session.add(
                User(
                    username=settings.admin_username,
                    hashed_password=hash_password(settings.admin_password),
                    role=Role.manager,
                )
            )
            logger.info("Compte manager initial « %s » créé.", settings.admin_username)
        reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
        if reseau is None:
            name = "Mon réseau" if settings.default_locale == "fr" else "My network"
            session.add(Reseau(id=RESEAU_SINGLETON_ID, name=name, default_locale=settings.default_locale))
        await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_secret_key()
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    init_engine(settings.database_url)
    await asyncio.to_thread(run_migrations, settings)
    await bootstrap(settings)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduler_tick,
        "interval",
        seconds=settings.monitor_tick_seconds,
        max_instances=1,
        coalesce=True,
    )
    if settings.backup_keep_daily > 0:
        # Instantané quotidien de la base (et un tout de suite s'il manque celui du jour).
        async def daily_backup() -> None:
            await asyncio.to_thread(backup.daily_snapshot, settings.db_path, settings.backup_keep_daily)

        scheduler.add_job(
            daily_backup,
            "interval",
            hours=6,
            next_run_time=datetime.now(),
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("GuiPAM démarré (tick monitor : %ss).", settings.monitor_tick_seconds)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="GuiPAM", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        """Charge user + réseau dans request.state, négocie la locale, pose le CSRF."""
        path = request.url.path
        if path.startswith("/static") or path == "/healthz":
            return await call_next(request)
        if path.startswith("/api/"):
            # API : pas de session ni de CSRF (authentification par clé) ; messages
            # d'erreur en anglais sauf Accept-Language explicite.
            set_locale(negotiate_locale(None, None, request.headers.get("accept-language"), "en"))
            return await call_next(request)

        if CSRF_SESSION_KEY not in request.session:
            request.session[CSRF_SESSION_KEY] = generate_csrf_token()

        user = None
        reseau = None
        nav_subnets: list[Subnet] = []
        try:
            async with session_factory()() as session:
                user_id = request.session.get("user_id")
                if user_id is not None:
                    user = await session.get(User, user_id)
                    if user is not None and not user.is_active:
                        user = None
                reseau = await session.get(Reseau, RESEAU_SINGLETON_ID)
                # Menu « Réseaux » : seulement pour les pages complètes (les partials
                # HTMX n'étendent pas base.html).
                if user is not None and not request.headers.get("hx-request"):
                    rows = (await session.exec(select(Subnet))).all()
                    nav_subnets = sorted(rows, key=lambda s: ipam.network_sort_key(s.cidr))
        except RuntimeError:
            pass  # moteur non initialisé (tests unitaires sans DB)
        request.state.user = user
        request.state.reseau = reseau
        request.state.nav_subnets = nav_subnets
        set_locale(
            negotiate_locale(
                user.locale if user else None,
                request.cookies.get(LOCALE_COOKIE),
                request.headers.get("accept-language"),
                (reseau.default_locale if reseau else None) or settings.default_locale,
            )
        )
        return await call_next(request)

    # Ajouté après le middleware de contexte pour s'exécuter avant lui (la
    # session doit exister quand le contexte la lit).
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key or "guipam-debug-only",
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.secure_cookies,
    )

    @app.exception_handler(NotAuthenticatedError)
    async def not_authenticated(request: Request, exc: NotAuthenticatedError):
        if request.headers.get("hx-request"):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", status_code=302)

    app.include_router(health_router.router)
    app.include_router(auth_router.router)
    app.include_router(dashboard_router.router)
    app.include_router(reseau_router.router)
    app.include_router(subnets_router.router)
    app.include_router(ips_router.router)
    app.include_router(monitors_router.router)
    app.include_router(users_router.router)
    app.include_router(audit_router.router)
    app.include_router(import_export_router.router)
    app.include_router(service_accounts_router.router)
    app.mount("/api/v1", create_api())
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    run()
