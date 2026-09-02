"""ESC/POS 명령 생성과 상태 응답 해석.

이 모듈은 UI(Qt)와 I/O(pyserial, win32print)에 전혀 의존하지 않는다.
바이트를 만들어 돌려주거나, 받은 바이트를 해석해 dataclass로 돌려줄 뿐이다.
덕분에 하드웨어 없이 pytest 로 단독 검증할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final

# --------------------------------------------------------------------------
# 기본 제어 문자
# --------------------------------------------------------------------------
ESC: Final = 0x1B
GS: Final = 0x1D
FS: Final = 0x1C
DLE: Final = 0x10
EOT: Final = 0x04
DC4: Final = 0x14


class Align(IntEnum):
    LEFT = 0
    CENTER = 1
    RIGHT = 2


class StatusKind(IntEnum):
    """DLE EOT n 의 n 값."""

    PRINTER = 1
    OFFLINE_CAUSE = 2
    ERROR_CAUSE = 3
    PAPER_SENSOR = 4


class CutMode(IntEnum):
    FULL = 0
    PARTIAL = 1


class DrawerPin(IntEnum):
    """금전함 커넥터 핀. 기종마다 배선이 달라 둘 다 시도해야 한다."""

    PIN_2 = 0
    PIN_5 = 1


# --------------------------------------------------------------------------
# 명령 생성
# --------------------------------------------------------------------------
def initialize() -> bytes:
    """ESC @ - 프린터 초기화."""
    return bytes([ESC, 0x40])


def select_multibyte_mode() -> bytes:
    """FS & - 다국어(2바이트) 문자 모드 진입. 한글 출력 전에 반드시 보낸다."""
    return bytes([FS, 0x26])


def cancel_multibyte_mode() -> bytes:
    """FS . - 다국어 문자 모드 해제."""
    return bytes([FS, 0x2E])


def status_query(kind: StatusKind) -> bytes:
    """DLE EOT n - 리얼타임 상태 조회. 버퍼를 무시하고 즉시 1바이트로 응답한다."""
    return bytes([DLE, EOT, int(kind)])


def align(mode: Align) -> bytes:
    """ESC a n - 정렬."""
    return bytes([ESC, 0x61, int(mode)])


def bold(on: bool) -> bytes:
    """ESC E n - 굵게."""
    return bytes([ESC, 0x45, 1 if on else 0])


def underline(on: bool, thick: bool = False) -> bytes:
    """ESC - n - 밑줄 (0=없음, 1=1점, 2=2점)."""
    n = (2 if thick else 1) if on else 0
    return bytes([ESC, 0x2D, n])


def text_size(width: int = 1, height: int = 1) -> bytes:
    """GS ! n - 문자 배율. width/height 는 1~8 배."""
    if not 1 <= width <= 8 or not 1 <= height <= 8:
        raise ValueError(f"배율은 1~8 사이여야 합니다 (width={width}, height={height})")
    n = ((width - 1) << 4) | (height - 1)
    return bytes([GS, 0x21, n])


def feed(lines: int = 1) -> bytes:
    """ESC d n - n 줄 피드."""
    if not 0 <= lines <= 255:
        raise ValueError(f"피드 줄 수는 0~255 여야 합니다 (lines={lines})")
    return bytes([ESC, 0x64, lines])


def cut(mode: CutMode = CutMode.FULL) -> bytes:
    """GS V m - 용지 절단 (0=전체, 1=부분)."""
    return bytes([GS, 0x56, int(mode)])


def feed_and_cut(lines: int = 3, mode: CutMode = CutMode.FULL) -> bytes:
    """GS V B n - n 줄 피드 후 절단. m=66(B)=전체, 67(C)=부분."""
    if not 0 <= lines <= 255:
        raise ValueError(f"피드 줄 수는 0~255 여야 합니다 (lines={lines})")
    m = 0x42 if mode is CutMode.FULL else 0x43
    return bytes([GS, 0x56, m, lines])


def drawer_kick(pin: DrawerPin, on_ms: int = 50, off_ms: int = 500) -> bytes:
    """ESC p m t1 t2 - 금전함 킥. t 단위는 2ms 이며 0~255 로 클램프된다."""
    t1 = _ms_to_ticks(on_ms)
    t2 = _ms_to_ticks(off_ms)
    return bytes([ESC, 0x70, int(pin), t1, t2])


def drawer_kick_realtime(pin: DrawerPin, on_ms: int = 200) -> bytes:
    """DLE DC4 n m t - 리얼타임 금전함 킥. 출력 버퍼를 무시하고 즉시 동작한다.

    n=1 고정, m=0(핀2)/1(핀5), t 는 100ms 단위(1~8).
    """
    t = max(1, min(8, round(on_ms / 100)))
    return bytes([DLE, DC4, 0x01, int(pin), t])


def _ms_to_ticks(ms: int) -> int:
    """밀리초를 ESC p 의 2ms 틱으로 변환한다."""
    if ms < 0:
        raise ValueError(f"시간은 0 이상이어야 합니다 (ms={ms})")
    return max(0, min(255, round(ms / 2)))


# --------------------------------------------------------------------------
# 상태 응답 해석
# --------------------------------------------------------------------------
# DLE EOT 응답은 bit0=0, bit1=1, bit4=1, bit7=0 이 고정이다.
_FIXED_MASK: Final = 0b1001_0011
_FIXED_VALUE: Final = 0b0001_0010


def is_valid_status_byte(value: int) -> bool:
    """응답 바이트가 ESC/POS 상태 바이트 형식(고정 비트)을 만족하는지 확인한다."""
    return 0 <= value <= 0xFF and (value & _FIXED_MASK) == _FIXED_VALUE


@dataclass(frozen=True)
class StatusFlag:
    """해석된 비트 하나. ok=False 면 사람이 조치해야 하는 상태다."""

    label: str
    detail: str
    ok: bool


@dataclass(frozen=True)
class StatusReport:
    """상태 바이트 하나를 해석한 결과."""

    kind: StatusKind
    raw: int
    flags: list[StatusFlag] = field(default_factory=list)
    well_formed: bool = True

    @property
    def ok(self) -> bool:
        return self.well_formed and all(f.ok for f in self.flags)

    @property
    def raw_hex(self) -> str:
        return f"0x{self.raw:02X}"

    def summary(self) -> str:
        """로그 한 줄용 요약 문자열."""
        if not self.well_formed:
            return f"{self.raw_hex} 형식이 올바르지 않은 응답"
        problems = [f.detail for f in self.flags if not f.ok]
        return f"{self.raw_hex} " + (" · ".join(problems) if problems else "정상")


def decode_status(kind: StatusKind, value: int) -> StatusReport:
    """DLE EOT n 응답 1바이트를 사람이 읽을 수 있는 형태로 해석한다."""
    if not 0 <= value <= 0xFF:
        raise ValueError(f"상태 바이트는 0~255 여야 합니다 (value={value})")

    well_formed = is_valid_status_byte(value)
    decoder = {
        StatusKind.PRINTER: _decode_printer,
        StatusKind.OFFLINE_CAUSE: _decode_offline_cause,
        StatusKind.ERROR_CAUSE: _decode_error_cause,
        StatusKind.PAPER_SENSOR: _decode_paper_sensor,
    }[kind]
    return StatusReport(kind=kind, raw=value, flags=decoder(value), well_formed=well_formed)


def _bit(value: int, mask: int) -> bool:
    return bool(value & mask)


def _decode_printer(v: int) -> list[StatusFlag]:
    """DLE EOT 1 - 프린터 상태."""
    drawer_closed = _bit(v, 0x04)
    return [
        StatusFlag(
            "금전함",
            # bit2 는 금전함 커넥터 3번 핀 레벨이다.
            # 0(LOW) = 열림, 1(HIGH) = 닫힘 또는 미연결.
            "닫힘 또는 미연결" if drawer_closed else "열림",
            ok=True,  # 열림/닫힘 자체는 오류가 아니다.
        ),
        StatusFlag("프린터", "오프라인" if _bit(v, 0x08) else "온라인", ok=not _bit(v, 0x08)),
        StatusFlag("커버", "열림" if _bit(v, 0x20) else "닫힘", ok=not _bit(v, 0x20)),
        StatusFlag(
            "피드 버튼",
            "눌림" if _bit(v, 0x40) else "안 눌림",
            ok=not _bit(v, 0x40),
        ),
    ]


def _decode_offline_cause(v: int) -> list[StatusFlag]:
    """DLE EOT 2 - 오프라인 원인."""
    return [
        StatusFlag("커버", "열림" if _bit(v, 0x04) else "닫힘", ok=not _bit(v, 0x04)),
        StatusFlag(
            "피드 버튼",
            "눌러서 급지 중" if _bit(v, 0x08) else "정상",
            ok=not _bit(v, 0x08),
        ),
        StatusFlag(
            "용지",
            "용지 없음으로 인쇄 정지" if _bit(v, 0x20) else "정상",
            ok=not _bit(v, 0x20),
        ),
        StatusFlag("에러", "에러 발생" if _bit(v, 0x40) else "없음", ok=not _bit(v, 0x40)),
    ]


def _decode_error_cause(v: int) -> list[StatusFlag]:
    """DLE EOT 3 - 에러 원인."""
    return [
        StatusFlag(
            "복구 가능 에러",
            "발생" if _bit(v, 0x04) else "없음",
            ok=not _bit(v, 0x04),
        ),
        StatusFlag("절단기", "에러" if _bit(v, 0x08) else "정상", ok=not _bit(v, 0x08)),
        StatusFlag(
            "복구 불가 에러",
            "발생 (전원 재투입 필요)" if _bit(v, 0x20) else "없음",
            ok=not _bit(v, 0x20),
        ),
        StatusFlag(
            "자동 복구 에러",
            "발생" if _bit(v, 0x40) else "없음",
            ok=not _bit(v, 0x40),
        ),
    ]


def _decode_paper_sensor(v: int) -> list[StatusFlag]:
    """DLE EOT 4 - 용지 센서. 각 상태는 2비트가 함께 셋된다."""
    near_end = _bit(v, 0x04) and _bit(v, 0x08)
    end = _bit(v, 0x20) and _bit(v, 0x40)
    if end:
        detail, ok = "없음", False
    elif near_end:
        detail, ok = "거의 없음", False
    else:
        detail, ok = "충분", True
    return [StatusFlag("용지", detail, ok=ok)]


# --------------------------------------------------------------------------
# 편의 헬퍼
# --------------------------------------------------------------------------
def parse_hex(text: str) -> bytes:
    """'1B 40', '1b40', '0x1B,0x40' 같은 입력을 바이트로 바꾼다."""
    cleaned = (
        text.replace("0x", " ")
        .replace("0X", " ")
        .replace(",", " ")
        .replace("-", " ")
        .strip()
    )
    tokens = cleaned.split()
    if not tokens:
        raise ValueError("보낼 16진수를 입력하세요. 예: 1B 40")

    if len(tokens) == 1 and len(tokens[0]) > 2:
        blob = tokens[0]
        if len(blob) % 2:
            raise ValueError(f"16진수 자릿수가 홀수입니다: {blob}")
        tokens = [blob[i : i + 2] for i in range(0, len(blob), 2)]

    out = bytearray()
    for token in tokens:
        try:
            value = int(token, 16)
        except ValueError as exc:
            raise ValueError(f"16진수로 읽을 수 없습니다: '{token}'") from exc
        if not 0 <= value <= 0xFF:
            raise ValueError(f"바이트 범위(00~FF)를 벗어났습니다: '{token}'")
        out.append(value)
    return bytes(out)


def to_hex(data: bytes, limit: int = 32) -> str:
    """로그 표시용 16진 문자열. 너무 길면 뒤를 생략한다."""
    head = data[:limit]
    text = " ".join(f"{b:02X}" for b in head)
    return text + f" … (총 {len(data)}바이트)" if len(data) > limit else text
