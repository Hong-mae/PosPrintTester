"""테스트 시나리오.

Transport 하나만 받아서 동작하며 Qt 에 의존하지 않는다.
모든 메서드는 블로킹이므로 UI 는 워커 스레드에서 호출해야 한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Final, Literal

from . import escpos
from .encoding import encode_line
from .errors import PosTesterError, WriteOnlyTransport
from .transport import Transport

LogLevel = Literal["info", "ok", "warn", "error"]
LogFn = Callable[[LogLevel, str], None]

#: 금전함이 안 열릴 때 기사에게 보여줄 점검 순서.
DRAWER_CHECKLIST: Final[tuple[str, ...]] = (
    "반대쪽 핀으로 다시 시도하세요. (2번 핀 ↔ 5번 핀) 기종마다 배선이 다릅니다.",
    "솔레노이드 전압을 확인하세요. EC-410 은 12V 모델과 24V 모델이 따로 있습니다. "
    "24V 금전함을 12V 포트에 물리면 '딸깍' 소리만 나고 열리지 않습니다.",
    "RJ-11 / RJ-12 케이블이 프린터의 DK(금전함) 포트에 끝까지 꽂혔는지 확인하세요. "
    "전화선 포트처럼 생겨서 헐겁게 걸쳐진 경우가 많습니다.",
    "금전함 측면의 수동 키가 잠금(LOCK) 위치인지 확인하세요. 잠겨 있으면 신호가 가도 열리지 않습니다.",
)

#: RAW 전송 패널에 노출할 프리셋.
COMMAND_PRESETS: Final[tuple[tuple[str, str], ...]] = (
    ("초기화 (ESC @)", "1B 40"),
    ("프린터 상태 (DLE EOT 1)", "10 04 01"),
    ("오프라인 원인 (DLE EOT 2)", "10 04 02"),
    ("에러 상태 (DLE EOT 3)", "10 04 03"),
    ("용지 센서 (DLE EOT 4)", "10 04 04"),
    ("금전함 2번 핀 (ESC p 0)", "1B 70 00 19 FA"),
    ("금전함 5번 핀 (ESC p 1)", "1B 70 01 19 FA"),
    ("금전함 리얼타임 (DLE DC4)", "10 14 01 00 02"),
    ("전체 절단 (GS V 0)", "1D 56 00"),
    ("부분 절단 (GS V 1)", "1D 56 01"),
    ("3줄 피드 후 절단 (GS V B 3)", "1D 56 42 03"),
    ("3줄 피드 (ESC d 3)", "1B 64 03"),
)

_WIDTH: Final = 42  # 80mm 용지 기본 폭(글자 수)


@dataclass
class StepResult:
    """테스트 한 단계의 결과."""

    title: str
    ok: bool
    detail: str = ""
    hints: list[str] = field(default_factory=list)
    #: 상태 조회 단계라면 해석된 상태들.
    reports: list[escpos.StatusReport] = field(default_factory=list)


class PrinterTester:
    """프린터 점검 시나리오 모음."""

    def __init__(self, transport: Transport, log: LogFn | None = None) -> None:
        self.transport = transport
        self._log: LogFn = log or (lambda level, message: None)

    # -- 내부 헬퍼 -------------------------------------------------------
    def _send(self, data: bytes, what: str) -> None:
        self._log("info", f"→ {what}  [{escpos.to_hex(data)}]")
        self.transport.write(data)

    def _failure(self, title: str, exc: Exception) -> StepResult:
        """예외를 삼키지 않고 사람이 읽을 수 있는 결과로 바꾼다."""
        if isinstance(exc, PosTesterError):
            message, hints = exc.message, list(exc.hints)
        else:
            message, hints = f"예상치 못한 오류: {exc}", []
        self._log("error", f"{title} 실패 — {message}")
        for hint in hints:
            self._log("warn", f"  · {hint}")
        return StepResult(title=title, ok=False, detail=message, hints=hints)

    # -- 개별 동작 -------------------------------------------------------
    def initialize(self) -> StepResult:
        """ESC @ 로 프린터를 초기화한다."""
        title = "초기화"
        try:
            self._send(escpos.initialize(), "ESC @ 초기화")
        except Exception as exc:
            return self._failure(title, exc)
        self._log("ok", "초기화 명령을 보냈습니다.")
        return StepResult(title=title, ok=True, detail="ESC @ 전송 완료")

    def feed(self, lines: int = 3) -> StepResult:
        title = f"{lines}줄 피드"
        try:
            self._send(escpos.feed(lines), title)
        except Exception as exc:
            return self._failure(title, exc)
        return StepResult(title=title, ok=True, detail=f"{lines}줄 피드 완료")

    def cut(self, mode: escpos.CutMode = escpos.CutMode.FULL, feed_lines: int = 0) -> StepResult:
        """용지를 자른다. feed_lines > 0 이면 그만큼 피드한 뒤 자른다.

        절단 날 앞까지 용지를 밀어내야 인쇄 내용이 잘리지 않으므로,
        실제 점검에서는 3줄 이상 피드 후 절단을 권한다.
        """
        mode_label = "전체 절단" if mode is escpos.CutMode.FULL else "부분 절단"
        title = f"{feed_lines}줄 피드 후 {mode_label}" if feed_lines else mode_label
        try:
            data = escpos.feed_and_cut(feed_lines, mode) if feed_lines else escpos.cut(mode)
            self._send(data, title)
        except Exception as exc:
            return self._failure(title, exc)
        self._log("ok", f"{title} 명령을 보냈습니다.")
        return StepResult(
            title=title,
            ok=True,
            detail="절단 명령 전송 완료",
            hints=["용지가 잘리지 않으면 자동 절단기가 없는 기종이거나 절단기에 용지가 걸린 것입니다."],
        )

    def read_status(self) -> StepResult:
        """상태 4종을 모두 조회해 비트 단위로 해석한다."""
        title = "상태 조회"
        if not self.transport.supports_read:
            exc = WriteOnlyTransport()
            self._log("warn", exc.message)
            return StepResult(title=title, ok=False, detail=exc.message, hints=exc.hints)

        reports: list[escpos.StatusReport] = []
        try:
            for kind in escpos.StatusKind:
                report = self.transport.query_status(kind)
                reports.append(report)
                level: LogLevel = "ok" if report.ok else "warn"
                self._log(level, f"DLE EOT {int(kind)} ({_KIND_LABELS[kind]}) → {report.summary()}")
                for flag in report.flags:
                    self._log("info", f"    {flag.label}: {flag.detail}")
        except Exception as exc:
            return self._failure(title, exc)

        problems = [f.detail for r in reports for f in r.flags if not f.ok]
        ok = not problems
        return StepResult(
            title=title,
            ok=ok,
            detail="이상 없음" if ok else " · ".join(problems),
            reports=reports,
        )

    def connection_test(self) -> StepResult:
        """ESC @ 를 보낸 뒤 상태 4종을 조회한다."""
        title = "연결 테스트"
        init = self.initialize()
        if not init.ok:
            return StepResult(title=title, ok=False, detail=init.detail, hints=init.hints)

        if not self.transport.supports_read:
            self._log("warn", "단방향 연결이라 상태를 확인할 수 없습니다. 전송만 성공했습니다.")
            return StepResult(
                title=title,
                ok=True,
                detail="전송 성공 (단방향이라 상태 확인 불가)",
                hints=WriteOnlyTransport().hints,
            )

        status = self.read_status()
        return StepResult(
            title=title,
            ok=status.ok,
            detail=status.detail,
            hints=status.hints,
            reports=status.reports,
        )

    # -- 출력 테스트 -----------------------------------------------------
    def print_test(self, cut_after: bool = True, feed_lines: int = 4) -> StepResult:
        """한글·정렬·강조·금액 포맷을 한 장에 모두 찍는다."""
        title = "출력 테스트"
        try:
            data, replaced = self._build_receipt(cut_after=cut_after, feed_lines=feed_lines)
            self._log("info", f"→ 출력 테스트 {len(data)}바이트 전송")
            self.transport.write(data)
        except Exception as exc:
            return self._failure(title, exc)

        if replaced:
            self._log("warn", f"프린터가 표현할 수 없어 '?' 로 바꾼 문자: {' '.join(replaced)}")
        self._log("ok", "출력 테스트 전송 완료 — 인쇄물을 눈으로 확인하세요.")
        return StepResult(
            title=title,
            ok=True,
            detail=f"{len(data)}바이트 전송 완료",
            hints=["한글이 깨져 나오면 프린터의 코드페이지를 KS5601(cp949)로 맞춰야 합니다."],
        )

    def _build_receipt(self, cut_after: bool, feed_lines: int) -> tuple[bytes, list[str]]:
        """테스트 영수증 바이트를 만든다. 대체된 문자 목록도 함께 돌려준다."""
        out = bytearray()
        replaced: list[str] = []

        def line(text: str = "") -> None:
            result = encode_line(text)
            out.extend(result.data)
            for ch in result.replaced:
                if ch not in replaced:
                    replaced.append(ch)

        def raw(data: bytes) -> None:
            out.extend(data)

        raw(escpos.initialize())
        # 한글을 보내기 전에 반드시 다국어 모드로 들어간다.
        raw(escpos.select_multibyte_mode())

        # 제목: 가운데 정렬 + 가로 2배 + 세로 2배 + 굵게
        raw(escpos.align(escpos.Align.CENTER))
        raw(escpos.text_size(2, 2))
        raw(escpos.bold(True))
        line("POS 점검표")
        raw(escpos.bold(False))
        raw(escpos.text_size(1, 1))
        line(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        raw(escpos.align(escpos.Align.LEFT))
        line("-" * _WIDTH)

        # 문자 종류
        line("[문자] 한글 ABCDEFG abcdefg 0123456789")
        line("[기호] ! @ # $ % ^ & * ( ) - + = / \\ : ; ' \"")
        line("[한글] 다람쥐 헌 쳇바퀴에 타고파 뷁 쭱 똠얌꿍")
        line("-" * _WIDTH)

        # 금액 포맷
        line(_amount_row("상품 A", 1_200))
        line(_amount_row("상품 B", 34_500))
        line(_amount_row("상품 C", 1_234_567))
        raw(escpos.bold(True))
        line(_amount_row("합    계", 1_270_267))
        raw(escpos.bold(False))
        line("-" * _WIDTH)

        # 정렬
        raw(escpos.align(escpos.Align.LEFT))
        line("왼쪽 정렬 (LEFT)")
        raw(escpos.align(escpos.Align.CENTER))
        line("가운데 정렬 (CENTER)")
        raw(escpos.align(escpos.Align.RIGHT))
        line("오른쪽 정렬 (RIGHT)")
        raw(escpos.align(escpos.Align.LEFT))
        line("-" * _WIDTH)

        # 강조
        raw(escpos.bold(True))
        line("굵게 (BOLD) 강조 문자")
        raw(escpos.bold(False))
        raw(escpos.underline(True))
        line("밑줄 (UNDERLINE) 문자")
        raw(escpos.underline(False))
        raw(escpos.text_size(2, 1))
        line("가로 2배")
        raw(escpos.text_size(1, 2))
        line("세로 2배")
        raw(escpos.text_size(2, 2))
        line("가로세로 2배")
        raw(escpos.text_size(1, 1))
        line("=" * _WIDTH)

        raw(escpos.align(escpos.Align.CENTER))
        line("위 항목이 모두 보이면 출력 정상")
        raw(escpos.align(escpos.Align.LEFT))

        # 다국어 모드 해제 후 마무리
        raw(escpos.cancel_multibyte_mode())
        if cut_after:
            raw(escpos.feed_and_cut(feed_lines, escpos.CutMode.FULL))
        else:
            raw(escpos.feed(feed_lines))

        return bytes(out), replaced

    # -- 금전함 ----------------------------------------------------------
    def drawer_test(
        self,
        pin: escpos.DrawerPin,
        realtime: bool = False,
        verify_delay: float = 0.35,
    ) -> StepResult:
        """금전함을 킥하고, 가능하면 핀3 상태로 실제로 열렸는지 확인한다."""
        pin_label = "2번 핀" if pin is escpos.DrawerPin.PIN_2 else "5번 핀"
        title = f"금전함 {pin_label}" + (" (리얼타임)" if realtime else "")

        try:
            data = (
                escpos.drawer_kick_realtime(pin) if realtime else escpos.drawer_kick(pin, 50, 500)
            )
            self._send(data, title)
        except Exception as exc:
            return self._failure(title, exc)

        if not self.transport.supports_read:
            self._log("warn", "단방향 연결이라 실제로 열렸는지 확인할 수 없습니다. 직접 눈으로 확인하세요.")
            return StepResult(
                title=title,
                ok=True,
                detail="킥 명령 전송 완료 (열림 여부 확인 불가)",
                hints=list(DRAWER_CHECKLIST),
            )

        # 솔레노이드가 움직이고 핀3 레벨이 바뀔 시간을 준다.
        time.sleep(verify_delay)
        try:
            report = self.transport.query_status(escpos.StatusKind.PRINTER)
        except Exception as exc:
            return self._failure(f"{title} 상태 확인", exc)

        opened = not bool(report.raw & 0x04)  # bit2 == 0 이면 핀3 LOW = 열림
        if opened:
            self._log("ok", f"{title}: 금전함이 열렸습니다. (핀3 LOW, {report.raw_hex})")
            return StepResult(title=title, ok=True, detail="금전함 열림 확인", reports=[report])

        self._log("warn", f"{title}: 열림 신호가 확인되지 않습니다. (핀3 HIGH, {report.raw_hex})")
        for item in DRAWER_CHECKLIST:
            self._log("info", f"  · {item}")
        return StepResult(
            title=title,
            ok=False,
            detail="핀3가 LOW 로 떨어지지 않았습니다 (닫힘 또는 미연결)",
            hints=list(DRAWER_CHECKLIST),
            reports=[report],
        )

    # -- RAW -------------------------------------------------------------
    def send_raw(self, data: bytes, read_reply: bool = True) -> StepResult:
        """임의의 바이트를 보낸다. 응답이 있으면 함께 표시한다."""
        title = "RAW 전송"
        if not data:
            return StepResult(title=title, ok=False, detail="보낼 데이터가 비어 있습니다.")
        try:
            self._send(data, f"RAW {len(data)}바이트")
        except Exception as exc:
            return self._failure(title, exc)

        detail = f"{len(data)}바이트 전송"
        if read_reply and self.transport.supports_read:
            try:
                reply = self.transport.read(1, timeout=0.4)
            except Exception:
                reply = b""
            if reply:
                detail += f" · 응답 {escpos.to_hex(reply)}"
                self._log("ok", f"← 응답 {escpos.to_hex(reply)}")
        self._log("ok", f"RAW 전송 완료 ({len(data)}바이트)")
        return StepResult(title=title, ok=True, detail=detail)

    # -- 전체 -------------------------------------------------------------
    def run_all(
        self,
        on_step: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[StepResult]:
        """전체 테스트를 순서대로 실행한다."""
        steps: list[tuple[str, Callable[[], StepResult]]] = [
            ("연결 테스트", self.connection_test),
            ("출력 테스트", lambda: self.print_test(cut_after=False, feed_lines=1)),
            ("금전함 2번 핀", lambda: self.drawer_test(escpos.DrawerPin.PIN_2)),
            ("금전함 5번 핀", lambda: self.drawer_test(escpos.DrawerPin.PIN_5)),
            ("용지 절단", lambda: self.cut(escpos.CutMode.FULL, feed_lines=4)),
        ]

        results: list[StepResult] = []
        total = len(steps)
        for index, (label, run) in enumerate(steps, start=1):
            if should_cancel is not None and should_cancel():
                self._log("warn", "전체 테스트가 중단되었습니다.")
                break
            if on_step is not None:
                on_step(index, total, label)
            self._log("info", f"── [{index}/{total}] {label} ──")
            results.append(run())
        return results


_KIND_LABELS: Final[dict[escpos.StatusKind, str]] = {
    escpos.StatusKind.PRINTER: "프린터 상태",
    escpos.StatusKind.OFFLINE_CAUSE: "오프라인 원인",
    escpos.StatusKind.ERROR_CAUSE: "에러 상태",
    escpos.StatusKind.PAPER_SENSOR: "용지 센서",
}


def _amount_row(label: str, amount: int) -> str:
    """'상품 A            1,200원' 처럼 금액을 오른쪽에 붙인다.

    한글은 프린터에서 2칸을 차지하므로 폭 계산에 반영한다.
    """
    value = f"{amount:,}원"
    pad = max(1, _WIDTH - _display_width(label) - _display_width(value))
    return f"{label}{' ' * pad}{value}"


def _display_width(text: str) -> int:
    """프린터 기준 표시 폭. 한글·전각 문자는 2칸으로 센다."""
    return sum(2 if ord(ch) > 0x7F else 1 for ch in text)
