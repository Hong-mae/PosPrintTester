"""설정 저장/복원 검증."""

from __future__ import annotations

from pathlib import Path

from pos_tester.config import AppConfig, load_config, save_config


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig(mode="mock", port="COM5", baudrate=115200, flow="RTS_CTS")
    assert save_config(config, path)
    assert load_config(path) == config


def test_missing_file_returns_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "nope.json") == AppConfig()


def test_corrupt_file_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"port": "COM7", "누가봐도이상한키": 1}', encoding="utf-8")
    assert load_config(path).port == "COM7"


def test_wrong_type_falls_back_to_default(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"baudrate": "빠르게"}', encoding="utf-8")
    assert load_config(path).baudrate == AppConfig().baudrate


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(AppConfig(), path)
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]
