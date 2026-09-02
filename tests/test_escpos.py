"""core/escpos.py 의 명령 생성과 비트 해석 검증."""

from __future__ import annotations

import pytest

from pos_tester.core import escpos as e


# --------------------------------------------------------------------------
# 명령 생성
# --------------------------------------------------------------------------
def test_initialize_is_esc_at() -> None:
    assert e.initialize() == b"\x1b\x40"


def test_multibyte_mode_commands() -> None:
    assert e.select_multibyte_mode() == b"\x1c\x26"  # FS &
    assert e.cancel_multibyte_mode() == b"\x1c\x2e"  # FS .


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (e.StatusKind.PRINTER, b"\x10\x04\x01"),
        (e.StatusKind.OFFLINE_CAUSE, b"\x10\x04\x02"),
        (e.StatusKind.ERROR_CAUSE, b"\x10\x04\x03"),
        (e.StatusKind.PAPER_SENSOR, b"\x10\x04\x04"),
    ],
)
def test_status_query_bytes(kind: e.StatusKind, expected: bytes) -> None:
    assert e.status_query(kind) == expected


def test_drawer_kick_matches_spec() -> None:
    # 사양서의 1B 70 00 19 FA (2번 핀, on 50ms / off 500ms)
    assert e.drawer_kick(e.DrawerPin.PIN_2, 50, 500) == b"\x1b\x70\x00\x19\xfa"
    assert e.drawer_kick(e.DrawerPin.PIN_5, 50, 500) == b"\x1b\x70\x01\x19\xfa"


def test_drawer_kick_clamps_long_pulse() -> None:
    # 2ms 단위이므로 510ms 를 넘으면 255 로 잘린다.
    assert e.drawer_kick(e.DrawerPin.PIN_2, 5000, 5000)[3:] == b"\xff\xff"


def test_drawer_kick_rejects_negative_time() -> None:
    with pytest.raises(ValueError):
        e.drawer_kick(e.DrawerPin.PIN_2, -1, 500)


def test_drawer_kick_realtime_matches_spec() -> None:
    # 사양서의 10 14 01 00 02 (리얼타임, 버퍼 무시)
    assert e.drawer_kick_realtime(e.DrawerPin.PIN_2, 200) == b"\x10\x14\x01\x00\x02"
    assert e.drawer_kick_realtime(e.DrawerPin.PIN_5, 200) == b"\x10\x14\x01\x01\x02"


def test_drawer_kick_realtime_clamps_t() -> None:
    assert e.drawer_kick_realtime(e.DrawerPin.PIN_2, 0)[4] == 1
    assert e.drawer_kick_realtime(e.DrawerPin.PIN_2, 9999)[4] == 8


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(e.CutMode.FULL, b"\x1d\x56\x00"), (e.CutMode.PARTIAL, b"\x1d\x56\x01")],
)
def test_cut(mode: e.CutMode, expected: bytes) -> None:
    assert e.cut(mode) == expected


def test_feed_and_cut() -> None:
    assert e.feed_and_cut(3, e.CutMode.FULL) == b"\x1d\x56\x42\x03"
    assert e.feed_and_cut(5, e.CutMode.PARTIAL) == b"\x1d\x56\x43\x05"


def test_feed_and_cut_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        e.feed_and_cut(256)


def test_feed() -> None:
    assert e.feed(3) == b"\x1b\x64\x03"
    with pytest.raises(ValueError):
        e.feed(300)


def test_align() -> None:
    assert e.align(e.Align.LEFT) == b"\x1b\x61\x00"
    assert e.align(e.Align.CENTER) == b"\x1b\x61\x01"
    assert e.align(e.Align.RIGHT) == b"\x1b\x61\x02"


def test_bold_and_underline() -> None:
    assert e.bold(True) == b"\x1b\x45\x01"
    assert e.bold(False) == b"\x1b\x45\x00"
    assert e.underline(True) == b"\x1b\x2d\x01"
    assert e.underline(True, thick=True) == b"\x1b\x2d\x02"
    assert e.underline(False) == b"\x1b\x2d\x00"


def test_text_size_packs_width_high_nibble() -> None:
    assert e.text_size(1, 1) == b"\x1d\x21\x00"
    assert e.text_size(2, 1) == b"\x1d\x21\x10"  # 가로 2배
    assert e.text_size(1, 2) == b"\x1d\x21\x01"  # 세로 2배
    assert e.text_size(2, 2) == b"\x1d\x21\x11"


@pytest.mark.parametrize(("w", "h"), [(0, 1), (1, 0), (9, 1), (1, 9)])
def test_text_size_rejects_out_of_range(w: int, h: int) -> None:
    with pytest.raises(ValueError):
        e.text_size(w, h)


# --------------------------------------------------------------------------
# 상태 바이트 형식
# --------------------------------------------------------------------------
def test_valid_status_byte_fixed_bits() -> None:
    # bit1 과 bit4 는 1, bit0 과 bit7 은 0 이어야 한다.
    assert e.is_valid_status_byte(0x12)
    assert e.is_valid_status_byte(0x16)
    assert not e.is_valid_status_byte(0x00)
    assert not e.is_valid_status_byte(0x13)  # bit0 이 1
    assert not e.is_valid_status_byte(0x92)  # bit7 이 1
    assert not e.is_valid_status_byte(0x02)  # bit4 가 0


def test_decode_marks_malformed_response() -> None:
    report = e.decode_status(e.StatusKind.PRINTER, 0xFF)
    assert not report.well_formed
    assert not report.ok
    assert "올바르지 않은" in report.summary()


def test_decode_rejects_non_byte() -> None:
    with pytest.raises(ValueError):
        e.decode_status(e.StatusKind.PRINTER, 256)


# --------------------------------------------------------------------------
# DLE EOT 1 — 프린터 상태
# --------------------------------------------------------------------------
def _flag(report: e.StatusReport, label: str) -> e.StatusFlag:
    return next(f for f in report.flags if f.label == label)


def test_printer_status_all_normal() -> None:
    report = e.decode_status(e.StatusKind.PRINTER, 0x16)  # bit2 셋 = 금전함 닫힘
    assert report.ok
    assert _flag(report, "금전함").detail == "닫힘 (또는 센서 없음)"
    assert _flag(report, "프린터").detail == "온라인"
    assert _flag(report, "커버").detail == "닫힘"


def test_pin3_helper_reads_bit2() -> None:
    assert e.drawer_pin3_high(0x16)      # bit2 셋
    assert not e.drawer_pin3_high(0x12)  # bit2 클리어


def test_printer_status_drawer_open_when_bit2_clear() -> None:
    report = e.decode_status(e.StatusKind.PRINTER, 0x12)
    assert _flag(report, "금전함").detail == "열림"
    # 금전함이 열린 것 자체는 오류가 아니다.
    assert report.ok


def test_printer_status_offline_bit3() -> None:
    report = e.decode_status(e.StatusKind.PRINTER, 0x16 | 0x08)
    assert _flag(report, "프린터").detail == "오프라인"
    assert not report.ok


def test_printer_status_cover_open_bit5() -> None:
    report = e.decode_status(e.StatusKind.PRINTER, 0x16 | 0x20)
    assert _flag(report, "커버").detail == "열림"
    assert not report.ok


def test_printer_status_feed_button_bit6() -> None:
    report = e.decode_status(e.StatusKind.PRINTER, 0x16 | 0x40)
    assert _flag(report, "피드 버튼").detail == "눌림"
    assert not report.ok


# --------------------------------------------------------------------------
# DLE EOT 2~4
# --------------------------------------------------------------------------
def test_offline_cause_bits() -> None:
    assert _flag(e.decode_status(e.StatusKind.OFFLINE_CAUSE, 0x12 | 0x04), "커버").detail == "열림"
    assert not _flag(e.decode_status(e.StatusKind.OFFLINE_CAUSE, 0x12 | 0x08), "피드 버튼").ok
    assert not _flag(e.decode_status(e.StatusKind.OFFLINE_CAUSE, 0x12 | 0x20), "용지").ok
    assert not _flag(e.decode_status(e.StatusKind.OFFLINE_CAUSE, 0x12 | 0x40), "에러").ok
    assert e.decode_status(e.StatusKind.OFFLINE_CAUSE, 0x12).ok


def test_error_cause_cutter_bit3() -> None:
    report = e.decode_status(e.StatusKind.ERROR_CAUSE, 0x12 | 0x08)
    assert _flag(report, "절단기").detail == "에러"
    assert not report.ok


def test_error_cause_unrecoverable_bit5() -> None:
    report = e.decode_status(e.StatusKind.ERROR_CAUSE, 0x12 | 0x20)
    assert "전원 재투입" in _flag(report, "복구 불가 에러").detail


def test_paper_sensor_levels() -> None:
    assert _flag(e.decode_status(e.StatusKind.PAPER_SENSOR, 0x12), "용지").detail == "충분"
    near = e.decode_status(e.StatusKind.PAPER_SENSOR, 0x12 | 0x0C)
    assert _flag(near, "용지").detail == "거의 없음"
    end = e.decode_status(e.StatusKind.PAPER_SENSOR, 0x12 | 0x0C | 0x60)
    assert _flag(end, "용지").detail == "없음"
    assert not end.ok


# --------------------------------------------------------------------------
# 16진 파싱
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["1B 40", "1b40", "0x1B 0x40", "1B,40", "1B-40", "  1B   40  "],
)
def test_parse_hex_accepts_common_formats(text: str) -> None:
    assert e.parse_hex(text) == b"\x1b\x40"


@pytest.mark.parametrize("text", ["", "   ", "ZZ", "1B 4G", "1B4"])
def test_parse_hex_rejects_bad_input(text: str) -> None:
    with pytest.raises(ValueError):
        e.parse_hex(text)


def test_to_hex_truncates_long_data() -> None:
    assert e.to_hex(b"\x1b\x40") == "1B 40"
    assert "총 100바이트" in e.to_hex(b"\x00" * 100)
