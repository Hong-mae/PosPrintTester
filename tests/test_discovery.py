"""속도 자동 탐색 로직 검증 (실제 포트 없이)."""

from __future__ import annotations

from typing import Any

import pytest

from pos_tester.core import discovery
from pos_tester.core.discovery import BaudProbe, describe_probes, scan_baudrates
from pos_tester.core.errors import ConnectionFailed


def _fake_probe(responding_baud: int | None) -> Any:
    def probe(port: str, baud: int, flow: Any, timeout: float) -> BaudProbe:
        if baud == responding_baud:
            return BaudProbe(baudrate=baud, responded=True, raw=0x16)
        return BaudProbe(baudrate=baud, responded=False, note="응답 없음")

    return probe


def test_scan_stops_at_first_responding_baud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_probe_one", _fake_probe(38400))
    progress: list[int] = []
    result = scan_baudrates("COM1", on_progress=lambda i, total, baud: progress.append(baud))
    assert result.found
    assert result.baudrate == 38400
    # 38400 에서 찾았으므로 그 뒤 속도는 시도하지 않는다.
    assert progress == [9600, 19200, 38400]


def test_scan_reports_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_probe_one", _fake_probe(None))
    result = scan_baudrates("COM1")
    assert not result.found
    assert result.baudrate is None
    assert len(result.probes) == 5


def test_scan_can_be_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_probe_one", _fake_probe(None))
    seen: list[int] = []
    result = scan_baudrates(
        "COM1",
        on_result=lambda p: seen.append(p.baudrate),
        should_cancel=lambda: len(seen) >= 2,
    )
    assert not result.found
    assert len(result.probes) == 2


def test_probe_treats_garbled_byte_as_no_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTransport:
        def __init__(self, settings: Any) -> None: ...
        def open(self) -> None: ...
        def close(self) -> None: ...
        def query(self, command: bytes, size: int, timeout: float) -> bytes:
            return b"\xff"  # 고정 비트를 만족하지 않는 깨진 바이트

    monkeypatch.setattr(discovery, "SerialTransport", FakeTransport)
    probe = discovery._probe_one("COM1", 9600, discovery.FlowControl.NONE, 0.1)
    assert not probe.responded
    assert "깨진 응답" in probe.note


def test_probe_survives_port_open_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingTransport:
        def __init__(self, settings: Any) -> None: ...
        def open(self) -> None:
            raise ConnectionFailed("포트를 열 수 없습니다.")

    monkeypatch.setattr(discovery, "SerialTransport", FailingTransport)
    probe = discovery._probe_one("COM1", 9600, discovery.FlowControl.NONE, 0.1)
    assert not probe.responded


def test_describe_probes_is_compact() -> None:
    probes = [BaudProbe(9600, False), BaudProbe(19200, True)]
    assert describe_probes(probes) == "9600:× / 19200:○"


def test_port_label_hides_placeholder_description() -> None:
    assert discovery.PortInfo("COM3", "n/a").label == "COM3"
    assert discovery.PortInfo("COM3", "USB Serial").label == "COM3 — USB Serial"


def test_ports_sort_numerically() -> None:
    class P:
        def __init__(self, device: str) -> None:
            self.device = device

    ordered = sorted([P("COM10"), P("COM2"), P("COM1")], key=discovery._port_sort_key)
    assert [p.device for p in ordered] == ["COM1", "COM2", "COM10"]


# --------------------------------------------------------------------------
# 레지스트리 보완 (SetupAPI 가 놓치는 COM 포트)
# --------------------------------------------------------------------------
class _FakePort:
    def __init__(self, device: str, description: str = "") -> None:
        self.device = device
        self.description = description


def test_registry_ports_fill_gaps_setupapi_missed(monkeypatch: pytest.MonkeyPatch) -> None:
    """POS 메인보드 내장 시리얼처럼 '포트' 장치 클래스에 없는 포트도 보여야 한다."""
    monkeypatch.setattr(
        discovery, "registry_serial_ports", lambda: [discovery.PortInfo("COM5", "Serial1 (레지스트리)")]
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "serial.tools.list_ports",
        type("M", (), {"comports": staticmethod(lambda: [_FakePort("COM3", "USB Serial")])}),
    )
    devices = [p.device for p in discovery.list_serial_ports()]
    assert devices == ["COM3", "COM5"]


def test_registry_does_not_override_setupapi_description(monkeypatch: pytest.MonkeyPatch) -> None:
    """양쪽에 다 있으면 설명이 풍부한 comports() 쪽을 남긴다."""
    monkeypatch.setattr(
        discovery, "registry_serial_ports", lambda: [discovery.PortInfo("COM3", "Serial0 (레지스트리)")]
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "serial.tools.list_ports",
        type("M", (), {"comports": staticmethod(lambda: [_FakePort("COM3", "USB Serial")])}),
    )
    ports = discovery.list_serial_ports()
    assert len(ports) == 1
    assert ports[0].description == "USB Serial"


def test_registry_ports_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """com3 과 COM3 을 다른 포트로 중복 표시하지 않는다."""
    monkeypatch.setattr(
        discovery, "registry_serial_ports", lambda: [discovery.PortInfo("com3", "Serial0")]
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "serial.tools.list_ports",
        type("M", (), {"comports": staticmethod(lambda: [_FakePort("COM3", "USB Serial")])}),
    )
    assert len(discovery.list_serial_ports()) == 1


def test_registry_lookup_survives_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """레지스트리 조회가 실패해도 보조 수단이므로 예외를 내지 않는다."""
    import sys

    fake_winreg = type(
        "W",
        (),
        {
            "HKEY_LOCAL_MACHINE": 0,
            "OpenKey": staticmethod(lambda *a, **k: (_ for _ in ()).throw(OSError("없음"))),
        },
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert discovery.registry_serial_ports() == []
