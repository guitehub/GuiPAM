"""Messages flash portés par la session (toasts après HX-Refresh ou redirection)."""

from fastapi import Request

FLASH_KEY = "flash"


def flash(request: Request, message: str, category: str = "success") -> None:
    messages = request.session.get(FLASH_KEY, [])
    messages.append({"message": message, "category": category})
    request.session[FLASH_KEY] = messages


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop(FLASH_KEY, [])
