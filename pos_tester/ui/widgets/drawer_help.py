"""금전함이 안 열릴 때 보여 주는 점검 순서 다이얼로그."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.tester import DRAWER_CHECKLIST
from ..tokens import SPACE
from .common import caption_label, make_button, title_label


class DrawerHelpDialog(QDialog):
    """번호 순서대로 확인하도록 만든 체크리스트."""

    def __init__(self, parent: QWidget | None = None, reason: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("금전함이 안 열릴 때")
        self.setModal(True)
        self.setMinimumWidth(640)

        root = QVBoxLayout(self)
        root.setContentsMargins(SPACE["2xl"], SPACE["xl"], SPACE["2xl"], SPACE["xl"])
        root.setSpacing(SPACE["md"])

        heading = title_label("금전함이 안 열릴 때 이 순서로 확인하세요")
        root.addWidget(_fixed(heading))
        if reason:
            root.addWidget(_fixed(caption_label(reason)))
        root.addSpacing(SPACE["xs"])

        for number, text in enumerate(DRAWER_CHECKLIST, start=1):
            root.addWidget(_fixed(_checklist_item(number, text)))

        root.addSpacing(SPACE["sm"])
        close_button = make_button("확인했습니다", variant="primary")
        close_button.clicked.connect(self.accept)
        root.addWidget(close_button)


def _fixed(widget: QWidget) -> QWidget:
    """세로로 늘어나지 않게 고정한다. 안 그러면 항목 사이에 빈 공간이 벌어진다."""
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return widget


def _checklist_item(number: int, text: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("ChecklistItem")

    layout = QHBoxLayout(frame)
    layout.setContentsMargins(SPACE["md"], SPACE["md"], SPACE["md"], SPACE["md"])
    layout.setSpacing(SPACE["md"])

    index = QLabel(str(number))
    index.setObjectName("ChecklistNumber")
    index.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

    body = QLabel(text)
    body.setWordWrap(True)

    layout.addWidget(index, 0)
    layout.addWidget(body, 1)
    return frame
