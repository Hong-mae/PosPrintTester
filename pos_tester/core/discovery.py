"""포트·프린터 목록 조회와 통신 속도 자동 탐색.

현장에서 가장 흔한 상황이 '포트는 맞는데 baud 를 모르는' 경우라서,
각 속도로 DLE EOT 1 을 보내 형식이 맞는 응답이 오는 속도를 찾는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from . import escpos
from .errors import ConnectionFailed
from .transport import BAUD_RATES, FlowControl, SerialSettings, SerialTransport


@dataclass(frozen=True)
class PortInfo:
    """COM 포트 하나."""

    device: str
    description: str

    @property
    def label(self) -> str:
        if self.description and self.description != "n/a":
            return f"{self.device} — {self.description}"
        return self.device


@dataclass(frozen=True)
class PrinterInfo:
    """윈도우에 설치된 프린터 하나."""

    name: str
    is_default: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} (기본 프린터)" if self.is_default else self.name


@dataclass(frozen=True)
class BaudProbe:
    """자동 탐색에서 속도 하나를 시도한 결과."""

    baudrate: int
    responded: bool
    raw: int | None = None
    note: str = ""


@dataclass(frozen=True)
class BaudScanResult:
    """자동 탐색 전체 결과."""

    probes: list[BaudProbe]
    baudrate: int | None

    @property
    def found(self) -> bool:
        return self.baudrate is not None


def list_serial_ports() -> list[PortInfo]:
    """연결된 COM 포트를 설명 문자열과 함께 돌려준다."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [
        PortInfo(device=p.device, description=(p.description or "").strip())
        for p in sorted(list_ports.comports(), key=_port_sort_key)
    ]


def _port_sort_key(port: object) -> tuple[int, str]:
    """COM10 이 COM2 앞에 오지 않도록 숫자 부분으로 정렬한다."""
    device = str(getattr(port, "device", ""))
    digits = "".join(ch for ch in device if ch.isdigit())
    return (int(digits) if digits else 9999, device)


def list_printers() -> list[PrinterInfo]:
    """설치된 프린터 목록. 윈도우가 아니면 빈 목록."""
    try:
        import win32print
    except ImportError:
        return []

    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ""

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        entries = win32print.EnumPrinters(flags, None, 2)
    except Exception:
        return []

    printers = [PrinterInfo(name=e["pPrinterName"], is_default=e["pPrinterName"] == default) for e in entries]
    # 기본 프린터를 맨 위로 올린다.
    printers.sort(key=lambda p: (not p.is_default, p.name.lower()))
    return printers


def scan_baudrates(
    port: str,
    flow: FlowControl = FlowControl.NONE,
    baudrates: Sequence[int] = BAUD_RATES,
    per_baud_timeout: float = 0.6,
    on_progress: Callable[[int, int, int], None] | None = None,
    on_result: Callable[[BaudProbe], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> BaudScanResult:
    """각 속도로 DLE EOT 1 을 보내 응답이 오는 속도를 찾는다.

    on_progress(index, total, baudrate) 와 on_result(probe) 로 진행 상황을
    실시간 보고한다. should_cancel() 이 True 를 돌려주면 즉시 중단한다.
    호출자는 이 함수를 워커 스레드에서 실행해야 한다.
    """
    probes: list[BaudProbe] = []
    total = len(baudrates)

    for index, baud in enumerate(baudrates, start=1):
        if should_cancel is not None and should_cancel():
            break
        if on_progress is not None:
            on_progress(index, total, baud)

        probe = _probe_one(port, baud, flow, per_baud_timeout)
        probes.append(probe)
        if on_result is not None:
            on_result(probe)
        if probe.responded:
            return BaudScanResult(probes=probes, baudrate=baud)

    return BaudScanResult(probes=probes, baudrate=None)


def _probe_one(port: str, baud: int, flow: FlowControl, timeout: float) -> BaudProbe:
    """속도 하나를 시도한다. 어떤 예외도 밖으로 흘리지 않는다."""
    settings = SerialSettings(port=port, baudrate=baud, flow=flow, read_timeout=timeout)
    transport = SerialTransport(settings)
    try:
        transport.open()
    except ConnectionFailed as exc:
        return BaudProbe(baudrate=baud, responded=False, note=str(exc))

    try:
        data = transport.query(escpos.status_query(escpos.StatusKind.PRINTER), 1, timeout)
    except Exception:
        return BaudProbe(baudrate=baud, responded=False, note="응답 없음")
    finally:
        transport.close()

    raw = data[0]
    if not escpos.is_valid_status_byte(raw):
        # 속도가 어긋나면 깨진 바이트가 오는 일이 흔하다. 응답으로 치지 않는다.
        return BaudProbe(baudrate=baud, responded=False, raw=raw, note=f"깨진 응답 0x{raw:02X}")
    return BaudProbe(baudrate=baud, responded=True, raw=raw, note=f"응답 0x{raw:02X}")


def describe_probes(probes: Iterable[BaudProbe]) -> str:
    """로그 한 줄로 요약한다."""
    return " / ".join(f"{p.baudrate}:{'○' if p.responded else '×'}" for p in probes)
