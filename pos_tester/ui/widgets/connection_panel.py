"""연결 방식 선택 패널.

시리얼(COM) / USB(윈도우 스풀러) / 가상 프린터(Mock) 를 전환한다.
USB 는 단방향이라 속도·흐름 제어·상태 조회를 잠그고 그 이유를 화면에 적는다.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...config import AppConfig
from ...core.discovery import list_printers, list_serial_ports
from ...core.errors import PosTesterError
from ...core.transport import (
    BAUD_RATES,
    FlowControl,
    MockTransport,
    SerialSettings,
    SerialTransport,
    Transport,
    WinSpoolerTransport,
)
from ..tokens import SPACE, TOUCH
from .common import Card, caption_label, form_row, make_button, make_combo

Mode = Literal["serial", "spooler", "mock"]

_MODE_LABELS: list[tuple[Mode, str]] = [
    ("serial", "시리얼 (COM 포트)"),
    ("spooler", "USB (윈도우 프린터)"),
    ("mock", "가상 프린터 (연습용)"),
]

_SPOOLER_NOTE = (
    "USB 연결은 프린터로 보내기만 할 수 있어 상태를 읽지 못합니다. "
    "상태 확인이 필요하면 시리얼을 쓰세요."
)
_MOCK_NOTE = "실제 장비 없이 화면과 순서를 익힐 수 있는 연습 모드입니다."
_SERIAL_NOTE = "속도를 모르면 '통신 속도 자동 찾기'를 누르세요."

#: COM 포트가 하나도 없을 때. USB 로 물린 POS 프린터는 제조사 VirtualCOM 드라이버를
#: 설치해야 COM 포트로 잡힌다(세우테크 SLK-TS100 등). 이걸 모르면 한참 헤맨다.
_NO_PORT_NOTE = (
    "COM 포트가 하나도 없습니다. 9핀 케이블이면 장치 관리자 > 포트(COM & LPT) 에 "
    "포트가 보이는지, BIOS 에서 시리얼 포트가 켜져 있는지 확인하세요. "
    "USB 케이블이면 제조사 VirtualCOM 드라이버를 설치하거나 방식을 "
    "'USB (윈도우 프린터)' 로 바꾸세요."
)
_NO_PRINTER_NOTE = (
    "설치된 프린터가 없습니다. 제어판 > 장치 및 프린터에서 프린터가 보이는지 "
    "먼저 확인하세요. LAN 으로 연결된 프린터는 이 프로그램이 지원하지 않습니다."
)


class ConnectionPanel(Card):
    """연결 설정 카드."""

    #: 사용자가 '연결'을 눌렀다. 만들어진 Transport 를 함께 넘긴다.
    connect_requested = Signal(object)
    #: 사용자가 '연결 끊기'를 눌렀다.
    disconnect_requested = Signal()
    #: (포트, 흐름 제어) 로 속도 자동 탐색을 요청했다.
    scan_requested = Signal(str, object)
    #: 연결 방식이 바뀌었다. 상태 패널을 잠그거나 풀 때 쓴다.
    mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("연결", parent)
        self._connected = False
        #: 목록 조회가 실패했을 때의 이유. 비어 있으면 성공.
        self._list_error = ""
        #: 조회는 됐는데 결과가 하나도 없는 상태.
        self._list_empty = False
        layout = self.body()
        layout.setContentsMargins(SPACE["lg"], SPACE["sm"], SPACE["lg"], SPACE["md"])
        layout.setSpacing(SPACE["xs"])

        self.mode_combo = make_combo([label for _, label in _MODE_LABELS])
        layout.addWidget(form_row("방식", self.mode_combo))

        # 포트/프린터 선택 + 새로고침
        target_row = QWidget()
        target_layout = QHBoxLayout(target_row)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.setSpacing(SPACE["sm"])
        self.target_combo = make_combo()
        self.refresh_button = make_button(
            "↻", variant="ghost", tooltip="포트/프린터 목록 다시 읽기", min_height=TOUCH["combo-h"]
        )
        self.refresh_button.setFixedWidth(48)
        target_layout.addWidget(self.target_combo, 1)
        target_layout.addWidget(self.refresh_button)
        self.target_row_widget = form_row("포트", target_row)
        self.target_label: QLabel = self.target_row_widget.findChild(QLabel)  # type: ignore[assignment]
        layout.addWidget(self.target_row_widget)

        self.baud_combo = make_combo([str(b) for b in BAUD_RATES])
        self.baud_row = form_row("속도", self.baud_combo)
        layout.addWidget(self.baud_row)

        self.flow_combo = make_combo([f.value for f in FlowControl])
        self.flow_row = form_row("흐름", self.flow_combo)
        layout.addWidget(self.flow_row)

        self.note = caption_label(_SERIAL_NOTE)
        layout.addWidget(self.note)
        # 창을 키웠을 때 늘어난 공간이 폼과 버튼 사이에 모이게 해서
        # 버튼 높이(터치 타깃)가 흐트러지지 않게 한다.
        layout.addStretch(1)

        self.scan_button = make_button(
            "통신 속도 자동 찾기",
            icon="🔎",
            tooltip="9600부터 115200까지 차례로 시도해 응답하는 속도를 찾습니다",
        )
        layout.addWidget(self.scan_button)

        self.connect_button = make_button("연결", variant="primary", icon="🔌")
        layout.addWidget(self.connect_button)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.refresh_button.clicked.connect(self.refresh_targets)
        self.scan_button.clicked.connect(self._on_scan_clicked)
        self.connect_button.clicked.connect(self._on_connect_clicked)

        self.refresh_targets()
        self._apply_mode_visibility()

    # -- 상태 조회 ---------------------------------------------------------
    @property
    def mode(self) -> Mode:
        return _MODE_LABELS[self.mode_combo.currentIndex()][0]

    @property
    def flow(self) -> FlowControl:
        return list(FlowControl)[self.flow_combo.currentIndex()]

    @property
    def baudrate(self) -> int:
        try:
            return int(self.baud_combo.currentText())
        except ValueError:
            return 38400

    @property
    def target(self) -> str:
        """선택된 COM 포트 이름 또는 프린터 이름."""
        return str(self.target_combo.currentData() or "")

    def set_connected(self, connected: bool) -> None:
        """연결 상태에 따라 버튼 라벨과 잠금을 바꾼다."""
        self._connected = connected
        self.connect_button.setText("🔌  연결 끊기" if connected else "🔌  연결")
        self.connect_button.setProperty("variant", "default" if connected else "primary")
        from .common import repolish

        repolish(self.connect_button)
        for widget in (self.mode_combo, self.target_combo, self.refresh_button, self.scan_button):
            widget.setEnabled(not connected)
        serial_mode = self.mode == "serial"
        self.baud_combo.setEnabled(not connected and serial_mode)
        self.flow_combo.setEnabled(not connected and serial_mode)

    # -- 목록 갱신 ---------------------------------------------------------
    def refresh_targets(self) -> None:
        """모드에 맞춰 포트 또는 프린터 목록을 다시 읽는다.

        조회에 실패하면 그 이유를 화면에 남긴다. 목록이 비어 있을 때
        '장비가 없는 것' 인지 '조회를 못 한 것' 인지 구분되어야 한다.
        """
        previous = self.target
        self.target_combo.clear()
        self._list_error = ""
        self._list_empty = False

        if self.mode == "mock":
            self.target_combo.addItem("가상 프린터", "mock")
        elif self.mode == "spooler":
            try:
                printers = list_printers()
            except PosTesterError as exc:
                printers = []
                self._list_error = exc.message
            for printer in printers:
                self.target_combo.addItem(printer.label, printer.name)
            if not printers:
                self._list_empty = True
                self.target_combo.addItem("설치된 프린터 없음", "")
        else:
            try:
                ports = list_serial_ports()
            except PosTesterError as exc:
                ports = []
                self._list_error = exc.message
            for port in ports:
                self.target_combo.addItem(port.label, port.device)
                self.target_combo.setItemData(
                    self.target_combo.count() - 1, port.label, Qt.ItemDataRole.ToolTipRole
                )
            if not ports:
                self._list_empty = True
                self.target_combo.addItem("COM 포트 없음", "")

        if previous:
            index = self.target_combo.findData(previous)
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
        self._update_note()

    # -- 이벤트 -----------------------------------------------------------
    def _on_mode_changed(self) -> None:
        self.refresh_targets()
        self._apply_mode_visibility()
        self.mode_changed.emit(self.mode)

    def _apply_mode_visibility(self) -> None:
        mode = self.mode
        serial = mode == "serial"
        self.baud_combo.setEnabled(serial)
        self.flow_combo.setEnabled(serial)
        self.scan_button.setEnabled(serial)
        self.target_label.setText("포트" if serial else "프린터" if mode == "spooler" else "대상")
        self._update_note()

    def _update_note(self) -> None:
        """방식과 목록 상태에 맞는 안내문을 고른다.

        조회 실패 > 목록 비어 있음 > 방식별 기본 안내 순으로 우선한다.
        """
        if self._list_error:
            self.note.setText(self._list_error)
            return
        mode = self.mode
        if self._list_empty:
            self.note.setText(_NO_PORT_NOTE if mode == "serial" else _NO_PRINTER_NOTE)
            return
        self.note.setText(
            _SERIAL_NOTE if mode == "serial" else _SPOOLER_NOTE if mode == "spooler" else _MOCK_NOTE
        )

    def _on_scan_clicked(self) -> None:
        if not self.target:
            return
        self.scan_requested.emit(self.target, self.flow)

    def _on_connect_clicked(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
            return
        transport = self.build_transport()
        if transport is not None:
            self.connect_requested.emit(transport)

    def build_transport(self) -> Transport | None:
        """현재 선택으로 Transport 를 만든다. 대상이 없으면 None."""
        mode = self.mode
        if mode == "mock":
            return MockTransport(latency=0.05)
        target = self.target
        if not target:
            return None
        if mode == "spooler":
            return WinSpoolerTransport(target)
        return SerialTransport(
            SerialSettings(port=target, baudrate=self.baudrate, flow=self.flow)
        )

    # -- 설정 저장/복원 -----------------------------------------------------
    def apply_config(self, config: AppConfig) -> None:
        for index, (mode, _) in enumerate(_MODE_LABELS):
            if mode == config.mode:
                self.mode_combo.setCurrentIndex(index)
                break
        self.refresh_targets()

        wanted = config.printer_name if config.mode == "spooler" else config.port
        if wanted:
            index = self.target_combo.findData(wanted)
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
            else:
                # 지난번에 쓰던 포트가 지금은 안 보여도 고를 수 있게 남겨 둔다.
                self.target_combo.addItem(f"{wanted} (지금은 연결 안 됨)", wanted)
                self.target_combo.setCurrentIndex(self.target_combo.count() - 1)

        baud_index = self.baud_combo.findText(str(config.baudrate))
        if baud_index >= 0:
            self.baud_combo.setCurrentIndex(baud_index)
        try:
            self.flow_combo.setCurrentIndex(list(FlowControl).index(FlowControl[config.flow]))
        except (KeyError, ValueError):
            self.flow_combo.setCurrentIndex(0)
        self._apply_mode_visibility()

    def write_config(self, config: AppConfig) -> None:
        config.mode = self.mode
        config.baudrate = self.baudrate
        config.flow = self.flow.name
        if self.mode == "spooler":
            config.printer_name = self.target
        elif self.mode == "serial":
            config.port = self.target

    def select_baudrate(self, baudrate: int) -> None:
        """자동 탐색이 찾은 속도를 콤보에 반영한다."""
        index = self.baud_combo.findText(str(baudrate))
        if index >= 0:
            self.baud_combo.setCurrentIndex(index)
