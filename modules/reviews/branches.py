"""Филиалы ИТСА для учёта рейтинга Google."""

from __future__ import annotations

from typing import Any

# Ссылки — поиск карточки в Google Maps (менеджер открывает и смотрит рейтинг/число).
BRANCHES: list[dict[str, str]] = [
    {
        "id": "karetnaya",
        "name": "Каретный",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=%D0%98%D0%A2%D0%A1%D0%90+%D0%9A%D0%B0%D1%80%D0%B5%D1%82%D0%BD%D1%8B%D0%B9+%D0%9E%D0%B4%D0%B5%D1%81%D1%81%D0%B0",
        "review_url": "https://www.google.com/maps/search/?api=1&query=%D0%98%D0%A2%D0%A1%D0%90+%D0%9A%D0%B0%D1%80%D0%B5%D1%82%D0%BD%D1%8B%D0%B9+%D0%9E%D0%B4%D0%B5%D1%81%D1%81%D0%B0",
    },
    {
        "id": "segedskaya",
        "name": "Сегедская",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=%D0%98%D0%A2%D0%A1%D0%90+%D0%A1%D0%B5%D0%B3%D0%B5%D0%B4%D1%81%D0%BA%D0%B0%D1%8F+%D0%9E%D0%B4%D0%B5%D1%81%D1%81%D0%B0",
        "review_url": "https://www.google.com/maps/search/?api=1&query=%D0%98%D0%A2%D0%A1%D0%90+%D0%A1%D0%B5%D0%B3%D0%B5%D0%B4%D1%81%D0%BA%D0%B0%D1%8F+%D0%9E%D0%B4%D0%B5%D1%81%D1%81%D0%B0",
    },
    {
        "id": "levitana",
        "name": "Левитана",
        "maps_url": "https://www.google.com/maps/search/?api=1&query=%D0%98%D0%A2%D0%A1%D0%90+%D0%9B%D0%B5%D0%B2%D0%B8%D1%82%D0%B0%D0%BD%D0%B0+%D0%9E%D0%B4%D0%B5%D1%81%D1%81%D0%B0",
        "review_url": "https://www.google.com/maps/search/?api=1&query=%D0%98%D0%A2%D0%A1%D0%90+%D0%9B%D0%B5%D0%B2%D0%B8%D1%82%D0%B0%D0%BD%D0%B0+%D0%9E%D0%B4%D0%B5%D1%81%D1%81%D0%B0",
    },
]

BRANCH_IDS = {b["id"] for b in BRANCHES}


def branches_public() -> list[dict[str, str]]:
    return [dict(b) for b in BRANCHES]


def branch_by_id(branch_id: str) -> dict[str, str] | None:
    for b in BRANCHES:
        if b["id"] == branch_id:
            return dict(b)
    return None


def guess_branch_id(location: str | None) -> str | None:
    loc = (location or "").casefold()
    if "карет" in loc:
        return "karetnaya"
    if "сегед" in loc:
        return "segedskaya"
    if "левитан" in loc:
        return "levitana"
    return None


CALL_OUTCOMES: dict[str, str] = {
    "will_review": "оставит отзыв",
    "no_answer": "не дозвон",
    "wont_review": "не оставит отзыв",
    "unhappy": "клиент не доволен",
}


def outcome_label(code: str | None) -> str:
    if not code:
        return "—"
    return CALL_OUTCOMES.get(str(code), str(code))


DEFAULT_CALL_SCRIPT: dict[str, Any] = {
    "title": "Скрипт звонка · сбор отзывов",
    "steps": [
        {
            "id": "hello",
            "label": "Приветствие",
            "text": "Здравствуйте, это сервисный центр ИТСА. Вы нам сдавали {device} в ремонт{when_phrase}. Скажите, всё в порядке? Работает?",
        },
        {
            "id": "ok",
            "label": "Если всё хорошо",
            "text": "Отлично! Будем очень признательны, если оставите короткий отзыв о сервисе в Google — это помогает другим клиентам выбрать нас. Сейчас отправлю вам SMS со ссылкой (или продиктую / скину в мессенджер).",
        },
        {
            "id": "not_ok",
            "label": "Если не всё в порядке",
            "text": "Жаль это слышать. Расскажите, пожалуйста, что именно не так — я зафиксирую и передам менеджеру, который поможет разобраться.",
        },
        {
            "id": "no_answer",
            "label": "Недозвон",
            "text": "Отметьте «не дозвон» и переходите к следующей карточке. Повторный прозвон — по решению руководителя.",
        },
        {
            "id": "refuse",
            "label": "Отказ оставить отзыв",
            "text": "Благодарим за ответ, хорошего дня. Отметьте «не оставит отзыв».",
        },
    ],
}
