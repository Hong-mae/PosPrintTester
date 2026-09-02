"""MockTransport 로 전체 시나리오를 하드웨어 없이 검증한다."""

from __future__ import annotations

import pytest

from pos_tester.core import escpos as e
from pos_tester.core.errors import NotConnected, WriteOnlyTransport
from pos_tester.core.tester import DRAWER_CHECKLIST, DRAWER_SENSOR_NOTES, PrinterTester
from pos_tester.core.transport import (
    MockState,
    MockTransport,
    Transport,
    WinSpoolerTransport,
)


@pytest.fixture()
def mock() -> MockTransport:
    transport = MockTransport()
    transport.open()
    return transport


@pytest.fixture()
def tester(mock: MockTransport) -> PrinterTester:
    return PrinterTester(mock)


# --------------------------------------------------------------------------
# Transport 기본 동작
# --------------------------------------------------------------------------
def test_write_before_open_raises_readable_error() -> None:
    with pytest.raises(NotConnected) as info:
        MockTransport().write(b"\x1b\x40")
    assert "연결" in info.value.message


def test_context_manager_opens_and_closes() -> None:
    transport = MockTransport()
    with transport:
        assert transport.is_open
    assert not transport.is_open


def test_spooler_is_write_only() -> None:
    transport: Transport = WinSpoolerTransport("가상 프린터")
    assert not transport.supports_read
    with pytest.raises(WriteOnlyTransport):
        transport.query_status(e.StatusKind.PRINTER)


# --------------------------------------------------------------------------
# 상태 조회
# --------------------------------------------------------------------------
def test_status_query_returns_valid_byte(mock: MockTransport) -> None:
    report = mock.query_status(e.StatusKind.PRINTER)
    assert report.well_formed
    assert report.ok


def test_cover_open_is_reported(mock: MockTransport, tester: PrinterTester) -> None:
    mock.state.cover_open = True
    result = tester.read_status()
    assert not result.ok
    assert "커버" in " ".join(f.label for r in result.reports for f in r.flags)
    assert "열림" in result.detail


def test_paper_end_is_reported(tester: PrinterTester, mock: MockTransport) -> None:
    mock.state.paper_end = True
    result = tester.read_status()
    assert not result.ok
    paper = [f for r in result.reports for f in r.flags if f.label == "용지"]
    assert any(f.detail == "없음" for f in paper)


def test_cutter_error_is_reported(tester: PrinterTester, mock: MockTransport) -> None:
    mock.state.cutter_error = True
    result = tester.read_status()
    assert not result.ok
    assert "절단기" in " ".join(
        f.label for r in result.reports for f in r.flags if not f.ok
    )


# --------------------------------------------------------------------------
# 연결 테스트
# --------------------------------------------------------------------------
def test_connection_test_sends_esc_at_first(tester: PrinterTester, mock: MockTransport) -> None:
    result = tester.connection_test()
    assert result.ok
    assert mock.received.startswith(b"\x1b\x40")
    assert len(result.reports) == 4


def test_connection_test_on_write_only_transport_explains_limitation() -> None:
    class WriteOnlyMock(MockTransport):
        supports_read = False

    transport = WriteOnlyMock()
    transport.open()
    result = PrinterTester(transport).connection_test()
    assert result.ok  # 전송 자체는 성공
    assert "단방향" in result.detail
    assert result.hints


# --------------------------------------------------------------------------
# 출력 테스트
# --------------------------------------------------------------------------
def test_print_test_enters_and_leaves_multibyte_mode(
    tester: PrinterTester, mock: MockTransport
) -> None:
    tester.print_test()
    data = bytes(mock.received)
    assert b"\x1c\x26" in data  # FS &
    assert b"\x1c\x2e" in data  # FS .
    assert data.index(b"\x1c\x26") < data.index(b"\x1c\x2e")


def test_print_test_covers_every_required_element(
    tester: PrinterTester, mock: MockTransport
) -> None:
    tester.print_test()
    printed = "\n".join(mock.printed_lines)
    assert "한글" in printed
    assert "ABCDEFG" in printed
    assert "0123456789" in printed
    assert "1,234,567원" in printed  # 금액 포맷
    assert "왼쪽 정렬" in printed and "가운데 정렬" in printed and "오른쪽 정렬" in printed
    assert "굵게" in printed and "밑줄" in printed
    assert "가로 2배" in printed and "세로 2배" in printed
    assert "-" * 10 in printed  # 구분선

    data = bytes(mock.received)
    assert b"\x1b\x45\x01" in data  # 굵게 ON
    assert b"\x1b\x2d\x01" in data  # 밑줄 ON
    assert b"\x1d\x21\x10" in data  # 가로 2배
    assert b"\x1d\x21\x01" in data  # 세로 2배


def test_print_test_cuts_paper_at_the_end(tester: PrinterTester, mock: MockTransport) -> None:
    tester.print_test(cut_after=True, feed_lines=4)
    assert mock.cuts == [(e.CutMode.FULL, 4)]


def test_print_test_can_skip_cut(tester: PrinterTester, mock: MockTransport) -> None:
    tester.print_test(cut_after=False)
    assert mock.cuts == []


def test_amount_rows_fit_the_paper_width(tester: PrinterTester) -> None:
    from pos_tester.core.tester import _WIDTH, _amount_row, _display_width

    for label, amount in [("상품 A", 1_200), ("합    계", 1_270_267)]:
        assert _display_width(_amount_row(label, amount)) == _WIDTH


# --------------------------------------------------------------------------
# 금전함
# --------------------------------------------------------------------------
@pytest.mark.parametrize("pin", [e.DrawerPin.PIN_2, e.DrawerPin.PIN_5])
def test_drawer_kick_opens_drawer(
    tester: PrinterTester, mock: MockTransport, pin: e.DrawerPin
) -> None:
    result = tester.drawer_test(pin, verify_timeout=0.3)
    assert result.ok
    assert mock.kicks == [(pin, False)]
    assert "열림" in result.detail


def test_realtime_kick_uses_dle_dc4(tester: PrinterTester, mock: MockTransport) -> None:
    result = tester.drawer_test(e.DrawerPin.PIN_2, realtime=True, verify_timeout=0.3)
    assert result.ok
    assert mock.kicks == [(e.DrawerPin.PIN_2, True)]
    assert b"\x10\x14\x01\x00" in bytes(mock.received)


def test_no_sensor_is_a_warning_not_a_failure(tester: PrinterTester, mock: MockTransport) -> None:
    """열림 감지 스위치가 없는 금전함은 아주 흔하다.

    서랍은 멀쩡히 열리므로 실패로 판정하면 안 된다. 실패로 몰면 기사가
    정상 장비를 고장으로 오해하고 엉뚱한 곳을 뜯게 된다.
    """
    mock.state.drawer_sensor_wired = False
    result = tester.drawer_test(e.DrawerPin.PIN_2, verify_timeout=0.3)
    assert result.ok  # 실패가 아니다
    assert result.warning  # 다만 눈으로 확인해야 한다
    assert "감지" in result.detail
    # 안내가 '열렸다면' 과 '안 열렸다면' 두 갈래를 모두 담고 있어야 한다.
    assert result.hints[: len(DRAWER_SENSOR_NOTES)] == list(DRAWER_SENSOR_NOTES)
    assert all(item in result.hints for item in DRAWER_CHECKLIST)
    assert any("24V" in hint for hint in result.hints)


def test_inverted_sensor_polarity_is_detected(tester: PrinterTester, mock: MockTransport) -> None:
    """NC 스위치를 쓰는 금전함은 열림이 HIGH 로 나온다.

    ESC/POS 규격은 핀3 의 레벨만 정의하고 어느 쪽이 열림인지는 정하지 않으므로
    레벨을 고정 해석하면 안 되고 킥 전후 변화를 봐야 한다.
    """
    mock.state.drawer_sensor_inverted = True
    result = tester.drawer_test(e.DrawerPin.PIN_2, verify_timeout=0.3)
    assert result.ok
    assert not result.warning
    assert "극성" in result.detail


def test_drawer_that_does_not_open_is_reported_as_unverified(
    tester: PrinterTester, mock: MockTransport
) -> None:
    """서랍이 안 열린 경우와 센서가 없는 경우는 핀3 만으로 구분할 수 없다.

    그래서 단정하지 않고 눈으로 확인하도록 안내한다.
    """
    mock.state.drawer_connected = False
    result = tester.drawer_test(e.DrawerPin.PIN_2, verify_timeout=0.3)
    assert result.warning
    assert "눈으로 확인" in result.detail
    assert any("안 열려요" in hint for hint in result.hints)


def test_already_open_drawer_is_distinguished_from_missing_sensor(mock: MockTransport) -> None:
    """센서가 동작하는 걸 한 번 본 뒤에는 '이미 열려 있음' 을 구분할 수 있다."""
    mock.state.drawer_open_seconds = 60.0  # 첫 킥 뒤 계속 열린 채로 둔다
    tester = PrinterTester(mock)

    first = tester.drawer_test(e.DrawerPin.PIN_2, verify_timeout=0.3)
    assert first.ok and not first.warning

    second = tester.drawer_test(e.DrawerPin.PIN_5, verify_timeout=0.3)
    assert second.ok
    assert second.warning
    assert "이미 열려" in second.detail


def test_write_only_transport_kick_is_a_warning() -> None:
    """단방향 연결에서는 열렸는지 알 수 없으므로 경고로 둔다."""

    class WriteOnlyMock(MockTransport):
        supports_read = False

    transport = WriteOnlyMock()
    transport.open()
    result = PrinterTester(transport).drawer_test(e.DrawerPin.PIN_2)
    assert result.ok
    assert result.warning
    assert "단방향" in result.detail


def test_drawer_state_returns_to_closed(mock: MockTransport, tester: PrinterTester) -> None:
    mock.state.drawer_open_seconds = 0.0
    tester.drawer_test(e.DrawerPin.PIN_2, verify_timeout=0.3)
    assert not mock.state.drawer_open


def test_mock_pin3_stays_high_without_sensor() -> None:
    """센서선이 없으면 서랍이 열려도 핀3 는 계속 HIGH 다."""
    transport = MockTransport(state=MockState(drawer_sensor_wired=False))
    transport.open()
    transport.write(e.drawer_kick(e.DrawerPin.PIN_2))
    assert transport.state.drawer_open  # 서랍은 실제로 열렸다
    report = transport.query_status(e.StatusKind.PRINTER)
    assert e.drawer_pin3_high(report.raw)  # 그런데 감지는 안 된다


# --------------------------------------------------------------------------
# 용지 절단 · 피드
# --------------------------------------------------------------------------
def test_full_cut(tester: PrinterTester, mock: MockTransport) -> None:
    assert tester.cut(e.CutMode.FULL).ok
    assert mock.cuts == [(e.CutMode.FULL, 0)]


def test_partial_cut(tester: PrinterTester, mock: MockTransport) -> None:
    assert tester.cut(e.CutMode.PARTIAL).ok
    assert mock.cuts == [(e.CutMode.PARTIAL, 0)]


def test_feed_then_cut(tester: PrinterTester, mock: MockTransport) -> None:
    result = tester.cut(e.CutMode.FULL, feed_lines=5)
    assert result.ok
    assert mock.cuts == [(e.CutMode.FULL, 5)]
    assert "5줄 피드 후 전체 절단" == result.title


def test_feed_only(tester: PrinterTester, mock: MockTransport) -> None:
    assert tester.feed(3).ok
    assert b"\x1b\x64\x03" in bytes(mock.received)


# --------------------------------------------------------------------------
# RAW 전송
# --------------------------------------------------------------------------
def test_send_raw_forwards_bytes(tester: PrinterTester, mock: MockTransport) -> None:
    result = tester.send_raw(e.parse_hex("1B 40"))
    assert result.ok
    assert bytes(mock.received) == b"\x1b\x40"


def test_send_raw_shows_status_reply(tester: PrinterTester) -> None:
    result = tester.send_raw(e.parse_hex("10 04 01"))
    assert result.ok
    assert "응답" in result.detail


def test_send_raw_rejects_empty(tester: PrinterTester) -> None:
    result = tester.send_raw(b"")
    assert not result.ok


# --------------------------------------------------------------------------
# 전체 테스트
# --------------------------------------------------------------------------
def test_run_all_executes_every_step(tester: PrinterTester, mock: MockTransport) -> None:
    steps: list[str] = []
    results = tester.run_all(on_step=lambda i, total, label: steps.append(label))
    assert len(results) == 5
    assert steps == [
        "연결 테스트",
        "출력 테스트",
        "금전함 2번 핀",
        "금전함 5번 핀",
        "용지 절단",
    ]
    assert all(r.ok for r in results)
    assert len(mock.kicks) == 2
    assert mock.cuts == [(e.CutMode.FULL, 4)]


def test_run_all_can_be_cancelled(tester: PrinterTester) -> None:
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    results = tester.run_all(should_cancel=cancel)
    assert len(results) < 5


def test_run_all_reports_failure_without_raising(mock: MockTransport) -> None:
    mock.state.cover_open = True
    results = PrinterTester(mock).run_all()
    assert not results[0].ok  # 연결 테스트에서 커버 열림이 잡힌다
    assert len(results) == 5  # 실패해도 나머지 단계는 계속 돈다


# --------------------------------------------------------------------------
# 로그 콜백
# --------------------------------------------------------------------------
def test_log_callback_receives_levels(mock: MockTransport) -> None:
    entries: list[tuple[str, str]] = []
    PrinterTester(mock, log=lambda level, msg: entries.append((level, msg))).connection_test()
    assert entries
    assert {level for level, _ in entries} <= {"info", "ok", "warn", "error"}
