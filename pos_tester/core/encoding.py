"""프린터 코드페이지 인코딩.

한글은 FS & 로 다국어 모드에 들어간 뒤 cp949(= EUC-KR 확장)로 보내야 한다.
인코딩할 수 없는 문자를 만나도 예외를 던지지 않고 대체 문자로 바꿔
'한 글자 때문에 영수증 전체가 안 나오는' 상황을 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 프린터 코드페이지에 없는 문자를 대신할 바이트('?').
REPLACEMENT: bytes = b"?"

#: 한국어 프린터가 쓰는 코드페이지.
PRINTER_CODEPAGE = "cp949"


@dataclass(frozen=True)
class EncodeResult:
    """인코딩 결과와, 대체된 문자 목록."""

    data: bytes
    replaced: list[str]

    @property
    def had_replacements(self) -> bool:
        return bool(self.replaced)


def encode_text(text: str, codepage: str = PRINTER_CODEPAGE) -> EncodeResult:
    """문자열을 프린터 코드페이지 바이트로 바꾼다.

    변환할 수 없는 문자는 REPLACEMENT 로 바꾸고 어떤 문자였는지 기록한다.
    """
    try:
        return EncodeResult(text.encode(codepage), [])
    except UnicodeEncodeError:
        pass  # 아래에서 한 글자씩 처리한다.

    out = bytearray()
    replaced: list[str] = []
    for ch in text:
        try:
            out += ch.encode(codepage)
        except UnicodeEncodeError:
            out += REPLACEMENT
            if ch not in replaced:
                replaced.append(ch)
    return EncodeResult(bytes(out), replaced)


def encode_line(text: str, codepage: str = PRINTER_CODEPAGE) -> EncodeResult:
    """encode_text 에 줄바꿈(LF)을 붙인다."""
    result = encode_text(text, codepage)
    return EncodeResult(result.data + b"\n", result.replaced)
