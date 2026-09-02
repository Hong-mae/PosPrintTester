"""타임스탬프 + 색상 구분 로그."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.tester import LogLevel
from ..tokens import COLORS, SPACE
from .common import make_button, section_label

#: 레벨별 글자 색. 상태 색은 의미 전달용으로만 쓴다.
_LEVEL_COLORS: dict[str, str] = {
    "info": COLORS["text-dim"],
    "ok": COLORS["ok"],
    "warn": COLORS["warn"],
    "error": COLORS["error"],
}

_MAX_BLOCKS = 4000  # 오래 켜 둬도 메모리가 계속 늘지 않게 상한을 둔다.


class LogView(QWidget):
    """로그 출력 + 지우기 / 파일 저장."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACE["sm"])

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(SPACE["sm"])
        header.addWidget(section_label("로그"))
        header.addStretch(1)

        self.clear_button = make_button("지우기", variant="ghost", icon="🗑")
        self.save_button = make_button("파일로 저장", variant="ghost", icon="💾")
        self.clear_button.setFixedWidth(120)
        self.save_button.setFixedWidth(150)
        header.addWidget(self.clear_button)
        header.addWidget(self.save_button)
        root.addLayout(header)

        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(_MAX_BLOCKS)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        root.addWidget(self.view, 1)

        self.clear_button.clicked.connect(self.clear)
        self.save_button.clicked.connect(self.save_to_file)

    # -- 기록 -------------------------------------------------------------
    def append(self, level: LogLevel | str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        color = _LEVEL_COLORS.get(str(level), COLORS["text-dim"])

        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        stamp_format = QTextCharFormat()
        stamp_format.setForeground(QColor(COLORS["text-mute"]))
        cursor.insertText(f"{timestamp}  ", stamp_format)

        body_format = QTextCharFormat()
        body_format.setForeground(QColor(color))
        cursor.insertText(f"{message}\n", body_format)

        self.view.setTextCursor(cursor)
        self.view.ensureCursorVisible()

    def clear(self) -> None:
        self.view.clear()
        self.append("info", "로그를 지웠습니다.")

    def plain_text(self) -> str:
        return self.view.toPlainText()

    # -- 저장 -------------------------------------------------------------
    def save_to_file(self) -> None:
        default_name = f"POSTester_{datetime.now():%Y%m%d_%H%M%S}.txt"
        path_text, _ = QFileDialog.getSaveFileName(
            self, "로그 저장", str(Path.home() / default_name), "텍스트 파일 (*.txt)"
        )
        if not path_text:
            return
        try:
            Path(path_text).write_text(self.plain_text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "저장 실패", f"로그를 저장하지 못했습니다.\n\n{exc}")
            return
        self.append("ok", f"로그를 저장했습니다: {path_text}")
