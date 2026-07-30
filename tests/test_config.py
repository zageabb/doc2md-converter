import json
from pathlib import Path

import pytest

from doc2md_watcher.config import ConfigError, StartupConfig
from doc2md_watcher import cli


def test_config_round_trip_uses_absolute_folder_paths(tmp_path: Path) -> None:
    watched = tmp_path / "watched"
    config_path = tmp_path / "config.json"
    original = StartupConfig(
        folders=[watched],
        initial=True,
        settle_seconds=1.5,
        gui=True,
        verbose=False,
    )
    original.save(config_path)

    loaded = StartupConfig.load(config_path)
    assert loaded == original


def test_relative_folders_resolve_from_config_location(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"folders": ["incoming"], "gui": True}),
        encoding="utf-8",
    )

    loaded = StartupConfig.load(config_path)
    assert loaded.folders == [(tmp_path / "incoming").resolve()]


def test_invalid_config_has_clear_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"folders": "not-a-list"}', encoding="utf-8")

    with pytest.raises(ConfigError, match="folders"):
        StartupConfig.load(config_path)


def test_cli_is_saved_when_config_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    watched = tmp_path / "watched"
    captured = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "watch",
        lambda folders, settle, initial: captured.update(
            folders=folders, settle=settle, initial=initial
        ),
    )

    assert cli.main(["--initial", "--settle-seconds", "2", str(watched)]) == 0
    saved = StartupConfig.load(tmp_path / "config.json")
    assert saved.folders == [watched]
    assert captured == {"folders": [watched], "settle": 2.0, "initial": True}


def test_existing_config_takes_precedence_over_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    supplied = tmp_path / "supplied"
    StartupConfig(folders=[configured], settle_seconds=3.0).save(tmp_path / "config.json")
    captured = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "watch",
        lambda folders, settle, initial: captured.update(
            folders=folders, settle=settle, initial=initial
        ),
    )

    assert cli.main(["--initial", str(supplied)]) == 0
    assert captured == {"folders": [configured], "settle": 3.0, "initial": False}
