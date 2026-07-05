"""Authentification : bcrypt direct (pas passlib), anti-brute-force, CSRF."""

import hmac
import secrets
import time
from dataclasses import dataclass, field

import bcrypt

# bcrypt ignore tout au-delà de 72 octets : on tronque explicitement.
BCRYPT_MAX_BYTES = 72

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"

MAX_ATTEMPTS = 5
BASE_LOCKOUT_SECONDS = 30
MAX_LOCKOUT_SECONDS = 900


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    raw = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, hashed.encode("ascii"))
    except ValueError:
        return False


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_tokens_match(expected: str | None, provided: str | None) -> bool:
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


@dataclass
class _AttemptState:
    failures: int = 0
    locked_until: float = field(default=0.0)


class LoginRateLimiter:
    """Compteur en mémoire par (IP, username) avec backoff exponentiel."""

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        base_lockout: float = BASE_LOCKOUT_SECONDS,
        max_lockout: float = MAX_LOCKOUT_SECONDS,
    ) -> None:
        self._states: dict[tuple[str, str], _AttemptState] = {}
        self.max_attempts = max_attempts
        self.base_lockout = base_lockout
        self.max_lockout = max_lockout

    def _key(self, ip: str, username: str) -> tuple[str, str]:
        return (ip, username.lower())

    def retry_after(self, ip: str, username: str) -> float:
        """Secondes restantes de blocage (0 si autorisé à tenter)."""
        state = self._states.get(self._key(ip, username))
        if state is None:
            return 0.0
        return max(0.0, state.locked_until - time.monotonic())

    def record_failure(self, ip: str, username: str) -> None:
        state = self._states.setdefault(self._key(ip, username), _AttemptState())
        state.failures += 1
        if state.failures >= self.max_attempts:
            exponent = state.failures - self.max_attempts
            lockout = min(self.base_lockout * (2**exponent), self.max_lockout)
            state.locked_until = time.monotonic() + lockout

    def record_success(self, ip: str, username: str) -> None:
        self._states.pop(self._key(ip, username), None)


login_rate_limiter = LoginRateLimiter()
