"""RAW 16진 전송 + 자주 쓰는 명령 프리셋."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from ...core.escpos import parse_hex
from ...core.tester import COMMAND_PRESETS
from ..tokens import SPACE, TOUCH
from .common import make_button, make_combo, section_label


class RawPanel(QWidget):
    """16진 문자열을 그대로 프린터에 보낸다. 디버깅용."""

    #: 검증을 통과한 바이트를 넘긴다.
    send_requested = Signal(bytes)
    #: 입력이 잘못됐을 때 로그에 남길 메시지.
    invalid_input = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SPACE["sm"])

        self.label = section_label("직접 명령")
        self.label.setToolTip("ESC/POS 명령을 16진수로 직접 보냅니다. 디버깅용입니다.")
        self.label.setFixedWidth(72)
        row.addWidget(self.label, 0)

        self.input = QLineEdit()
        self.input.setPlaceholderText("보낼 16진수 — 예: 1B 40")
        self.input.setClearButtonEnabled(True)
        self.input.setMinimumHeight(TOUCH["secondary-h"])

        self.preset_combo = make_combo(["프리셋 고르기…"] + [name for name, _ in COMMAND_PRESETS])
        self.preset_combo.setMinimumHeight(TOUCH["secondary-h"])
        self.preset_combo.setMaximumHeight(TOUCH["secondary-h"])
        self.preset_combo.setFixedWidth(210)

        self.send_button = make_button(
            "전송", icon="➤", min_height=TOUCH["secondary-h"], tooltip="입력한 바이트를 그대로 보냅니다"
        )
        self.send_button.setFixedWidth(108)

        row.addWidget(self.input, 1)
        row.addWidget(self.preset_combo, 0)
        row.addWidget(self.send_button, 0)

        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.send_button.clicked.connect(self._on_send)
        self.input.returnPressed.connect(self._on_send)

    def _on_preset_selected(self, index: int) -> None:
        if index <= 0:
            return
        _, hex_text = COMMAND_PRESETS[index - 1]
        self.input.setText(hex_text)
        self.preset_combo.setCurrentIndex(0)

    def _on_send(self) -> None:
        try:
            data = parse_hex(self.input.text())
        except ValueError as exc:
            self.invalid_input.emit(str(exc))
            return
        self.send_requested.emit(data)

    def text(self) -> str:
        return self.input.text()

    def set_text(self, value: str) -> None:
        self.input.setText(value)
