"""디자인 토큰 — 색상·간격·타이포의 단일 출처.

theme.qss 는 {{token}} 형태의 자리표시자를 쓰고, load_stylesheet() 가
여기 값으로 치환한다. 색상 값이 파이썬과 QSS 두 곳에 흩어지지 않게 하려는 것이다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------
# 색상 — 채도 낮은 뉴트럴 + 액센트 1개. 원색은 쓰지 않는다.
# --------------------------------------------------------------------------
COLORS: Final[dict[str, str]] = {
    # 배경
    "bg-base": "#16181C",  # 앱 배경
    "bg-sunken": "#101215",  # 로그·입력 인셋
    "bg-card": "#1D2025",  # 카드 표면
    "bg-raised": "#24282E",  # 호버 / 드롭다운
    "bg-overlay": "#0B0D10",  # 모달 뒤 어둡게
    # 보더 — 배경색 대신 이걸로 층위를 만든다.
    "border": "#2E333A",
    "border-hi": "#3A4048",
    # 텍스트
    "text": "#E6E8EB",
    "text-dim": "#A8AEB8",
    "text-mute": "#6C7480",
    "text-disabled": "#4E555F",
    # 액센트 (뮤트 틸) — 화면 전체에서 이 계열 하나만 쓴다.
    "accent": "#4C9A8F",
    "accent-hover": "#59AFA3",
    "accent-press": "#3E8177",
    "accent-fg": "#0E1211",
    "accent-soft": "#20302F",  # 액센트 배경의 아주 옅은 버전
    # 상태 — 의미 전달용으로만 최소한 사용
    "ok": "#74A97C",
    "ok-soft": "#1E2A21",
    "warn": "#C39A55",
    "warn-soft": "#2B2419",
    "error": "#C4706A",
    "error-soft": "#2C1D1C",
    "idle": "#6C7480",
}

# --------------------------------------------------------------------------
# 간격 — 4px 배수 스케일
# --------------------------------------------------------------------------
SPACE: Final[dict[str, int]] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 20,
    "2xl": 24,
    "3xl": 32,
}

# --------------------------------------------------------------------------
# 타이포 — 제목 / 본문 / 캡션 3단계
# --------------------------------------------------------------------------
#: 윈도우에는 Malgun Gothic 이 항상 있으므로 폰트를 따로 넣지 않아도 한글이 깨지지 않는다.
#: 뒤쪽은 리눅스에서 개발·검증할 때 쓰는 대체 폰트다.
FONT_STACK: Final = (
    '"Malgun Gothic", "맑은 고딕", "Segoe UI", '
    '"Noto Sans KR", "NanumGothic", "나눔고딕", sans-serif'
)

#: QFont 로 직접 고를 때의 우선순위. 설치된 첫 번째를 쓴다.
FONT_CANDIDATES: Final[tuple[str, ...]] = (
    "Malgun Gothic",
    "맑은 고딕",
    "Noto Sans KR",
    "NanumGothic",
    "Segoe UI",
)

TYPE: Final[dict[str, int]] = {
    "title": 18,  # 상단 연결 상태
    "section": 14,  # 카드 섹션 헤더 (600 weight + letter-spacing)
    "body": 14,
    "button": 15,
    "caption": 12,
}

# --------------------------------------------------------------------------
# 터치 타깃 — 15" PCAP 터치 기준
# --------------------------------------------------------------------------
TOUCH: Final[dict[str, int]] = {
    "primary-h": 56,  # 주요 액션 버튼 최소 높이
    "secondary-h": 44,  # 보조 버튼
    "combo-h": 46,  # 콤보박스
    "combo-item-h": 44,  # 드롭다운 항목
    "gap": 8,  # 버튼 사이 최소 간격
    "radius": 8,
}

#: 설계 기준 해상도. 이 크기에서 스크롤 없이 모든 기능이 보여야 한다.
BASE_WIDTH: Final = 1024
BASE_HEIGHT: Final = 768

#: QSS 의 세로 padding / border 값. 아래 계산에 쓴다.
_PAD_V: Final[dict[str, int]] = {"button": 10, "ghost": 6, "combo": 8, "input": 8}
_BORDER: Final = 1

_PLACEHOLDER = re.compile(r"\{\{([a-z0-9\-]+)\}\}")


def _content_height(total: int, pad_key: str) -> int:
    """터치 타깃 전체 높이에서 padding·border 를 뺀 '내용 영역' 높이.

    Qt 스타일시트의 min-height 는 내용 영역 기준이므로, 이 값을 넣어야
    화면에 실제로 그려지는 높이가 의도한 터치 타깃 크기가 된다.
    """
    return max(0, total - 2 * _PAD_V[pad_key] - 2 * _BORDER)


def token_table() -> dict[str, str]:
    """QSS 치환에 쓸 이름 → 값 표. 색상·간격·타이포·터치를 한 곳에 모은다."""
    table: dict[str, str] = dict(COLORS)
    table.update({f"space-{k}": str(v) for k, v in SPACE.items()})
    table.update({f"font-{k}": str(v) for k, v in TYPE.items()})
    table.update({f"touch-{k}": str(v) for k, v in TOUCH.items()})
    # QSS 전용 — min-height 에 넣을 내용 영역 높이.
    table["qss-primary-h"] = str(_content_height(TOUCH["primary-h"], "button"))
    table["qss-secondary-h"] = str(_content_height(TOUCH["secondary-h"], "ghost"))
    table["qss-combo-h"] = str(_content_height(TOUCH["combo-h"], "combo"))
    table["qss-input-h"] = str(_content_height(TOUCH["secondary-h"], "input"))
    table["font-stack"] = FONT_STACK
    return table


def stylesheet_path() -> Path:
    """theme.qss 의 위치.

    소스로 실행할 때는 이 파일 옆에 있고, PyInstaller 로 묶였을 때는
    임시 해제 폴더(sys._MEIPASS) 아래 같은 상대 경로에 풀린다.
    """
    local = Path(__file__).with_name("theme.qss")
    if local.exists():
        return local
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "pos_tester" / "ui" / "theme.qss"
    return local


def load_stylesheet(path: Path | None = None) -> str:
    """theme.qss 를 읽어 {{token}} 을 실제 값으로 치환한다."""
    source = (path or stylesheet_path()).read_text(encoding="utf-8")
    return render_stylesheet(source)


def render_stylesheet(source: str) -> str:
    """자리표시자를 치환한다. 모르는 이름이 있으면 바로 알 수 있게 예외를 던진다."""
    table = token_table()
    missing: list[str] = []

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in table:
            missing.append(name)
            return match.group(0)
        return table[name]

    result = _PLACEHOLDER.sub(substitute, source)
    if missing:
        raise KeyError(f"theme.qss 에 정의되지 않은 토큰이 있습니다: {sorted(set(missing))}")
    return result
