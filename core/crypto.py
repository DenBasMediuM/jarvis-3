from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet


def ensure_fernet(key_path: Path) -> Fernet:
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        key = key_path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        key_path.chmod(0o600)
    return Fernet(key)


class SecretBox:
    def __init__(self, key_path: Path) -> None:
        self._fernet = ensure_fernet(key_path)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
