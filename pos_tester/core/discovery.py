"""포트·프린터 목록 조회와 통신 속도 자동 탐색.

현장에서 가장 흔한 상황이 '포트는 맞는데 baud 를 모르는' 경우라서,
각 속도로 DLE EOT 1 을 보내 형식이 맞는 응답이 오는 속도를 찾는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from . import escpos
from .errors import ConnectionFailed, TransportError
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
    """연결된 COM 포트를 설명 문자열과 함께 돌려준다.

    두 곳을 합쳐서 본다.

    1. pyserial 의 comports() — SetupAPI 의 '포트(COM & LPT)' 장치 클래스
    2. 레지스트리 HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM

    1번만 보면 POS 메인보드 내장 시리얼처럼 '포트' 장치 클래스로 등록되지 않은
    COM 포트가 통째로 빠진다. 장치 관리자에는 안 보여도 실제로는 열리는 포트가
    있고, SERIALCOMM 은 그런 포트까지 담고 있는 실제 존재 목록이다.
    (윈도우의 mode 명령이나 SerialPort.GetPortNames() 가 보는 곳이 여기다.)

    조회 자체가 실패하면 빈 목록 대신 예외를 던진다. 빈 목록으로 뭉개면
    '포트가 없다' 와 '조회를 못 했다' 를 구분할 수 없어 현장에서 원인을 못 찾는다.
    """
    try:
        from serial.tools import list_ports
    except ImportError as exc:  # pragma: no cover - 배포본에는 항상 포함된다.
        raise TransportError(
            "시리얼 통신 모듈(pyserial)을 불러오지 못해 포트를 조회할 수 없습니다.",
            ["프로그램을 다시 설치하거나 다시 빌드해 주세요."],
        ) from exc

    found: dict[str, PortInfo] = {}
    for port in list_ports.comports():
        info = PortInfo(device=port.device, description=(port.description or "").strip())
        found[info.device.upper()] = info

    # SetupAPI 가 놓친 포트를 레지스트리로 보완한다. 이미 찾은 포트는 덮어쓰지 않는다.
    for info in registry_serial_ports():
        found.setdefault(info.device.upper(), info)

    return sorted(found.values(), key=_port_sort_key)


def registry_serial_ports() -> list[PortInfo]:
    """레지스트리 SERIALCOMM 에 등록된 COM 포트.

    윈도우가 아니거나 키가 없으면 빈 목록을 돌려준다.
    이건 보조 수단이라 실패해도 예외를 던지지 않는다 - 주 경로인 comports() 가
    이미 동작했다면 여기서 막힐 이유가 없다.
    """
    try:
        import winreg
    except ImportError:
        return []

    ports: list[PortInfo] = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
        ) as key:
            _, value_count, _ = winreg.QueryInfoKey(key)
            for index in range(value_count):
                source, device, _ = winreg.EnumValue(key, index)
                device = str(device).strip()
                if device:
                    # source 는 \Device\Serial0 같은 드라이버 이름이다.
                    driver = str(source).rsplit("\\", 1)[-1]
                    ports.append(PortInfo(device=device, description=f"{driver} (레지스트리)"))
    except OSError:
        return []
    return ports


def _port_sort_key(port: object) -> tuple[int, str]:
    """COM10 이 COM2 앞에 오지 않도록 숫자 부분으로 정렬한다."""
    device = str(getattr(port, "device", ""))
    digits = "".join(ch for ch in device if ch.isdigit())
    return (int(digits) if digits else 9999, device)


def list_printers() -> list[PrinterInfo]:
    """설치된 프린터 목록.

    조회 자체가 실패하면 빈 목록 대신 예외를 던진다. 이유를 화면에 적어야
    기사가 '프린터가 없다' 와 '프로그램이 조회를 못 했다' 를 구분할 수 있다.
    """
    try:
        import win32print
    except ImportError as exc:
        raise TransportError(
            "USB(윈도우 프린터) 목록은 Windows 에서만 조회할 수 있습니다.",
            ["시리얼(COM) 또는 가상 프린터 연결을 사용하세요."],
        ) from exc

    try:
        default = win32print.GetDefaultPrinter()
    except Exception:
        default = ""

    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    try:
        entries = win32print.EnumPrinters(flags, None, 2)
    except Exception as exc:
        raise TransportError(
            f"프린터 목록을 읽지 못했습니다. ({exc})",
            ["제어판 > 장치 및 프린터에서 프린터가 보이는지 확인하세요."],
        ) from exc

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
