"""POS 프린터·금전함 점검 도구."""

from __future__ import annotations

import sys

__version__ = "1.0.0"


def use_utf8_console() -> None:
    """표준 출력·오류를 UTF-8 로 맞춘다.

    Windows 파이썬은 stdout 인코딩을 콘솔 코드페이지(cp1252 / cp949)에서 가져오기
    때문에, 한글을 print 하면 UnicodeEncodeError 로 스크립트가 통째로 죽는다.
    출력 한 줄 때문에 빌드가 실패하는 일이 없도록 진입점마다 이걸 먼저 부른다.

    --windowed 로 빌드하면 stdout 이 아예 없을 수 있으므로 없는 경우도 견딘다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 콘솔이 없거나 다시 설정할 수 없는 스트림이면 그냥 둔다.
            pass
