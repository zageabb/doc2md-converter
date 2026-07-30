from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

CONFIG_NAME = "config.json"


class ConfigError(ValueError):
    pass


@dataclass
class StartupConfig:
    folders: list[Path]
    initial: bool = False
    settle_seconds: float = 1.0
    gui: bool = False
    verbose: bool = False

    @classmethod
    def load(cls, path: Path) -> "StartupConfig":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid JSON in {path}: {exc}") from exc
        except OSError as exc:
            raise ConfigError(f"could not read {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must contain a JSON object")

        folders = data.get("folders")
        if not isinstance(folders, list) or not all(isinstance(item, str) for item in folders):
            raise ConfigError(f"{path}: 'folders' must be a list of paths")
        base = path.parent.resolve()
        resolved_folders: list[Path] = []
        for item in folders:
            candidate = Path(item).expanduser()
            if not candidate.is_absolute():
                candidate = base / candidate
            resolved_folders.append(candidate.resolve())
        settle_seconds = data.get("settle_seconds", 1.0)
        if not isinstance(settle_seconds, (int, float)) or settle_seconds < 0:
            raise ConfigError(f"{path}: 'settle_seconds' must be zero or greater")

        return cls(
            folders=resolved_folders,
            initial=_boolean(data, "initial", False, path),
            settle_seconds=float(settle_seconds),
            gui=_boolean(data, "gui", False, path),
            verbose=_boolean(data, "verbose", False, path),
        )

    def save(self, path: Path) -> None:
        data: dict[str, Any] = asdict(self)
        data["folders"] = [str(folder.expanduser().resolve()) for folder in self.folders]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)


def _boolean(data: dict[str, Any], key: str, default: bool, path: Path) -> bool:
    value = data.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{path}: '{key}' must be true or false")
    return value
