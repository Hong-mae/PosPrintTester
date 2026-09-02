"""마지막 연결 설정 저장/복원.

Windows 에서는 %APPDATA%\\POSTester\\config.json 에 저장한다.
설정 파일이 깨졌거나 없어도 절대 예외를 밖으로 내지 않고 기본값으로 돌아간다.
설정 하나 때문에 프로그램이 안 뜨는 상황이 현장에서 제일 곤란하기 때문이다.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Final

APP_NAME: Final = "POSTester"
CONFIG_FILENAME: Final = "config.json"


@dataclass
class AppConfig:
    """다음 실행 때 복원할 설정."""

    #: "serial" | "spooler" | "mock"
    mode: str = "serial"
    port: str = ""
    baudrate: int = 38400
    #: FlowControl 의 이름. "NONE" | "RTS_CTS" | "DTR_DSR"
    flow: str = "NONE"
    printer_name: str = ""
    #: 절단 전 피드 줄 수.
    cut_feed_lines: int = 3
    #: 마지막으로 보낸 RAW 16진 문자열.
    last_raw: str = "1B 40"
    fullscreen: bool = False


def config_dir() -> Path:
    """설정 디렉터리 경로. 없으면 만든다."""
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def load_config(path: Path | None = None) -> AppConfig:
    """설정을 읽는다. 실패하면 기본값을 돌려준다."""
    target = path or config_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppConfig()
    if not isinstance(raw, dict):
        return AppConfig()

    known = {f.name: f for f in fields(AppConfig)}
    values: dict[str, Any] = {}
    for name, field_def in known.items():
        if name not in raw:
            continue
        value = raw[name]
        # 타입이 어긋나는 값은 조용히 버리고 기본값을 쓴다.
        if field_def.type in ("int", int) and isinstance(value, bool):
            continue
        try:
            values[name] = {"str": str, "int": int, "bool": bool}[str(field_def.type)](value)
        except (KeyError, TypeError, ValueError):
            continue
    return AppConfig(**values)


def save_config(config: AppConfig, path: Path | None = None) -> bool:
    """설정을 저장한다. 성공 여부를 돌려주며 예외는 던지지 않는다.

    쓰다가 중단돼도 기존 파일이 깨지지 않도록 임시 파일에 쓴 뒤 교체한다.
    """
    target = path or config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp"
        ) as handle:
            json.dump(asdict(config), handle, ensure_ascii=False, indent=2)
            temp_name = handle.name
        os.replace(temp_name, target)
        return True
    except OSError:
        return False
