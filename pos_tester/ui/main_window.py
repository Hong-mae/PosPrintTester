"""메인 창.

1024 x 768 에서 스크롤 없이 모든 기능이 보이도록 세로 예산을 나눈다.

    바깥 여백      10 x 2
    상단 상태 바   64
    상태 램프 띠   74   (상태를 못 읽는 이유를 적을 한 줄을 미리 비워 둔다)
    본문(연결 / 테스트)  내용 높이만큼 (약 415)
    로그           나머지 (최소 150)

본문은 내용 높이 그대로 두고 남는 세로 공간은 전부 로그가 가져간다.
창을 키우면 로그만 늘어나므로 버튼 위치가 흔들리지 않는다.
이 값을 바꾸면 1024x768 에서 잘리는지 반드시 다시 확인할 것.

UI 스레드에서는 어떤 I/O 도 하지 않는다. 모든 작업은 PrinterWorker 로 넘긴다.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig, config_path, load_config, save_config
from ..core.escpos import CutMode, DrawerPin, StatusKind, to_hex
from ..core.tester import StepResult
from ..core.transport import Transport
from . import worker as jobs
from .tokens import BASE_HEIGHT, BASE_WIDTH, SPACE, load_stylesheet
from .widgets.action_panel import ActionPanel
from .widgets.connection_panel import ConnectionPanel
from .widgets.drawer_help import DrawerHelpDialog
from .widgets.log_view import LogView
from .widgets.status_header import StatusHeader
from .widgets.status_panel import StatusPanel
from .worker import JobOutcome, WorkerThread

_LEFT_WIDTH = 336
_LOG_MIN_HEIGHT = 150
_STRIP_HEIGHT = 74


class MainWindow(QMainWindow):
    """POSTester 메인 창."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("POSTester — POS 프린터 · 금전함 점검")
        self.resize(BASE_WIDTH, BASE_HEIGHT)
        # 설계 기준 해상도보다 작아지면 버튼이 잘리므로 그 아래로는 줄이지 않는다.
        self.setMinimumSize(BASE_WIDTH, BASE_HEIGHT)

        self.config: AppConfig = load_config()
        self.worker_thread = WorkerThread()
        self.worker = self.worker_thread.worker
        self._supports_read = False

        self._build_ui()
        self._connect_signals()
        self._apply_config()

        self.log_view.append("info", "POSTester 를 시작했습니다.")
        self.log_view.append("info", f"설정 파일: {config_path()}")
        self.log_view.append(
            "info", "실제 장비가 없으면 방식을 '가상 프린터 (연습용)' 으로 두고 시험해 보세요."
        )

    # -- 화면 구성 ---------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(SPACE["sm"] + 2, SPACE["sm"] + 2, SPACE["sm"] + 2, SPACE["sm"] + 2)
        root.setSpacing(SPACE["sm"])

        self.header = StatusHeader()
        root.addWidget(self.header)

        self.status_panel = StatusPanel()
        self.status_panel.setFixedHeight(_STRIP_HEIGHT)
        root.addWidget(self.status_panel)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SPACE["md"])

        self.connection_panel = ConnectionPanel()
        self.connection_panel.setFixedWidth(_LEFT_WIDTH)
        body.addWidget(self.connection_panel, 0)

        self.action_panel = ActionPanel()
        body.addWidget(self.action_panel, 1)
        root.addLayout(body, 0)

        self.log_view = LogView()
        self.log_view.setMinimumHeight(_LOG_MIN_HEIGHT)
        root.addWidget(self.log_view, 1)

        self.setCentralWidget(central)

        shortcut = QShortcut(QKeySequence(Qt.Key.Key_F11), self)
        shortcut.activated.connect(self.toggle_fullscreen)

    def _connect_signals(self) -> None:
        panel = self.connection_panel
        panel.connect_requested.connect(self._on_connect_requested)
        panel.disconnect_requested.connect(lambda: self.worker.submit(jobs.job_disconnect()))
        panel.scan_requested.connect(
            lambda port, flow: self.worker.submit(jobs.job_scan_baud(port, flow))
        )
        panel.mode_changed.connect(self._on_mode_changed)

        actions = self.action_panel
        actions.connection_test_requested.connect(lambda: self.worker.submit(jobs.job_connection_test()))
        actions.status_refresh_requested.connect(lambda: self.worker.submit(jobs.job_read_status()))
        actions.initialize_requested.connect(lambda: self.worker.submit(jobs.job_initialize()))
        actions.print_test_requested.connect(self._on_print_test)
        actions.drawer_requested.connect(self._on_drawer)
        actions.drawer_help_requested.connect(lambda: self.show_drawer_help())
        actions.cut_requested.connect(self._on_cut)
        actions.feed_requested.connect(lambda lines: self.worker.submit(jobs.job_feed(lines)))
        actions.raw_requested.connect(self._on_raw)
        actions.raw_invalid.connect(lambda message: self.log_view.append("error", message))
        actions.run_all_requested.connect(self._on_run_all)

        self.header.fullscreen_button.clicked.connect(self.toggle_fullscreen)

        self.worker.log.connect(self.log_view.append)
        self.worker.progress.connect(self._on_progress)
        self.worker.job_done.connect(self._on_job_done)
        self.worker.connection_changed.connect(self._on_connection_changed)
        self.worker.idle.connect(self._on_idle)

    def _apply_config(self) -> None:
        self.connection_panel.apply_config(self.config)
        self.action_panel.set_feed_lines(self.config.cut_feed_lines)
        self.action_panel.raw_panel.set_text(self.config.last_raw)
        self._set_connected_ui(False)
        if self.config.fullscreen:
            self.showFullScreen()

    # -- 사용자 동작 -------------------------------------------------------
    def _on_connect_requested(self, transport: Transport) -> None:
        self.worker.submit(jobs.job_connect(transport))

    def _on_mode_changed(self, mode: str) -> None:
        if mode == "spooler":
            self.status_panel.set_unavailable(
                "USB(윈도우 프린터) 연결은 보내기만 가능해 상태를 읽을 수 없습니다. "
                "상태 확인이 필요하면 시리얼로 연결하세요."
            )
            self.action_panel.set_status_query_enabled(False)
        else:
            self.status_panel.clear()
            self.action_panel.set_status_query_enabled(True)

    def _on_print_test(self) -> None:
        lines = self.action_panel.feed_lines
        self.worker.submit(jobs.job_print_test(cut_after=lines > 0, feed_lines=max(lines, 1)))

    def _on_drawer(self, pin: DrawerPin, realtime: bool) -> None:
        self.worker.submit(jobs.job_drawer(pin, realtime))

    def _on_cut(self, mode: CutMode, feed_lines: int) -> None:
        job = jobs.job_cut(mode, feed_lines)
        # 피드 후 절단 버튼은 줄 수가 바뀌어도 같은 버튼에 결과를 되돌려야 한다.
        if feed_lines:
            job.key = "cut_feed"
        self.worker.submit(job)

    def _on_raw(self, data: bytes) -> None:
        self.log_view.append("info", f"RAW 전송 준비: {to_hex(data)}")
        self.worker.submit(jobs.job_send_raw(data))

    def _on_run_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "전체 테스트",
            "연결 → 출력 → 금전함 2번 핀 → 금전함 5번 핀 → 용지 절단 순서로 실행합니다.\n\n"
            "금전함이 두 번 열리고 용지가 잘립니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.log_view.append("info", "전체 테스트를 취소했습니다.")
            return
        self.worker.submit(jobs.job_run_all())

    def show_drawer_help(self, reason: str = "") -> None:
        DrawerHelpDialog(self, reason).exec()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.config.fullscreen = self.isFullScreen()

    # -- 워커 응답 ---------------------------------------------------------
    def _on_progress(self, text: str, value: int, maximum: int) -> None:
        self.header.show_progress(text, value, maximum)
        self.action_panel.set_busy(True)
        self.connection_panel.connect_button.setEnabled(False)

    def _on_idle(self) -> None:
        self.header.hide_progress()
        self.action_panel.set_busy(False)
        self.action_panel.set_status_query_enabled(self._supports_read)
        self.connection_panel.connect_button.setEnabled(True)

    def _on_connection_changed(self, connected: bool, name: str, supports_read: bool) -> None:
        self._supports_read = supports_read
        self._set_connected_ui(connected, name, supports_read)

    def _set_connected_ui(self, connected: bool, name: str = "", supports_read: bool = False) -> None:
        self.connection_panel.set_connected(connected)
        self.action_panel.set_status_query_enabled(connected and supports_read)
        if connected:
            self.header.set_connected(name)
            if not supports_read:
                self.status_panel.set_unavailable(
                    "단방향 연결이라 상태를 읽을 수 없습니다. 인쇄물을 눈으로 확인하세요."
                )
            else:
                self.status_panel.clear("‘상태 새로고침’ 을 누르면 현재 상태를 읽어옵니다.")
        else:
            self.header.set_disconnected()
            self.status_panel.clear()

    def _on_job_done(self, key: str, outcome: JobOutcome) -> None:
        self.action_panel.flash_result(key, outcome.ok, outcome.warning)

        if key == "connect" and not outcome.ok:
            self.header.set_error(outcome.detail)
        if key == "scan":
            self._handle_scan_result(outcome)
        if outcome.payload is not None:
            self._update_status_lamps(outcome.payload)
        if key.startswith("drawer") and not outcome.ok:
            # 명령 자체가 실패했을 때만 체크리스트를 띄운다.
            # '열림 감지 안 됨' 은 센서 없는 금전함에서 정상적으로 나오는 상태라
            # 팝업 없이 노란색 표시와 로그로만 알린다.
            self.show_drawer_help(outcome.detail)

    def _handle_scan_result(self, outcome: JobOutcome) -> None:
        result = outcome.payload
        if result is not None and getattr(result, "found", False):
            self.connection_panel.select_baudrate(result.baudrate)
            self.log_view.append(
                "ok", f"속도를 {result.baudrate} bps 로 맞췄습니다. 이제 '연결'을 누르세요."
            )
        else:
            self.log_view.append(
                "warn",
                "모든 속도에서 응답이 없었습니다. 포트 번호, 케이블 종류(크로스 여부), "
                "흐름 제어 설정을 확인하세요.",
            )

    def _update_status_lamps(self, payload: Any) -> None:
        """작업 결과에 상태 조회가 섞여 있으면 램프를 갱신한다."""
        reports = []
        if isinstance(payload, StepResult):
            reports = payload.reports
        elif isinstance(payload, list) and payload and isinstance(payload[0], StepResult):
            for step in payload:
                if step.reports:
                    reports = step.reports
        if not reports:
            return
        # 금전함 킥 결과처럼 프린터 상태 하나만 온 경우도 그 항목만 갱신한다.
        if len(reports) == 1 and reports[0].kind is StatusKind.PRINTER:
            self.status_panel.update_from_reports(reports)
            return
        self.status_panel.update_from_reports(reports)

    # -- 종료 --------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_config()
        self.worker_thread.stop()
        super().closeEvent(event)

    def _save_config(self) -> None:
        self.connection_panel.write_config(self.config)
        self.config.cut_feed_lines = self.action_panel.feed_lines
        self.config.last_raw = self.action_panel.raw_panel.text()
        self.config.fullscreen = self.isFullScreen()
        if not save_config(self.config):
            # 설정을 못 써도 프로그램 종료를 막지는 않는다.
            self.log_view.append("warn", "설정을 저장하지 못했습니다.")


def build_stylesheet() -> str:
    """앱 전체에 적용할 QSS."""
    return load_stylesheet()
