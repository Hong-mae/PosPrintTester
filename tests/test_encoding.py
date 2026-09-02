"""cp949 인코딩과 대체 문자 처리 검증."""

from __future__ import annotations

from pos_tester.core.encoding import encode_line, encode_text


def test_ascii_passes_through() -> None:
    result = encode_text("ABC 123")
    assert result.data == b"ABC 123"
    assert not result.had_replacements


def test_hangul_uses_cp949() -> None:
    result = encode_text("한글")
    assert result.data == "한글".encode("cp949")
    assert not result.had_replacements


def test_unencodable_char_is_replaced_not_raised() -> None:
    # 이모지는 cp949 에 없다. 예외 대신 '?' 로 바뀌어야 한다.
    result = encode_text("가나🙂다라")
    assert b"?" in result.data
    assert result.replaced == ["🙂"]
    assert result.data.decode("cp949") == "가나?다라"


def test_replaced_list_is_deduplicated() -> None:
    assert encode_text("🙂🙂🙂").replaced == ["🙂"]


def test_encode_line_appends_lf() -> None:
    assert encode_line("A").data == b"A\n"
