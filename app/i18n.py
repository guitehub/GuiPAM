"""Internationalisation : Babel + gettext.

Les msgid du code sont en anglais ; le catalogue `fr` (complet en v1) est
compilé au build (`.po` → `.mo`). La locale courante est portée par une
contextvar positionnée par un middleware à chaque requête.
"""

from contextvars import ContextVar
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from babel import dates
from babel.support import NullTranslations, Translations

from app.models import utcnow

LOCALE_DIR = Path(__file__).parent / "locale"
LOCALE_COOKIE = "guipam_locale"
FALLBACK_LOCALE = "fr"

_current_locale: ContextVar[str] = ContextVar("current_locale", default=FALLBACK_LOCALE)


def available_locales() -> list[str]:
    """Locales disposant d'un catalogue, plus « en » (langue des msgid)."""
    found = {"en"}
    if LOCALE_DIR.is_dir():
        for child in LOCALE_DIR.iterdir():
            if (child / "LC_MESSAGES").is_dir():
                found.add(child.name)
    return sorted(found)


@lru_cache
def get_translations(locale: str) -> NullTranslations:
    translations = Translations.load(str(LOCALE_DIR), locales=[locale])
    return translations


def set_locale(locale: str) -> None:
    _current_locale.set(locale)


def get_locale() -> str:
    return _current_locale.get()


def gettext(message: str) -> str:
    return get_translations(get_locale()).gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return get_translations(get_locale()).ngettext(singular, plural, n)


_ = gettext


def negotiate_locale(
    user_locale: str | None,
    cookie_locale: str | None,
    accept_language: str | None,
    default_locale: str | None,
) -> str:
    """Priorité : préférence utilisateur → cookie → Accept-Language → défaut réseau → fr."""
    supported = available_locales()
    for candidate in (user_locale, cookie_locale):
        if candidate and candidate in supported:
            return candidate
    if accept_language:
        for part in accept_language.split(","):
            code = part.split(";")[0].strip().lower()
            short = code.split("-")[0]
            if code in supported:
                return code
            if short in supported:
                return short
    if default_locale and default_locale in supported:
        return default_locale
    return FALLBACK_LOCALE


def format_relative(dt: datetime | None, now: datetime | None = None) -> str:
    """Date relative localisée (« il y a 3 minutes »)."""
    if dt is None:
        return _("never")
    reference = now or utcnow()
    return dates.format_timedelta(
        dt - reference,
        granularity="second",
        add_direction=True,
        locale=get_locale(),
    )


def format_datetime(dt: datetime | None) -> str:
    if dt is None:
        return _("never")
    return dates.format_datetime(dt, format="short", locale=get_locale())
