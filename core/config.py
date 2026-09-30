from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
WEB_DIR = ROOT / "web"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="JARVIS_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8787
    data_dir: Path = DATA_DIR
    db_path: Path | None = None
    secret_key_path: Path | None = None

    # Default OpenAI-compatible endpoint (Ollama). Override in UI/settings.
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "llama3.2"

    default_gincore_base_url: str = "https://itserviceoutsourcing.gincore.net"

    def resolved_db_path(self) -> Path:
        return self.db_path or (self.data_dir / "jarvis.db")

    def resolved_secret_key_path(self) -> Path:
        return self.secret_key_path or (self.data_dir / "secret.key")


settings = Settings()
