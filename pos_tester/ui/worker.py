"""워커 스레드.

시리얼 I/O 는 전부 여기서 돈다. UI 스레드는 submit() 으로 작업을 넘기고
시그널로만 결과를 받는다. UI 스레드에서 transport 를 직접 만지는 코드는 없어야 한다.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..core import escpos
from ..core.discovery import BaudScanResult, scan_baudrates
from ..core.errors import PosTesterError
from ..core.tester import LogLevel, PrinterTester, StepResult
from ..core.transport import FlowControl, Transport


@dataclass
class Job:
    """워커 스레드에서 실행할 작업 하나."""

    #: UI 가 결과를 어느 버튼에 되돌릴지 구분하는 키.
    key: str
    #: 진행 표시에 쓸 라벨.
    label: str
    #: 워커 자신을 받아 결과를 돌려주는 함수.
    run: Callable[["PrinterWorker"], Any]
    #: 연결되지 않아도 실행할 수 있는 작업인지.
    needs_connection: bool = True


@dataclass
class JobOutcome:
    """작업 결과. 예외는 여기까지 잡아서 읽을 수 있는 메시지로 바꿔 온다."""

    key: str
    label: str
    ok: bool
    #: 실패는 아니지만 사용자가 눈으로 확인해야 하는 상태. UI 가 노란색으로 표시한다.
    warning: bool = False
    detail: str = ""
    hints: list[str] = field(default_factory=list)
    payload: Any = None


class PrinterWorker(QObject):
    """전송 계층을 소유하고 모든 블로킹 호출을 대신 수행한다."""

    #: (레벨, 메시지) — 로그 창에 그대로 찍힌다.
    log = Signal(str, str)
    #: (설명, 현재값, 최대값) — 최대값 0 이면 진행률을 알 수 없는 상태.
    progress = Signal(str, int, int)
    #: (작업 키, JobOutcome)
    job_done = Signal(str, object)
    #: (연결됨, 대상 이름, 상태 조회 가능 여부)
    connection_changed = Signal(bool, str, bool)
    #: 큐가 비어 UI 를 다시 활성화해도 되는 시점.
    idle = Signal()

    _submitted = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.transport: Transport | None = None
        self.tester: PrinterTester | None = None
        self._cancel = threading.Event()
        self._pending = 0
        self._pending_lock = threading.Lock()
        # 워커 스레드로 넘어간 뒤에는 큐드 커넥션이 되어 호출이 스레드를 건넌다.
        self._submitted.connect(self._execute)

    # -- UI 스레드에서 호출 ------------------------------------------------
    def submit(self, job: Job) -> None:
        """작업을 워커 스레드 큐에 넣는다. 즉시 반환한다."""
        with self._pending_lock:
            self._pending += 1
        self._submitted.emit(job)

    def request_cancel(self) -> None:
        """진행 중인 반복 작업(전체 테스트, 속도 탐색)에 중단을 요청한다."""
        self._cancel.set()

    @property
    def is_connected(self) -> bool:
        return self.transport is not None and self.transport.is_open

    # -- 워커 스레드에서 실행 ----------------------------------------------
    def _execute(self, job: Job) -> None:
        self._cancel.clear()
        try:
            if job.needs_connection and not self.is_connected:
                raise PosTesterError(
                    "아직 연결되지 않았습니다.", ["왼쪽 '연결' 버튼을 먼저 눌러 주세요."]
                )
            self.progress.emit(job.label, 0, 0)
            result = job.run(self)
            outcome = _to_outcome(job, result)
        except PosTesterError as exc:
            self.log.emit("error", f"{job.label} 실패 — {exc.message}")
            for hint in exc.hints:
                self.log.emit("warn", f"  · {hint}")
            outcome = JobOutcome(job.key, job.label, False, False, exc.message, list(exc.hints))
        except Exception as exc:  # 예상 못 한 예외도 삼키지 않고 사용자에게 보여준다.
            detail = f"예상치 못한 오류: {exc}"
            self.log.emit("error", f"{job.label} 실패 — {detail}")
            self.log.emit("info", traceback.format_exc().strip())
            outcome = JobOutcome(job.key, job.label, False, False, detail)

        self.job_done.emit(job.key, outcome)
        with self._pending_lock:
            self._pending -= 1
            remaining = self._pending
        if remaining <= 0:
            self.idle.emit()

    def should_cancel(self) -> bool:
        return self._cancel.is_set()

    def emit_log(self, level: LogLevel, message: str) -> None:
        self.log.emit(level, message)

    # -- 연결 --------------------------------------------------------------
    def connect_transport(self, transport: Transport) -> str:
        """기존 연결을 닫고 새 전송 계층을 연다."""
        self.disconnect_transport(quiet=True)
        transport.open()
        self.transport = transport
        self.tester = PrinterTester(transport, log=self.emit_log)
        self.connection_changed.emit(True, transport.display_name, transport.supports_read)
        self.log.emit("ok", f"연결됨 — {transport.display_name}")
        if not transport.supports_read:
            self.log.emit(
                "warn",
                "단방향 연결이라 프린터 상태를 읽을 수 없습니다. 상태 조회 기능이 잠깁니다.",
            )
        return transport.display_name

    def disconnect_transport(self, quiet: bool = False) -> str:
        transport = self.transport
        self.transport = None
        self.tester = None
        if transport is not None:
            transport.close()
            if not quiet:
                self.log.emit("info", f"연결을 끊었습니다 — {transport.display_name}")
        self.connection_changed.emit(False, "", False)
        return "연결 해제"

    def require_tester(self) -> PrinterTester:
        if self.tester is None:
            raise PosTesterError(
                "아직 연결되지 않았습니다.", ["왼쪽 '연결' 버튼을 먼저 눌러 주세요."]
            )
        return self.tester

    # -- 속도 자동 탐색 -----------------------------------------------------
    def scan_baud(self, port: str, flow: FlowControl) -> BaudScanResult:
        """포트를 열어 두지 않은 상태에서 각 속도를 순서대로 시도한다."""
        self.disconnect_transport(quiet=True)
        self.log.emit("info", f"{port} 통신 속도 자동 탐색을 시작합니다.")

        def on_progress(index: int, total: int, baud: int) -> None:
            self.progress.emit(f"{baud} bps 시도 중… ({index}/{total})", index, total)
            self.log.emit("info", f"  {baud} bps 시도…")

        def on_result(probe: Any) -> None:
            level: LogLevel = "ok" if probe.responded else "info"
            self.log.emit(level, f"  {probe.baudrate} bps → {probe.note}")

        result = scan_baudrates(
            port=port,
            flow=flow,
            on_progress=on_progress,
            on_result=on_result,
            should_cancel=self.should_cancel,
        )
        if result.found:
            self.log.emit("ok", f"통신 속도를 찾았습니다: {result.baudrate} bps")
        else:
            self.log.emit("warn", "응답하는 속도를 찾지 못했습니다.")
        return result


def _to_outcome(job: Job, result: Any) -> JobOutcome:
    """작업 반환값을 UI 가 다루기 쉬운 JobOutcome 으로 정규화한다."""
    if isinstance(result, JobOutcome):
        return result
    if isinstance(result, StepResult):
        return JobOutcome(
            job.key, result.title, result.ok, result.warning, result.detail, result.hints, result
        )
    if isinstance(result, list) and result and isinstance(result[0], StepResult):
        ok = all(step.ok for step in result)
        warning = any(step.warning for step in result)
        failed = [step.title for step in result if not step.ok]
        warned = [step.title for step in result if step.warning]
        if not ok:
            detail = "실패: " + ", ".join(failed)
        elif warning:
            detail = "확인 필요: " + ", ".join(warned)
        else:
            detail = "모든 단계 정상"
        return JobOutcome(job.key, job.label, ok, warning, detail, payload=result)
    if isinstance(result, BaudScanResult):
        detail = (
            f"{result.baudrate} bps 에서 응답" if result.found else "응답하는 속도를 찾지 못했습니다"
        )
        return JobOutcome(job.key, job.label, result.found, False, detail, payload=result)
    return JobOutcome(job.key, job.label, True, False, str(result or ""), payload=result)


class WorkerThread:
    """PrinterWorker 와 그것을 담는 QThread 를 함께 관리한다."""

    def __init__(self) -> None:
        self.thread = QThread()
        self.thread.setObjectName("PrinterWorker")
        self.worker = PrinterWorker()
        self.worker.moveToThread(self.thread)
        self.thread.start()

    def stop(self) -> None:
        """워커가 소유한 연결을 닫고 스레드를 정리한다."""
        transport = self.worker.transport
        if transport is not None:
            try:
                transport.close()
            except Exception:
                pass
        self.thread.quit()
        self.thread.wait(3000)


# --------------------------------------------------------------------------
# 자주 쓰는 Job 생성기
# --------------------------------------------------------------------------
def job_connect(transport: Transport) -> Job:
    return Job(
        key="connect",
        label=f"{transport.display_name} 연결 중",
        run=lambda w: w.connect_transport(transport),
        needs_connection=False,
    )


def job_disconnect() -> Job:
    return Job(
        key="disconnect",
        label="연결 해제",
        run=lambda w: w.disconnect_transport(),
        needs_connection=False,
    )


def job_scan_baud(port: str, flow: FlowControl) -> Job:
    return Job(
        key="scan",
        label="통신 속도 자동 탐색",
        run=lambda w: w.scan_baud(port, flow),
        needs_connection=False,
    )


def job_connection_test() -> Job:
    return Job("conn_test", "연결 테스트", lambda w: w.require_tester().connection_test())


def job_read_status() -> Job:
    return Job("status", "상태 새로고침", lambda w: w.require_tester().read_status())


def job_print_test(cut_after: bool, feed_lines: int) -> Job:
    return Job(
        "print",
        "출력 테스트",
        lambda w: w.require_tester().print_test(cut_after=cut_after, feed_lines=feed_lines),
    )


def job_drawer(pin: escpos.DrawerPin, realtime: bool = False) -> Job:
    key = f"drawer_{'rt' if realtime else int(pin)}"
    label = ("리얼타임 킥" if realtime else f"{'2' if pin is escpos.DrawerPin.PIN_2 else '5'}번 핀 킥")
    return Job(key, label, lambda w: w.require_tester().drawer_test(pin, realtime=realtime))


def job_cut(mode: escpos.CutMode, feed_lines: int = 0) -> Job:
    key = f"cut_{int(mode)}_{feed_lines}"
    return Job(key, "용지 절단", lambda w: w.require_tester().cut(mode, feed_lines=feed_lines))


def job_feed(lines: int) -> Job:
    return Job(f"feed_{lines}", f"{lines}줄 피드", lambda w: w.require_tester().feed(lines))


def job_initialize() -> Job:
    return Job("init", "초기화", lambda w: w.require_tester().initialize())


def job_send_raw(data: bytes) -> Job:
    return Job("raw", "RAW 전송", lambda w: w.require_tester().send_raw(data))


def job_run_all() -> Job:
    def run(worker: PrinterWorker) -> Any:
        tester = worker.require_tester()

        def on_step(index: int, total: int, label: str) -> None:
            worker.progress.emit(f"전체 테스트 — {label} ({index}/{total})", index, total)

        return tester.run_all(on_step=on_step, should_cancel=worker.should_cancel)

    return Job("run_all", "전체 테스트", run)
