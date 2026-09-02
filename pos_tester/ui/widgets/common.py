"""여러 화면에서 공통으로 쓰는 위젯 조각."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..tokens import SPACE, TOUCH

ButtonVariant = Literal["default", "primary", "danger", "ghost", "link"]


def repolish(widget: QWidget) -> None:
    """동적 속성(variant, state, result …)을 바꾼 뒤 QSS 를 다시 적용한다."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value: object) -> None:
    """속성을 바꾸고 즉시 다시 칠한다."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    repolish(widget)


class Card(QFrame):
    """보더 + 은은한 그림자로 층위를 표현하는 카드.

    배경색만 바꾸면 평면적으로 보이므로 그림자를 함께 쓴다.
    """

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 90))
        self.setGraphicsEffect(shadow)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(SPACE["lg"], SPACE["md"], SPACE["lg"], SPACE["lg"])
        self._layout.setSpacing(SPACE["md"])

        self.title_label: QLabel | None = None
        if title:
            self.title_label = section_label(title)
            self._layout.addWidget(self.title_label)

    def body(self) -> QVBoxLayout:
        """카드 안쪽 레이아웃."""
        return self._layout


def section_label(text: str) -> QLabel:
    """카드 제목 등 섹션 헤더."""
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def caption_label(text: str = "", wrap: bool = True) -> QLabel:
    """보조 설명용 작은 글씨."""
    label = QLabel(text)
    label.setProperty("role", "caption")
    label.setWordWrap(wrap)
    return label


def title_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "title")
    return label


def make_button(
    text: str,
    variant: ButtonVariant = "default",
    icon: str = "",
    tooltip: str = "",
    min_height: int | None = None,
) -> QPushButton:
    """터치 기준을 만족하는 버튼을 만든다.

    아이콘만 있는 버튼은 만들지 않는다. 기사가 뜻을 헷갈리기 때문에
    아이콘은 항상 텍스트 앞에 붙는 장식으로만 쓴다.
    """
    label = f"{icon}  {text}" if icon else text
    button = QPushButton(label)
    button.setProperty("variant", variant)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        button.setToolTip(tooltip)

    if min_height is None:
        min_height = {
            "ghost": TOUCH["secondary-h"],
            "link": 0,
        }.get(variant, TOUCH["primary-h"])
    if min_height:
        button.setMinimumHeight(min_height)
    if variant == "link":
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return button


def make_combo(items: list[str] | None = None) -> QComboBox:
    """드롭다운 항목까지 터치 기준에 맞춘 콤보박스."""
    combo = QComboBox()
    combo.setMinimumHeight(TOUCH["combo-h"])
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    # 항목 높이는 QSS 로도 주지만, 뷰의 기본 높이를 함께 올려야 확실하다.
    view = combo.view()
    view.setSpacing(2)
    combo.setMaxVisibleItems(8)
    if items:
        combo.addItems(items)
    return combo


def horizontal_rule() -> QFrame:
    rule = QFrame()
    rule.setObjectName("Separator")
    rule.setFixedHeight(1)
    return rule


def form_row(label_text: str, field: QWidget, label_width: int = 44) -> QWidget:
    """'포트 [COM3 ▾]' 형태의 한 줄."""
    from PySide6.QtWidgets import QHBoxLayout

    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(SPACE["md"])

    label = QLabel(label_text)
    label.setFixedWidth(label_width)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setProperty("role", "value")

    layout.addWidget(label)
    layout.addWidget(field, 1)
    return row
