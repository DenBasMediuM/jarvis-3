"""Экспорт уже лежит в docs/ — этот модуль делает git add/commit/push для Pages."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from core.config import ROOT


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def publish_docs_files(
    rel_paths: list[str],
    *,
    message: str,
) -> dict[str, Any]:
    """
    git add + commit (если есть изменения) + push указанных файлов под docs/.
    Возвращает {ok, skipped?, committed?, pushed?, paths, log}.
    """
    root = ROOT
    if not (root / ".git").exists():
        raise RuntimeError("Корень проекта не является git-репозиторием")

    clean: list[str] = []
    for raw in rel_paths:
        p = Path(raw)
        if p.is_absolute():
            try:
                p = p.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"Путь вне репозитория: {raw}") from exc
        parts = p.parts
        if not parts or parts[0] != "docs":
            raise ValueError(f"Разрешены только файлы в docs/: {raw}")
        if ".." in parts:
            raise ValueError(f"Недопустимый путь: {raw}")
        full = root / p
        if not full.is_file():
            raise FileNotFoundError(f"Нет файла: {p}")
        clean.append(str(p).replace("\\", "/"))

    if not clean:
        return {"ok": True, "skipped": True, "reason": "empty", "paths": []}

    add = _run(["git", "add", "--", *clean], cwd=root)
    if add.returncode != 0:
        raise RuntimeError(f"git add: {(add.stderr or add.stdout or '').strip()}")

    porcelain = _run(["git", "status", "--porcelain", "--", *clean], cwd=root)
    if porcelain.returncode != 0:
        raise RuntimeError(f"git status: {(porcelain.stderr or porcelain.stdout or '').strip()}")
    if not (porcelain.stdout or "").strip():
        return {
            "ok": True,
            "skipped": True,
            "reason": "no_changes",
            "paths": clean,
            "committed": False,
            "pushed": False,
        }

    commit = _run(["git", "commit", "-m", message], cwd=root)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit: {(commit.stderr or commit.stdout or '').strip()}")

    push = _run(["git", "push"], cwd=root)
    if push.returncode != 0:
        raise RuntimeError(f"git push: {(push.stderr or push.stdout or '').strip()}")

    return {
        "ok": True,
        "skipped": False,
        "committed": True,
        "pushed": True,
        "paths": clean,
        "log": ((commit.stdout or "") + (push.stdout or "")).strip()[:500],
    }
