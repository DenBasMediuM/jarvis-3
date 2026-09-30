from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


@dataclass
class SettingField:
    key: str
    label: str
    type: str = "text"  # text | password | url | number | checkbox
    placeholder: str = ""
    help: str = ""
    secret: bool = False


@dataclass
class ModuleManifest:
    id: str
    name: str
    description: str
    settings: list[SettingField] = field(default_factory=list)


class BaseModule:
    """Contract for Jarvis modules (Python now; other languages via HTTP later)."""

    id: str = "base"
    name: str = "Base"
    description: str = ""

    def settings_schema(self) -> list[SettingField]:
        return []

    def tools(self) -> list[ToolSpec]:
        return []

    async def on_settings_saved(self, settings: dict[str, Any]) -> None:
        return None

    def manifest(self) -> ModuleManifest:
        return ModuleManifest(
            id=self.id,
            name=self.name,
            description=self.description,
            settings=self.settings_schema(),
        )
