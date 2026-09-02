"""프린터 상태 램프 5종을 가로로 늘어놓은 띠.

DLE EOT 응답을 해석한 StatusReport 를 받아 사람이 읽는 한 줄로 보여 준다.
단방향(USB) 연결일 때는 전체를 흐리게 하고 이유를 함께 적는다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core.escpos import StatusKind, StatusReport
from ..tokens import SPACE
from .common import Card, caption_label, set_prop

#: (키, 화면 라벨) — 표시 순서 그대로다.
_ITEMS: list[tuple[str, str]] = [
    ("printer", "프린터"),
    ("cover", "커버"),
    ("paper", "용지"),
    ("cutter", "절단기"),
    ("drawer", "금전함"),
]

#: 각 램프를 어느 상태 조회의 어느 플래그에서 가져올지.
_SOURCES: dict[str, tuple[StatusKind, str]] = {
    "printer": (StatusKind.PRINTER, "프린터"),
    "cover": (StatusKind.PRINTER, "커버"),
    "paper": (StatusKind.PAPER_SENSOR, "용지"),
    "cutter": (StatusKind.ERROR_CAUSE, "절단기"),
    "drawer": (StatusKind.PRINTER, "금전함"),
}

_UNKNOWN = "—"


class _Lamp(QWidget):
    """램프 한 칸: 위에 항목 이름, 아래에 ● + 상태 문구."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.caption = caption_label(title, wrap=False)
        layout.addWidget(self.caption)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(SPACE["xs"] + 2)

        self.dot = QLabel("●")
        self.dot.setProperty("lamp", "idle")
        self.dot.setFixedWidth(14)
        self.value = QLabel(_UNKNOWN)
        self.value.setProperty("lamp", "idle")
        self.value.setStyleSheet("font-size: 15px; font-weight: 600;")

        value_row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        value_row.addWidget(self.value, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(value_row)

    def set_state(self, text: str, lamp: str) -> None:
        self.value.setText(text)
        set_prop(self.dot, "lamp", lamp)
        set_prop(self.value, "lamp", lamp)


class StatusPanel(Card):
    """상태 램프 띠."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        layout = self.body()
        layout.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        layout.setSpacing(SPACE["xs"])

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["lg"])

        self.lamps: dict[str, _Lamp] = {}
        for index, (key, title) in enumerate(_ITEMS):
            if index:
                row.addWidget(_divider())
            lamp = _Lamp(title)
            self.lamps[key] = lamp
            row.addWidget(lamp, 1)
        layout.addLayout(row)

        self.note = caption_label("")
        self.note.setVisible(False)
        layout.addWidget(self.note)

    # -- 갱신 -------------------------------------------------------------
    def clear(self, note: str = "") -> None:
        """모든 램프를 '알 수 없음'으로 되돌린다."""
        for lamp in self.lamps.values():
            lamp.set_state(_UNKNOWN, "idle")
        self.set_note(note)

    def set_note(self, note: str) -> None:
        self.note.setText(note)
        self.note.setVisible(bool(note))

    def set_unavailable(self, reason: str) -> None:
        """단방향 연결처럼 상태를 읽을 수 없을 때."""
        self.clear(reason)

    def update_from_reports(self, reports: list[StatusReport]) -> None:
        """상태 조회 결과로 램프를 갱신한다."""
        by_kind = {report.kind: report for report in reports}
        for key, (kind, flag_label) in _SOURCES.items():
            report = by_kind.get(kind)
            lamp = self.lamps[key]
            if report is None or not report.well_formed:
                lamp.set_state(_UNKNOWN, "idle")
                continue
            flag = next((f for f in report.flags if f.label == flag_label), None)
            if flag is None:
                lamp.set_state(_UNKNOWN, "idle")
                continue
            lamp.set_state(flag.detail, _lamp_level(key, flag.detail, flag.ok))
        self.set_note("")


def _lamp_level(key: str, detail: str, ok: bool) -> str:
    """램프 색을 고른다.

    금전함은 열림/닫힘 모두 정상이므로 오류 색을 쓰지 않고,
    열려 있을 때만 눈에 띄게 액센트가 아닌 경고 톤으로 구분한다.
    """
    if key == "drawer":
        return "warn" if detail == "열림" else "ok"
    if key == "paper" and detail == "거의 없음":
        return "warn"
    return "ok" if ok else "error"


def _divider() -> QFrame:
    """램프 칸 사이의 얇은 세로선."""
    line = QFrame()
    line.setObjectName("LampDivider")
    line.setFixedWidth(1)
    line.setMinimumHeight(34)
    return line
