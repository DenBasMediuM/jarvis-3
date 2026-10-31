"""Пользователи публичной витрины: хеши паролей и матрица доступа."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import ROOT

PBKDF2_ITERS = 200_000
PBKDF2_ALGO = "sha256"

# id → подпись в админке
ACCESS_OPTIONS: list[dict[str, str]] = [
    {"id": "quality", "label": "Качество", "group": "Качество"},
    {
        "id": "processes.upsell",
        "label": "Досогласования",
        "group": "Процессы",
    },
    {
        "id": "processes.debt",
        "label": "Дебиторка",
        "group": "Процессы",
    },
    {
        "id": "processes.branch_kpi",
        "label": "КПД филиалов",
        "group": "Процессы",
    },
    {
        "id": "processes.reviews",
        "label": "Сбор отзывов",
        "group": "Процессы",
    },
    {
        "id": "processes.reviews_stats",
        "label": "Статистика по сбору отзывов",
        "group": "Процессы",
    },
    {
        "id": "processes.buffer_quality",
        "label": "Качество обработки буфера",
        "group": "Процессы",
    },
    {"id": "finance", "label": "Финансы", "group": "Финансы"},
]

ACCESS_IDS = {o["id"] for o in ACCESS_OPTIONS}


def default_users_json_path() -> Path:
    return ROOT / "docs" / "auth" / "users.json"


def hash_password(password: str, *, salt_hex: str | None = None) -> tuple[str, str]:
    """Вернуть (salt_hex, hash_hex) через PBKDF2-HMAC-SHA256."""
    if not password or len(password) < 4:
        raise ValueError("Пароль слишком короткий (мин. 4 символа)")
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        PBKDF2_ALGO, password.encode("utf-8"), salt, PBKDF2_ITERS
    )
    return salt.hex(), dk.hex()


def feedback_verifier(password: str, *, salt_hex: str | None = None) -> tuple[str, str]:
    """Верификатор для Worker «Улучшения» → (fb_salt_hex, fb_verifier_hex).

    Браузер при входе считает proof = PBKDF2(password, fb_salt, 200k) и отправляет его Worker'у,
    а тот сверяет sha256(proof) с fb_verifier из users.json. Так тяжёлый хеш считает клиент
    (Workers не умеют PBKDF2 > 100k итераций), а в публичном users.json лежит только sha256 от
    секрета, который без пароля не получить.
    """
    fb_salt, proof_hex = hash_password(password, salt_hex=salt_hex)
    return fb_salt, hashlib.sha256(bytes.fromhex(proof_hex)).hexdigest()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        _, check = hash_password(password, salt_hex=salt_hex)
    except ValueError:
        return False
    return secrets.compare_digest(check, hash_hex)


def normalize_access(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = [x.strip() for x in raw.split(",") if x.strip()]
    out: list[str] = []
    for item in raw:
        key = str(item or "").strip()
        if key in ACCESS_IDS and key not in out:
            out.append(key)
    return out


def public_user_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "login": row.get("login"),
        "access": normalize_access(row.get("access_json") or row.get("access")),
        "enabled": bool(int(row.get("enabled") if row.get("enabled") is not None else 1)),
        # есть верификатор для «Улучшений» (иначе нужно заново задать пароль)
        "feedback_ready": bool(row.get("fb_verifier")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def export_users_payload(users: list[dict[str, Any]]) -> dict[str, Any]:
    """Снимок для Pages: только login/salt/hash/access (без plaintext)."""
    exported: list[dict[str, Any]] = []
    for u in users:
        if not int(u.get("enabled") if u.get("enabled") is not None else 1):
            continue
        item = {
            "login": u["login"],
            "salt": u["salt"],
            "hash": u["password_hash"],
            "iters": PBKDF2_ITERS,
            "algo": PBKDF2_ALGO,
            "access": normalize_access(u.get("access_json") or u.get("access")),
        }
        if u.get("fb_salt") and u.get("fb_verifier"):
            item["fb_salt"] = u["fb_salt"]
            item["fb_verifier"] = u["fb_verifier"]
        exported.append(item)
    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "pbkdf2_iterations": PBKDF2_ITERS,
        "users": exported,
    }


def write_users_json(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or default_users_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target
