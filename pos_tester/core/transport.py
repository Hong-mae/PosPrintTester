"""프린터와의 전송 계층.

Transport 를 구현한 클래스는 세 가지다.

* SerialTransport   - COM 포트. 양방향이라 상태 조회가 된다.
* WinSpoolerTransport - 윈도우 스풀러 RAW 인쇄. 단방향이라 상태 조회가 안 된다.
* MockTransport     - 하드웨어 없이 UI/시나리오를 검증하기 위한 가짜 프린터.

Qt 에 의존하지 않으며, 모든 호출은 블로킹이다. UI 는 반드시 워커 스레드에서 부른다.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Final

from . import escpos
from .errors import (
    ConnectionFailed,
    NoResponse,
    NotConnected,
    TransportError,
    WriteOnlyTransport,
)

BAUD_RATES: Final[tuple[int, ...]] = (9600, 19200, 38400, 57600, 115200)


class FlowControl(Enum):
    """흐름 제어 방식. 값은 UI 표시용 라벨이다."""

    NONE = "없음"
    RTS_CTS = "RTS-CTS (하드웨어)"
    DTR_DSR = "DTR-DSR (하드웨어)"


@dataclass(frozen=True)
class SerialSettings:
    """8N1 은 ESC/POS 프린터 사실상 표준이라 고정한다."""

    port: str
    baudrate: int = 38400
    flow: FlowControl = FlowControl.NONE
    read_timeout: float = 1.0
    write_timeout: float = 3.0


class Transport(ABC):
    """프린터로 바이트를 보내고(가능하면) 받는 통로."""

    #: 상단 상태바에 표시할 대상 이름.
    display_name: str = ""
    #: False 면 상태 조회 UI 를 비활성화해야 한다.
    supports_read: bool = False

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # -- 수명 주기 -------------------------------------------------------
    @abstractmethod
    def open(self) -> None:
        """연결한다. 실패하면 ConnectionFailed 를 던진다."""

    @abstractmethod
    def close(self) -> None:
        """연결을 닫는다. 이미 닫혀 있어도 예외를 던지지 않는다."""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    # -- 입출력 ----------------------------------------------------------
    @abstractmethod
    def write(self, data: bytes) -> int:
        """바이트를 보내고 보낸 길이를 돌려준다."""

    def read(self, size: int = 1, timeout: float = 1.0) -> bytes:
        """size 바이트까지 읽는다. 단방향 연결이면 WriteOnlyTransport."""
        raise WriteOnlyTransport()

    def reset_input(self) -> None:
        """읽기 버퍼에 남은 쓰레기를 버린다. 단방향이면 아무 것도 하지 않는다."""

    # -- 조합 ------------------------------------------------------------
    def query(self, command: bytes, size: int = 1, timeout: float = 1.0) -> bytes:
        """명령을 보내고 응답을 기다린다.

        상태 조회 명령은 잔여 응답이 섞이면 해석이 어긋나므로 보내기 전에
        입력 버퍼를 비운다.
        """
        if not self.supports_read:
            raise WriteOnlyTransport()
        with self._lock:
            self.reset_input()
            self.write(command)
            data = self.read(size, timeout)
        if len(data) < size:
            raise NoResponse()
        return data

    def query_status(self, kind: escpos.StatusKind, timeout: float = 1.0) -> escpos.StatusReport:
        """DLE EOT n 을 보내고 해석된 상태를 돌려준다."""
        raw = self.query(escpos.status_query(kind), size=1, timeout=timeout)
        return escpos.decode_status(kind, raw[0])

    def __enter__(self) -> "Transport":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# --------------------------------------------------------------------------
# 시리얼 (COM)
# --------------------------------------------------------------------------
class SerialTransport(Transport):
    """pyserial 기반 COM 포트 연결. 양방향."""

    supports_read = True

    def __init__(self, settings: SerialSettings) -> None:
        super().__init__()
        self.settings = settings
        self._port: object | None = None
        self.display_name = f"{settings.port} · {settings.baudrate} · 8N1"

    def open(self) -> None:
        try:
            import serial  # 지연 임포트: pyserial 이 없어도 모듈 임포트는 되게.
        except ImportError as exc:  # pragma: no cover - 배포본에는 항상 포함된다.
            raise ConnectionFailed(
                "시리얼 통신 모듈(pyserial)을 불러오지 못했습니다.",
                ["프로그램을 다시 설치하거나 다시 빌드해 주세요."],
            ) from exc

        s = self.settings
        try:
            self._port = serial.Serial(
                port=s.port,
                baudrate=s.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=s.read_timeout,
                write_timeout=s.write_timeout,
                rtscts=s.flow is FlowControl.RTS_CTS,
                dsrdtr=s.flow is FlowControl.DTR_DSR,
            )
        except Exception as exc:
            raise ConnectionFailed(
                f"{s.port} 포트를 열 수 없습니다. ({exc})",
                [
                    "다른 프로그램(POS 프로그램 등)이 같은 포트를 쓰고 있는지 확인하세요.",
                    "장치 관리자에서 포트 번호가 맞는지 확인하세요.",
                    "USB-시리얼 변환기를 쓴다면 드라이버가 설치되어 있어야 합니다.",
                ],
            ) from exc

    def close(self) -> None:
        port = self._port
        self._port = None
        if port is not None:
            try:
                port.close()  # type: ignore[attr-defined]
            except Exception:
                pass  # 닫는 중 오류는 사용자가 할 수 있는 일이 없다.

    @property
    def is_open(self) -> bool:
        return self._port is not None and bool(getattr(self._port, "is_open", False))

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise NotConnected()
        try:
            written = self._port.write(data)  # type: ignore[union-attr]
            self._port.flush()  # type: ignore[union-attr]
        except Exception as exc:
            raise TransportError(
                f"데이터를 보내지 못했습니다. ({exc})",
                [
                    "케이블이 빠졌거나 프린터 전원이 꺼졌을 수 있습니다.",
                    "흐름 제어 설정이 맞지 않으면 전송이 멈출 수 있습니다.",
                ],
            ) from exc
        return int(written or 0)

    def read(self, size: int = 1, timeout: float = 1.0) -> bytes:
        if not self.is_open:
            raise NotConnected()
        port = self._port
        previous = port.timeout  # type: ignore[union-attr]
        try:
            port.timeout = timeout  # type: ignore[union-attr]
            return bytes(port.read(size))  # type: ignore[union-attr]
        except Exception as exc:
            raise TransportError(f"응답을 읽지 못했습니다. ({exc})") from exc
        finally:
            try:
                port.timeout = previous  # type: ignore[union-attr]
            except Exception:
                pass

    def reset_input(self) -> None:
        if self.is_open:
            try:
                self._port.reset_input_buffer()  # type: ignore[union-attr]
            except Exception:
                pass


# --------------------------------------------------------------------------
# USB (윈도우 스풀러 RAW)
# --------------------------------------------------------------------------
class WinSpoolerTransport(Transport):
    """win32print 로 스풀러에 RAW 데이터를 보낸다. 단방향이라 상태 조회 불가."""

    supports_read = False

    def __init__(self, printer_name: str, doc_name: str = "POSTester") -> None:
        super().__init__()
        self.printer_name = printer_name
        self.doc_name = doc_name
        self._handle: object | None = None
        self.display_name = f"{printer_name} (USB · 단방향)"

    def open(self) -> None:
        win32print = _import_win32print()
        try:
            self._handle = win32print.OpenPrinter(self.printer_name)
        except Exception as exc:
            raise ConnectionFailed(
                f"프린터 '{self.printer_name}' 를 열 수 없습니다. ({exc})",
                [
                    "제어판 > 장치 및 프린터에서 해당 프린터가 보이는지 확인하세요.",
                    "프린터가 오프라인 상태이거나 일시 중지되어 있을 수 있습니다.",
                ],
            ) from exc

    def close(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            _import_win32print().ClosePrinter(handle)
        except Exception:
            pass

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def write(self, data: bytes) -> int:
        if not self.is_open:
            raise NotConnected()
        win32print = _import_win32print()
        try:
            # datatype 을 "RAW" 로 지정해야 드라이버가 가공하지 않고 그대로 보낸다.
            job = win32print.StartDocPrinter(self._handle, 1, (self.doc_name, None, "RAW"))
            try:
                win32print.StartPagePrinter(self._handle)
                win32print.WritePrinter(self._handle, data)
                win32print.EndPagePrinter(self._handle)
            finally:
                win32print.EndDocPrinter(self._handle)
        except Exception as exc:
            raise TransportError(
                f"프린터로 데이터를 보내지 못했습니다. ({exc})",
                ["프린터가 일시 중지 상태이거나 인쇄 대기열이 막혀 있을 수 있습니다."],
            ) from exc
        _ = job
        return len(data)


def _import_win32print():  # type: ignore[no-untyped-def]
    """win32print 를 지연 임포트한다. 윈도우가 아니면 읽을 수 있는 메시지로 바꾼다."""
    try:
        import win32print  # noqa: PLC0415
    except ImportError as exc:
        raise ConnectionFailed(
            "USB(윈도우 스풀러) 연결은 Windows 에서만 사용할 수 있습니다.",
            ["시리얼(COM) 또는 가상 프린터(Mock) 연결을 사용하세요."],
        ) from exc
    return win32print


# --------------------------------------------------------------------------
# Mock (가상 프린터)
# --------------------------------------------------------------------------
@dataclass
class MockState:
    """가상 프린터의 내부 상태. 테스트에서 직접 조작할 수 있다."""

    online: bool = True
    cover_open: bool = False
    paper_end: bool = False
    paper_near_end: bool = False
    cutter_error: bool = False
    feed_button: bool = False
    #: 금전함이 열려 있는지. 킥 명령을 받으면 잠깐 True 가 된다.
    drawer_open: bool = False
    #: 금전함이 실제로 연결되어 있는지. False 면 킥해도 열리지 않는다.
    drawer_connected: bool = True
    #: 열림 감지 스위치(3번 핀)가 물려 있는지.
    #: False 면 서랍이 열려도 핀3 는 계속 HIGH 다 - 실제 현장에서 가장 흔한 경우.
    drawer_sensor_wired: bool = True
    #: 감지 스위치 극성이 반대(NC)인 금전함. 열림이 HIGH 로 나온다.
    drawer_sensor_inverted: bool = False
    #: 킥 후 금전함이 열린 것으로 보이는 시간(초).
    drawer_open_seconds: float = 2.0


class MockTransport(Transport):
    """가짜 ESC/POS 프린터.

    받은 바이트를 파싱해서 상태 조회에는 MockState 로 만든 상태 바이트를 돌려주고,
    금전함 킥 명령을 받으면 내부 드로어 상태를 토글한다.
    하드웨어 없이 UI 전체 플로우를 돌려보기 위한 것이다.
    """

    supports_read = True
    display_name = "가상 프린터 (Mock)"

    def __init__(self, state: MockState | None = None, latency: float = 0.0) -> None:
        super().__init__()
        self.state = state or MockState()
        self.latency = latency
        self._open = False
        self._rx = bytearray()
        #: 지금까지 받은 모든 바이트. 테스트에서 검증용으로 쓴다.
        self.received = bytearray()
        #: 프린터가 '인쇄한' 텍스트 줄. 한글 출력 검증에 쓴다.
        self.printed_lines: list[str] = []
        #: 받은 금전함 킥 명령 기록 (핀 번호, 리얼타임 여부).
        self.kicks: list[tuple[escpos.DrawerPin, bool]] = []
        #: 받은 절단 명령 기록 (모드, 피드 줄 수).
        self.cuts: list[tuple[escpos.CutMode, int]] = []
        self._multibyte = False
        self._drawer_close_at = 0.0
        self._text_buffer = bytearray()

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def reset_input(self) -> None:
        self._rx.clear()

    def write(self, data: bytes) -> int:
        if not self._open:
            raise NotConnected()
        if self.latency:
            time.sleep(self.latency)
        self.received += data
        self._parse(data)
        return len(data)

    def read(self, size: int = 1, timeout: float = 1.0) -> bytes:
        if not self._open:
            raise NotConnected()
        if self.latency:
            time.sleep(min(self.latency, timeout))
        out = bytes(self._rx[:size])
        del self._rx[: len(out)]
        return out

    # -- 파서 ------------------------------------------------------------
    def _parse(self, data: bytes) -> None:
        """받은 바이트를 훑으며 아는 명령을 처리하고 나머지는 인쇄 텍스트로 본다."""
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == escpos.DLE and i + 2 < n and data[i + 1] == escpos.EOT:
                self._rx.append(self._status_byte(escpos.StatusKind(data[i + 2])))
                i += 3
            elif b == escpos.DLE and i + 4 < n and data[i + 1] == escpos.DC4:
                self._kick(escpos.DrawerPin(data[i + 3]), realtime=True)
                i += 5
            elif b == escpos.ESC and i + 1 < n:
                i += self._parse_esc(data, i)
            elif b == escpos.GS and i + 1 < n:
                i += self._parse_gs(data, i)
            elif b == escpos.FS and i + 1 < n:
                self._multibyte = data[i + 1] == 0x26
                i += 2
            elif b == 0x0A:
                self._flush_text()
                i += 1
            else:
                self._text_buffer.append(b)
                i += 1
        self._flush_text()

    def _parse_esc(self, data: bytes, i: int) -> int:
        cmd = data[i + 1]
        if cmd == 0x70 and i + 4 < len(data):  # ESC p m t1 t2
            self._kick(escpos.DrawerPin(data[i + 2]), realtime=False)
            return 5
        if cmd == 0x64:  # ESC d n
            return 3
        if cmd in (0x61, 0x45, 0x2D, 0x21, 0x74, 0x4D):  # 인자 1개짜리
            return 3
        if cmd == 0x40:  # ESC @
            self._multibyte = False
            return 2
        return 2

    def _parse_gs(self, data: bytes, i: int) -> int:
        cmd = data[i + 1]
        if cmd == 0x56:  # GS V
            m = data[i + 2] if i + 2 < len(data) else 0
            if m in (0x42, 0x43):  # GS V B/C n - 피드 후 절단
                lines = data[i + 3] if i + 3 < len(data) else 0
                mode = escpos.CutMode.FULL if m == 0x42 else escpos.CutMode.PARTIAL
                self.cuts.append((mode, lines))
                return 4
            self.cuts.append((escpos.CutMode(m if m in (0, 1) else 0), 0))
            return 3
        if cmd == 0x21:  # GS ! n
            return 3
        return 3

    def _flush_text(self) -> None:
        if not self._text_buffer:
            return
        text = bytes(self._text_buffer).decode("cp949", errors="replace")
        self._text_buffer.clear()
        if text.strip():
            self.printed_lines.append(text)

    def _kick(self, pin: escpos.DrawerPin, realtime: bool) -> None:
        self.kicks.append((pin, realtime))
        if self.state.drawer_connected:
            self.state.drawer_open = True
            self._drawer_close_at = time.monotonic() + self.state.drawer_open_seconds

    def _drawer_is_open(self) -> bool:
        if self.state.drawer_open and time.monotonic() >= self._drawer_close_at:
            self.state.drawer_open = False
        return self.state.drawer_open

    def _pin3_high(self) -> bool:
        """금전함 커넥터 3번 핀 레벨.

        센서선이 없으면 풀업되어 서랍 상태와 무관하게 계속 HIGH 다.
        """
        if not self.state.drawer_sensor_wired:
            return True
        is_open = self._drawer_is_open()
        return is_open if self.state.drawer_sensor_inverted else not is_open

    # -- 상태 바이트 생성 -------------------------------------------------
    def _status_byte(self, kind: escpos.StatusKind) -> int:
        v = 0b0001_0010  # bit1, bit4 고정
        s = self.state
        if kind is escpos.StatusKind.PRINTER:
            if self._pin3_high():
                v |= 0x04
            if not s.online or s.cover_open or s.paper_end:
                v |= 0x08
            if s.cover_open:
                v |= 0x20
            if s.feed_button:
                v |= 0x40
        elif kind is escpos.StatusKind.OFFLINE_CAUSE:
            if s.cover_open:
                v |= 0x04
            if s.feed_button:
                v |= 0x08
            if s.paper_end:
                v |= 0x20
            if s.cutter_error:
                v |= 0x40
        elif kind is escpos.StatusKind.ERROR_CAUSE:
            if s.cutter_error:
                v |= 0x08
        elif kind is escpos.StatusKind.PAPER_SENSOR:
            if s.paper_near_end or s.paper_end:
                v |= 0x04 | 0x08
            if s.paper_end:
                v |= 0x20 | 0x40
        return v
