"""Cookie de session signé, avec option « Rester connecté ».

Variante du ``SessionMiddleware`` de Starlette (même format de cookie : JSON en base64
signé par ``itsdangerous.TimestampSigner``, donc les cookies existants restent lisibles)
dont la durée dépend de la session elle-même :

- session ordinaire : cookie **de navigateur** (sans ``Max-Age``, effacé à la fermeture du
  navigateur) et refusée côté serveur après ``max_age`` secondes d'inactivité ;
- session marquée ``REMEMBER_KEY`` (case « Rester connecté » à la connexion) : cookie
  persistant de ``remember_max_age`` secondes.

Le cookie est re-signé à chaque réponse : les deux durées sont donc glissantes (comptées
depuis la dernière requête), comme avec Starlette.
"""

import json
import time
from base64 import b64decode, b64encode
from typing import Literal

import itsdangerous
from itsdangerous.exc import BadSignature
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REMEMBER_KEY = "remember"


class SessionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        max_age: int,
        remember_max_age: int,
        session_cookie: str = "session",
        same_site: Literal["lax", "strict", "none"] = "lax",
        https_only: bool = False,
    ) -> None:
        self.app = app
        self.signer = itsdangerous.TimestampSigner(secret_key)
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.remember_max_age = remember_max_age
        self.security_flags = "httponly; samesite=" + same_site
        if https_only:
            self.security_flags += "; secure"

    def _load(self, raw: str) -> dict:
        """Session portée par le cookie, ou {} si invalide ou expirée."""
        try:
            data, signed_at = self.signer.unsign(
                raw.encode("utf-8"),
                max_age=max(self.max_age, self.remember_max_age),
                return_timestamp=True,
            )
            session = json.loads(b64decode(data))
        except (BadSignature, ValueError):
            return {}
        if not isinstance(session, dict):
            return {}
        limit = self.remember_max_age if session.get(REMEMBER_KEY) else self.max_age
        if time.time() - signed_at.timestamp() > limit:
            return {}
        return session

    def _cookie(self, value: str, attributes: str) -> str:
        return f"{self.session_cookie}={value}; path=/; {attributes}{self.security_flags}"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):  # pragma: no cover
            await self.app(scope, receive, send)
            return

        raw = HTTPConnection(scope).cookies.get(self.session_cookie)
        scope["session"] = self._load(raw) if raw else {}
        had_session = bool(scope["session"])

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session = scope["session"]
                headers = MutableHeaders(scope=message)
                if session:
                    data = self.signer.sign(b64encode(json.dumps(session).encode("utf-8")))
                    max_age = f"Max-Age={self.remember_max_age}; " if session.get(REMEMBER_KEY) else ""
                    headers.append("Set-Cookie", self._cookie(data.decode("utf-8"), max_age))
                elif had_session or raw:
                    # Session vidée (déconnexion) ou cookie invalide/expiré : on l'efface.
                    headers.append(
                        "Set-Cookie", self._cookie("null", "expires=Thu, 01 Jan 1970 00:00:00 GMT; ")
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
