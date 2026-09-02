"""사용자에게 그대로 보여줄 수 있는 예외 계층.

원본 예외는 __cause__ 로 남기되, message 는 항상 설치 기사가 읽고
다음 행동을 정할 수 있는 한국어 문장이어야 한다.
"""

from __future__ import annotations


class PosTesterError(Exception):
    """이 프로그램이 사용자에게 보고하는 모든 오류의 기반."""

    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hints: list[str] = hints or []

    def __str__(self) -> str:
        return self.message


class TransportError(PosTesterError):
    """연결·송수신 계층에서 생긴 오류."""


class ConnectionFailed(TransportError):
    """포트/프린터를 열지 못했다."""


class NotConnected(TransportError):
    """연결되지 않은 상태에서 송수신을 시도했다."""

    def __init__(self) -> None:
        super().__init__(
            "아직 연결되지 않았습니다.",
            ["왼쪽 '연결' 버튼을 먼저 눌러 주세요."],
        )


class NoResponse(TransportError):
    """명령은 보냈으나 응답이 오지 않았다."""

    def __init__(self, message: str = "프린터가 응답하지 않습니다.") -> None:
        super().__init__(
            message,
            [
                "통신 속도(baud)가 프린터 설정과 다를 수 있습니다 — '속도 자동탐색'을 눌러 보세요.",
                "일반 시리얼 케이블 대신 크로스(널모뎀) 케이블이 필요한 기종일 수 있습니다.",
                "프린터의 흐름 제어 설정(RTS-CTS / DTR-DSR)과 프로그램 설정이 다를 수 있습니다.",
                "프린터 전원과 케이블 체결 상태를 확인하세요.",
            ],
        )


class WriteOnlyTransport(TransportError):
    """단방향 연결에서 상태 조회를 시도했다."""

    def __init__(self) -> None:
        super().__init__(
            "USB(윈도우 스풀러) 연결은 단방향이라 프린터 상태를 읽을 수 없습니다.",
            ["상태 확인이 필요하면 시리얼(COM) 연결로 전환하세요."],
        )


class EncodingError(PosTesterError):
    """인쇄할 문자열을 프린터 코드페이지로 바꾸지 못했다."""
