"""Lanceur : écouteurs HTTPS et HTTP dans un même processus (plusieurs uvicorn.Server, une boucle).

| GUIPAM_TLS | GUIPAM_HTTP_MODE | HTTPS (https_port)   | HTTP (http_port)                              |
|------------|------------------|----------------------|-----------------------------------------------|
| auto       | redirect (déf.)  | application          | 308 vers l'HTTPS, sauf /healthz               |
| auto       | proxy            | application          | application, X-Forwarded-* des proxies déclarés |
| auto       | off              | application          | —                                             |
| off        | (ignoré)         | —                    | application (comportement 0.5)                |

Le premier écouteur (« principal ») exécute le lifespan de l'application (migrations, scheduler) ; le
second ne démarre qu'une fois le principal prêt et partage le même objet application. L'écouteur
HTTPS n'accepte jamais d'en-têtes X-Forwarded-* : seul l'écouteur proxy (ou HTTP en TLS off) les lit,
et seulement depuis GUIPAM_TRUSTED_PROXIES.
"""

import asyncio
import contextlib
import copy
import logging
import logging.config
import re
import signal
from dataclasses import dataclass

import uvicorn
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send
from uvicorn.config import LOGGING_CONFIG

from app import tls
from app.config import Settings, get_settings

logger = logging.getLogger("guipam")

_HOST = re.compile(r"^(?:\[(?P<v6>[0-9a-fA-F:.]+)\]|(?P<name>[A-Za-z0-9._-]+))(?::\d+)?$")


def log_config() -> dict:
    """Configuration uvicorn + loggers « guipam » (empreintes TLS, avertissements) au même format."""
    config = copy.deepcopy(LOGGING_CONFIG)
    config["loggers"]["guipam"] = {"handlers": ["default"], "level": "INFO", "propagate": False}
    return config


class RedirectToHttps:
    """Écouteur HTTP en mode redirect : 308 vers la même URL en HTTPS ; /healthz délégué à l'application."""

    def __init__(self, app: ASGIApp, https_port: int) -> None:
        self.app = app
        self.port_suffix = "" if https_port == 443 else f":{https_port}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/healthz":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # websocket : rien à servir en clair
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        match = _HOST.match(Headers(scope=scope).get("host", ""))
        if match is None:
            await self._respond(send, 400, b"Bad Request: missing or invalid Host header\n")
            return
        host = f"[{match['v6']}]" if match["v6"] else match["name"]
        target = scope.get("raw_path") or scope["path"].encode()
        if scope.get("query_string"):
            target += b"?" + scope["query_string"]
        location = f"https://{host}{self.port_suffix}".encode() + target
        await self._respond(send, 308, b"Redirecting to HTTPS\n", [(b"location", location)])

    @staticmethod
    async def _respond(send: Send, status: int, body: bytes, headers: list | None = None) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    *(headers or []),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


@dataclass
class Listener:
    name: str  # "https" | "http-redirect" | "http-proxy" | "http"
    config: uvicorn.Config


def _proxy_options(settings: Settings) -> dict:
    proxies = settings.trusted_proxy_list
    return {"proxy_headers": bool(proxies), "forwarded_allow_ips": proxies or ""}


def build_listeners(settings: Settings, app: ASGIApp, info: tls.TlsInfo) -> list[Listener]:
    """Écouteurs à lancer, le principal (lifespan) en tête."""
    # ws="none" : GuiPAM ne sert pas de websocket.
    common = {"host": settings.host, "log_config": None, "server_header": False, "ws": "none"}
    if not info.enabled:
        config = uvicorn.Config(app, port=settings.http_port, lifespan="on", **common, **_proxy_options(settings))
        return [Listener("http", config)]
    listeners = [
        Listener(
            "https",
            uvicorn.Config(
                app,
                port=settings.https_port,
                ssl_certfile=str(info.certfile),
                ssl_keyfile=str(info.keyfile),
                proxy_headers=False,
                lifespan="on",
                **common,
            ),
        )
    ]
    if settings.http_mode == "redirect":
        redirect = RedirectToHttps(app, settings.redirect_https_port)
        config = uvicorn.Config(redirect, port=settings.http_port, lifespan="off", proxy_headers=False, **common)
        listeners.append(Listener("http-redirect", config))
    elif settings.http_mode == "proxy":
        config = uvicorn.Config(app, port=settings.http_port, lifespan="off", **common, **_proxy_options(settings))
        listeners.append(Listener("http-proxy", config))
    return listeners


class _Server(uvicorn.Server):
    """uvicorn.Server sans sa propre capture des signaux (sinon un SIGTERM n'arrêterait qu'un écouteur)."""

    @contextlib.contextmanager
    def capture_signals(self):
        yield


async def _serve(server: _Server) -> bool:
    """Lance un serveur ; False s'il n'a pas pu démarrer (port occupé…) au lieu d'un sys.exit."""
    try:
        await server.serve()
    except SystemExit:
        return False
    return server.started


async def serve_listeners(
    listeners: list[Listener], install_signal_handlers: bool = True, shutdown: asyncio.Event | None = None
) -> int:
    """Lance les écouteurs jusqu'à l'arrêt (signal, `shutdown`, ou fin de l'un d'eux). Renvoie un code de sortie."""
    servers = [_Server(listener.config) for listener in listeners]

    def stop() -> None:
        for server in servers:
            server.should_exit = True

    signals_received = 0

    def on_signal() -> None:
        nonlocal signals_received
        signals_received += 1
        stop()
        if signals_received > 1:  # deuxième Ctrl+C / SIGTERM : arrêt forcé, comme uvicorn
            for server in servers:
                server.force_exit = True

    loop = asyncio.get_running_loop()
    if install_signal_handlers:
        loop.add_signal_handler(signal.SIGTERM, on_signal)
        loop.add_signal_handler(signal.SIGINT, on_signal)
    try:
        primary = asyncio.create_task(_serve(servers[0]))
        while not servers[0].started and not primary.done():
            await asyncio.sleep(0.05)
        if not servers[0].started:
            await primary
            return 3  # code de uvicorn pour un échec de démarrage
        for listener in listeners:
            context = getattr(listener.config, "ssl", None)  # créé par config.load() au démarrage
            if context is not None:
                tls.register_context(context)

        tasks = [primary] + [asyncio.create_task(_serve(server)) for server in servers[1:]]
        waiter = asyncio.create_task(shutdown.wait()) if shutdown is not None else None
        await asyncio.wait(tasks + ([waiter] if waiter else []), return_when=asyncio.FIRST_COMPLETED)
        stop()
        if waiter is not None:
            waiter.cancel()
        results = await asyncio.gather(*tasks)
    finally:
        if install_signal_handlers:
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)
    return 0 if all(results) else 1


def run(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    logging.config.dictConfig(log_config())
    for message in settings.startup_warnings():
        logger.warning(message)
    try:
        info = tls.prepare(settings)
    except tls.TlsError as exc:
        logger.error("%s", exc)
        return 1

    from app.main import app

    listeners = build_listeners(settings, app, info)
    for listener in listeners:
        scheme = "https" if listener.name == "https" else "http"
        role = {
            "https": "application",
            "http": "application (TLS désactivé)",
            "http-redirect": f"redirection 308 vers le port {settings.redirect_https_port}, /healthz",
            "http-proxy": f"application pour reverse proxy (proxies de confiance : {settings.trusted_proxies or 'aucun'})",
        }[listener.name]
        logger.info("Écoute %s://%s:%s : %s.", scheme, settings.host, listener.config.port, role)
    return asyncio.run(serve_listeners(listeners))


if __name__ == "__main__":
    raise SystemExit(run())
