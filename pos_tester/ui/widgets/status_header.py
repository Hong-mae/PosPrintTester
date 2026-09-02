"""화면 맨 위의 연결 상태 바.

연결 여부와 대상 이름을 항상 크게 보여주고, 작업 중에는 진행 표시로 바뀐다.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..tokens import SPACE
from .common import make_button, set_prop

State = Literal["connected", "disconnected", "busy", "error"]


class StatusHeader(QFrame):
    """연결 상태 + 진행 표시를 담당하는 상단 바."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusHeader")
        self.setFixedHeight(64)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)

        root = QHBoxLayout(self)
        root.setContentsMargins(SPACE["xl"], SPACE["sm"], SPACE["lg"], SPACE["sm"])
        root.setSpacing(SPACE["lg"])

        self.dot = QLabel()
        self.dot.setObjectName("StatusDot")
        self.dot.setFixedSize(16, 16)
        root.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        self.title = QLabel("연결 안 됨")
        self.title.setObjectName("StatusTitle")
        self.target = QLabel("연결 방식을 고르고 '연결'을 누르세요")
        self.target.setObjectName("StatusTarget")

        text_column.addWidget(self.title)
        text_column.addWidget(self.target)
        root.addLayout(text_column, 1)

        # 작업 중에만 보이는 진행 표시.
        progress_column = QVBoxLayout()
        progress_column.setContentsMargins(0, 0, 0, 0)
        progress_column.setSpacing(SPACE["xs"])
        self.progress_label = QLabel("")
        self.progress_label.setProperty("role", "caption")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedSize(220, 8)
        self.progress_bar.setTextVisible(False)
        progress_column.addWidget(self.progress_label)
        progress_column.addWidget(self.progress_bar)

        self.progress_holder = QWidget()
        self.progress_holder.setLayout(progress_column)
        self.progress_holder.setVisible(False)
        root.addWidget(self.progress_holder, 0, Qt.AlignmentFlag.AlignVCenter)

        self.fullscreen_button: QPushButton = make_button(
            "전체화면", variant="ghost", icon="⛶", tooltip="F11 키로도 전환할 수 있습니다"
        )
        self.fullscreen_button.setFixedWidth(132)
        root.addWidget(self.fullscreen_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self._apply_state("disconnected")

    # -- 상태 -------------------------------------------------------------
    def set_connected(self, name: str) -> None:
        self.title.setText("연결됨")
        self.target.setText(name)
        self._apply_state("connected")

    def set_disconnected(self, reason: str = "연결 방식을 고르고 '연결'을 누르세요") -> None:
        self.title.setText("연결 안 됨")
        self.target.setText(reason)
        self._apply_state("disconnected")

    def set_error(self, message: str) -> None:
        self.title.setText("연결 실패")
        self.target.setText(message)
        self._apply_state("error")

    def _apply_state(self, state: State) -> None:
        set_prop(self.title, "state", state)
        set_prop(self.dot, "state", state)

    # -- 진행 표시 ---------------------------------------------------------
    def show_progress(self, text: str, value: int = 0, maximum: int = 0) -> None:
        """maximum 이 0 이면 진행률을 알 수 없는 애니메이션으로 표시한다."""
        self.progress_label.setText(text)
        self.progress_bar.setRange(0, maximum)
        self.progress_bar.setValue(value)
        self.progress_holder.setVisible(True)

    def hide_progress(self) -> None:
        self.progress_holder.setVisible(False)
        self.progress_label.setText("")
