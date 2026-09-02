"""테스트 버튼 모음.

프린터 / 금전함 / 용지 세 묶음과 RAW 전송, 그리고 전체 테스트를 담는다.
결과가 오면 눌린 버튼 테두리를 잠시 초록·빨강으로 바꿔 로그를 보지 않아도
성공·실패를 알 수 있게 한다.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ...core.escpos import CutMode, DrawerPin
from ..tokens import SPACE
from .common import Card, caption_label, make_button, make_combo, section_label, set_prop
from .raw_panel import RawPanel

#: 결과 표시를 유지하는 시간(ms).
_FLASH_MS = 1600


class ActionPanel(Card):
    """점검 동작 버튼 카드."""

    connection_test_requested = Signal()
    print_test_requested = Signal()
    status_refresh_requested = Signal()
    initialize_requested = Signal()
    drawer_requested = Signal(object, bool)  # (DrawerPin, realtime)
    drawer_help_requested = Signal()
    cut_requested = Signal(object, int)  # (CutMode, feed_lines)
    feed_requested = Signal(int)
    raw_requested = Signal(bytes)
    raw_invalid = Signal(str)
    run_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        layout = self.body()
        # 1024x768 에 맞추기 위해 섹션 사이는 6px 로 좁히고,
        # 버튼끼리의 간격은 터치 기준 8px 를 그대로 지킨다.
        layout.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(SPACE["xs"])

        #: 작업 키 → 버튼. 결과가 오면 해당 버튼을 깜빡인다.
        self.buttons_by_key: dict[str, QPushButton] = {}
        self._flash_timers: dict[str, QTimer] = {}

        # -- 프린터 테스트 ------------------------------------------------
        layout.addLayout(_header_row("프린터 테스트"))
        self.connection_button = make_button("연결 테스트", icon="✓", tooltip="ESC @ 전송 후 상태 4종 조회")
        self.print_button = make_button("출력 테스트", icon="🖨", tooltip="한글·정렬·강조를 한 장에 인쇄")
        self.status_button = make_button("상태 새로고침", icon="↻")
        self.init_button = make_button("초기화", icon="⟲", tooltip="ESC @ 만 전송")
        layout.addLayout(
            _button_row([self.connection_button, self.print_button, self.status_button, self.init_button])
        )
        self._register("conn_test", self.connection_button)
        self._register("print", self.print_button)
        self._register("status", self.status_button)
        self._register("init", self.init_button)

        # -- 금전함 --------------------------------------------------------
        self.help_button = make_button("안 열려요?", variant="link")
        layout.addLayout(_header_row("금전함", trailing=self.help_button))
        self.pin2_button = make_button("2번 핀 열기", icon="💰", tooltip="ESC p 0 — 1B 70 00 19 FA")
        self.pin5_button = make_button("5번 핀 열기", icon="💰", tooltip="ESC p 1 — 1B 70 01 19 FA")
        self.realtime_button = make_button(
            "리얼타임 열기", icon="⚡", tooltip="DLE DC4 — 출력 버퍼를 무시하고 즉시 동작"
        )
        layout.addLayout(_button_row([self.pin2_button, self.pin5_button, self.realtime_button]))
        self._register("drawer_0", self.pin2_button)
        self._register("drawer_1", self.pin5_button)
        self._register("drawer_rt", self.realtime_button)

        # -- 용지 ----------------------------------------------------------
        self.feed_lines_combo = make_combo([f"{n}줄" for n in range(0, 11)])
        self.feed_lines_combo.setCurrentIndex(3)
        self.feed_lines_combo.setFixedWidth(96)
        self.feed_lines_combo.setFixedHeight(30)
        self.feed_lines_combo.setToolTip("절단 전에 밀어낼 줄 수. 너무 적으면 인쇄 내용이 잘립니다.")
        layout.addLayout(
            _header_row("용지 · 절단", trailing=self.feed_lines_combo, trailing_caption="절단 전 피드")
        )
        self.cut_full_button = make_button("전체 절단", icon="✂", tooltip="GS V 0 — 완전히 자릅니다")
        self.cut_partial_button = make_button("부분 절단", icon="✂", tooltip="GS V 1 — 한 점을 남기고 자릅니다")
        self.feed_cut_button = make_button(
            "피드 후 절단", icon="✂", tooltip="GS V B n — 설정한 줄 수만큼 밀어낸 뒤 자릅니다"
        )
        self.feed_button = make_button("피드만", icon="⇩", tooltip="ESC d n — 자르지 않고 밀어냅니다")
        layout.addLayout(
            _button_row(
                [self.cut_full_button, self.cut_partial_button, self.feed_cut_button, self.feed_button]
            )
        )
        self._register("cut_0_0", self.cut_full_button)
        self._register("cut_1_0", self.cut_partial_button)
        self._register("cut_feed", self.feed_cut_button)
        self._register("feed", self.feed_button)

        # -- RAW ------------------------------------------------------------
        # 섹션 헤더 없이 한 줄로 처리한다. 라벨은 RawPanel 안에 들어 있다.
        layout.addSpacing(2)
        self.raw_panel = RawPanel()
        layout.addWidget(self.raw_panel)
        self._register("raw", self.raw_panel.send_button)

        # -- 전체 테스트 ------------------------------------------------------
        # 위험한 동작이므로 다른 버튼과 간격을 넉넉히 띄워 오조작을 막는다.
        layout.addSpacing(SPACE["md"])
        self.run_all_button = make_button(
            "전체 테스트 순차 실행 (5단계)",
            variant="danger",
            icon="▶",
            tooltip="연결 → 출력 → 금전함 2번 → 금전함 5번 → 절단 순서로 모두 실행합니다",
        )
        layout.addWidget(self.run_all_button)
        self._register("run_all", self.run_all_button)

        self._connect_signals()

    # -- 배선 ---------------------------------------------------------------
    def _register(self, key: str, button: QPushButton) -> None:
        self.buttons_by_key[key] = button

    def _connect_signals(self) -> None:
        self.connection_button.clicked.connect(self.connection_test_requested)
        self.print_button.clicked.connect(self.print_test_requested)
        self.status_button.clicked.connect(self.status_refresh_requested)
        self.init_button.clicked.connect(self.initialize_requested)

        self.help_button.clicked.connect(self.drawer_help_requested)
        self.pin2_button.clicked.connect(lambda: self.drawer_requested.emit(DrawerPin.PIN_2, False))
        self.pin5_button.clicked.connect(lambda: self.drawer_requested.emit(DrawerPin.PIN_5, False))
        self.realtime_button.clicked.connect(
            lambda: self.drawer_requested.emit(DrawerPin.PIN_2, True)
        )

        self.cut_full_button.clicked.connect(lambda: self.cut_requested.emit(CutMode.FULL, 0))
        self.cut_partial_button.clicked.connect(lambda: self.cut_requested.emit(CutMode.PARTIAL, 0))
        self.feed_cut_button.clicked.connect(
            lambda: self.cut_requested.emit(CutMode.FULL, self.feed_lines)
        )
        self.feed_button.clicked.connect(lambda: self.feed_requested.emit(max(1, self.feed_lines)))

        self.raw_panel.send_requested.connect(self.raw_requested)
        self.raw_panel.invalid_input.connect(self.raw_invalid)
        self.run_all_button.clicked.connect(self.run_all_requested)

    # -- 상태 ---------------------------------------------------------------
    @property
    def feed_lines(self) -> int:
        return self.feed_lines_combo.currentIndex()

    def set_feed_lines(self, lines: int) -> None:
        if 0 <= lines <= 10:
            self.feed_lines_combo.setCurrentIndex(lines)

    def set_busy(self, busy: bool) -> None:
        """작업 중에는 모든 액션을 잠근다. 실수로 두 번 눌리는 것을 막는다."""
        for button in self.buttons_by_key.values():
            button.setEnabled(not busy)
        self.raw_panel.input.setEnabled(not busy)
        self.raw_panel.preset_combo.setEnabled(not busy)
        self.feed_lines_combo.setEnabled(not busy)
        self.help_button.setEnabled(True)  # 도움말은 언제든 볼 수 있어야 한다.

    def set_status_query_enabled(self, enabled: bool) -> None:
        """단방향 연결이면 상태 조회 버튼을 잠근다."""
        self.status_button.setEnabled(enabled)
        self.status_button.setToolTip(
            "" if enabled else "USB(단방향) 연결에서는 프린터 상태를 읽을 수 없습니다."
        )

    def flash_result(self, key: str, ok: bool, warning: bool = False) -> None:
        """결과를 버튼 테두리 색으로 잠깐 보여 준다.

        성공(초록) / 확인 필요(노랑) / 실패(빨강) 세 가지다.
        '확인 필요' 는 명령은 나갔지만 결과를 프로그램이 확인할 수 없는 경우로,
        실패로 몰면 멀쩡한 장비를 고장으로 오해하게 되므로 따로 구분한다.
        """
        button = self.buttons_by_key.get(key)
        if button is None:
            return
        state = "fail" if not ok else "warn" if warning else "ok"
        set_prop(button, "result", state)

        timer = self._flash_timers.get(key)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda k=key: self._clear_flash(k))
            self._flash_timers[key] = timer
        timer.start(_FLASH_MS)

    def _clear_flash(self, key: str) -> None:
        button = self.buttons_by_key.get(key)
        if button is not None:
            set_prop(button, "result", "")


def _header_row(
    title: str, trailing: QWidget | None = None, trailing_caption: str = ""
) -> QHBoxLayout:
    """섹션 제목 한 줄. 오른쪽에 작은 컨트롤을 붙일 수 있다."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 2, 0, 0)
    row.setSpacing(SPACE["sm"])
    row.addWidget(section_label(title))
    row.addStretch(1)
    if trailing_caption:
        row.addWidget(caption_label(trailing_caption, wrap=False))
    if trailing is not None:
        row.addWidget(trailing)
    return row


def _button_row(buttons: list[QPushButton]) -> QHBoxLayout:
    """버튼을 같은 너비로 나란히 놓는다. 간격은 터치 기준 8px."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(SPACE["sm"])
    for button in buttons:
        row.addWidget(button, 1)
    return row

