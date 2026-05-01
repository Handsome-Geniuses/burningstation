from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
try:
    from .settings import Settings
except:
    from settings import Settings


def get_settings_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "settings.json"
    return Path(__file__).resolve().parent / "settings.json"


def deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            base[key] = deep_update(base[key], value)
        else:
            base[key] = value
    return base


class SettingsStore:
    _instance: SettingsStore | None = None
    _initialized = False

    def __new__(cls, path: str | Path | None = None) -> SettingsStore:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, path: str | Path | None = None) -> None:
        if self.__class__._initialized:
            return

        self.path = Path(path) if path else get_settings_path()
        self._settings: Settings | None = None
        self.__class__._initialized = True

    @property
    def settings(self) -> Settings:
        return self.load()

    def ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            default_settings = Settings()
            self.path.write_text(
                default_settings.model_dump_json(indent=4),
                encoding="utf-8",
            )

    def load(self, force: bool = False) -> Settings:
        if self._settings is not None and not force:
            return self._settings

        self.ensure_file()

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in settings file: {self.path}") from exc

        self._settings = Settings.model_validate(data)
        return self._settings

    def save(self) -> None:
        settings = self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            settings.model_dump_json(indent=4),
            encoding="utf-8",
        )

    def reload(self) -> Settings:
        return self.load(force=True)

    def to_dict(self) -> dict[str, Any]:
        return self.load().model_dump()

    def to_json(self, indent: int | None = None) -> str:
        return self.load().model_dump_json(indent=indent)

    def get_schema(self) -> dict[str, Any]:
        return Settings.model_json_schema()

    def to_frontend(self) -> dict[str, Any]:
        return {
            "values": self.to_dict(),
            "schema": self.get_schema(),
        }

    def set_from_dict(self, data: dict[str, Any]) -> Settings:
        settings = Settings.model_validate(data)
        self._settings = settings
        self.save()
        return settings

    def update_from_dict(self, data: dict[str, Any]) -> Settings:
        current = self.load()
        merged = deep_update(current.model_dump(), data)
        updated = Settings.model_validate(merged)
        self._settings = updated
        self.save()
        return updated


store = SettingsStore()
store.load()

if __name__ == "__main__":
    print("Loaded:")
    print(store.settings.model_dump())

    # store.settings.value = 10
    # store.update_from_dict({"dummy": {"enabled": False}})

    print("\nSaved:")
    print(store.settings.model_dump())

    print("\nSchema:")
    # print(store.get_schema())
    print(json.dumps(store.get_schema(), indent=4))

    store.save()