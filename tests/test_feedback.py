from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from modules.feedback.client import (
    FeedbackClient,
    FeedbackError,
    summarize,
    validate_update,
)


def test_validate_update_rules():
    assert validate_update({"status": "approved"}) == {"status": "approved"}
    assert validate_update({"status": "done", "admin_comment": "  ок  ", "priority": "2"}) == {
        "status": "done",
        "admin_comment": "ок",
        "priority": 2,
    }
    assert validate_update({"priority": None}) == {"priority": None}
    with pytest.raises(ValueError):
        validate_update({"status": "weird"})
    with pytest.raises(ValueError):
        validate_update({"status": "rejected", "admin_comment": "  "})
    with pytest.raises(ValueError):
        validate_update({})


def test_summarize_counts():
    c = summarize([{"status": "new"}, {"status": "new"}, {"status": "done"}, {"status": "x"}])
    assert c["new"] == 2 and c["done"] == 1 and c["rejected"] == 0


def _client(handler):
    return FeedbackClient("https://w.example/", "adm", transport=httpx.MockTransport(handler))


def test_client_sends_admin_key_and_parses():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers.get("Authorization")
        seen["url"] = str(req.url)
        if req.method == "PATCH":
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": True, "items": [{"id": 1, "status": "new"}]})

    c = _client(handler)
    items = asyncio.run(c.list_requests())
    assert items == [{"id": 1, "status": "new"}]
    assert seen["auth"] == "Bearer adm"
    assert seen["url"] == "https://w.example/admin/requests"
    asyncio.run(c.update_request(5, {"status": "approved"}))
    assert seen["url"] == "https://w.example/admin/requests/5"
    assert seen["body"] == {"status": "approved"}


def test_client_errors():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "message": "Укажите причину"})

    with pytest.raises(FeedbackError, match="Укажите причину"):
        asyncio.run(_client(handler).update_request(1, {"status": "rejected"}))
    with pytest.raises(FeedbackError, match="не настроен"):
        asyncio.run(FeedbackClient("", "").list_requests())


def test_push_product_sends_markdown():
    got = {}

    def handler(req: httpx.Request) -> httpx.Response:
        got["body"] = json.loads(req.content)
        return httpx.Response(200, json={"ok": True, "chars": 3})

    res = asyncio.run(_client(handler).push_product("abc"))
    assert res["chars"] == 3 and got["body"] == {"markdown": "abc"}


def test_feedback_verifier_and_export():
    import hashlib

    from core.vitrine_auth import export_users_payload, feedback_verifier, hash_password

    fb_salt, ver = feedback_verifier("pass1234")
    _, proof = hash_password("pass1234", salt_hex=fb_salt)  # то, что посчитает браузер
    assert hashlib.sha256(bytes.fromhex(proof)).hexdigest() == ver
    rows = [
        {"login": "a", "salt": "s", "password_hash": "h", "enabled": 1, "fb_salt": fb_salt, "fb_verifier": ver},
        {"login": "b", "salt": "s", "password_hash": "h", "enabled": 1},
    ]
    users = export_users_payload(rows)["users"]
    assert users[0]["fb_verifier"] == ver and "fb_verifier" not in users[1]
