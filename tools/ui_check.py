"""하드웨어 없이 UI 전체 플로우를 돌려 보는 검증 스크립트.

가상 프린터(MockTransport)로 연결부터 전체 테스트까지 실제로 클릭해 보고,
1024x768 에서 잘리는 곳이 없는지, 터치 타깃 높이와 버튼 색이 의도대로
그려지는지 확인한다. 단계마다 스크린샷을 남긴다.

    # 리눅스 (가상 디스플레이 필요)
    xvfb-run -a python tools/ui_check.py

    # 윈도우
    python tools\\ui_check.py

성공하면 종료 코드 0, 하나라도 실패하면 1 을 돌려준다.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import main as entry  # noqa: E402
from pos_tester import use_utf8_console  # noqa: E402
from pos_tester.core.escpos import CutMode  # noqa: E402
from pos_tester.ui.main_window import MainWindow, build_stylesheet  # noqa: E402
from pos_tester.ui.tokens import BASE_HEIGHT, BASE_WIDTH, COLORS, TYPE  # noqa: E402

OUT_DIR = Path(os.environ.get("UI_CHECK_OUT", ROOT / "build" / "screenshots"))

problems: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("  OK   " if condition else "  FAIL ") + message)
    if not condition:
        problems.append(message)


def main() -> int:
    use_utf8_console()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setFont(QFont(entry._pick_font_family(), TYPE["body"]))
    app.setStyleSheet(build_stylesheet())

    window = MainWindow()
    window.resize(BASE_WIDTH, BASE_HEIGHT)
    window.show()

    def pump(seconds: float) -> None:
        """워커 스레드의 시그널이 UI 로 전달될 시간을 준다."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    def shot(name: str) -> None:
        pump(0.4)
        window.grab().save(str(OUT_DIR / f"{name}.png"))

    print("1) 초기 화면 — 1024x768 에서 잘리지 않는가")
    pump(0.8)
    shot("01_initial")
    layout = window.centralWidget().layout()
    check(
        layout.minimumSize().height() <= BASE_HEIGHT,
        f"최소 내용 높이 {layout.minimumSize().height()} <= {BASE_HEIGHT}",
    )
    check(
        layout.minimumSize().width() <= BASE_WIDTH,
        f"최소 내용 너비 {layout.minimumSize().width()} <= {BASE_WIDTH}",
    )

    print("2) 터치 타깃 크기")
    for name, widget in [
        ("연결", window.connection_panel.connect_button),
        ("연결 테스트", window.action_panel.connection_button),
        ("2번 핀 열기", window.action_panel.pin2_button),
        ("전체 절단", window.action_panel.cut_full_button),
        ("전체 테스트", window.action_panel.run_all_button),
    ]:
        check(widget.height() >= 56, f"{name} 높이 {widget.height()}px >= 56px")
    check(
        window.connection_panel.mode_combo.height() >= 44,
        f"콤보 높이 {window.connection_panel.mode_combo.height()}px >= 44px",
    )

    print("3) 버튼 변형별 실제 렌더 색 (QSS 우선순위 회귀 방지)")
    image = window.grab().toImage()

    def color_at(widget: object, dy: int) -> str:
        top_left = widget.mapTo(window, widget.rect().topLeft())  # type: ignore[attr-defined]
        x = top_left.x() + widget.width() // 2  # type: ignore[attr-defined]
        return image.pixelColor(x, top_left.y() + dy).name().lower()

    primary_bg = color_at(window.connection_panel.connect_button, 10)
    default_bg = color_at(window.action_panel.connection_button, 10)
    danger_border = color_at(window.action_panel.run_all_button, 1)
    danger_bg = color_at(window.action_panel.run_all_button, 10)
    check(primary_bg == COLORS["accent"].lower(), f"주요 버튼 배경 {primary_bg} == 액센트")
    check(default_bg == COLORS["bg-raised"].lower(), f"기본 버튼 배경 {default_bg}")
    check(danger_border == COLORS["warn"].lower(), f"위험 버튼 테두리 {danger_border} == 경고색")
    check(danger_bg == COLORS["bg-card"].lower(), f"위험 버튼은 색을 채우지 않음 {danger_bg}")

    print("4) 가상 프린터로 연결")
    window.connection_panel.mode_combo.setCurrentIndex(2)
    pump(0.3)
    check(window.connection_panel.mode == "mock", "가상 프린터 모드")
    window.connection_panel.connect_button.click()
    pump(1.2)
    check(window.worker.is_connected, "연결됨")
    check(window.header.title.text() == "연결됨", f"상단 상태 '{window.header.title.text()}'")
    shot("02_connected")

    print("5) 연결 테스트 — 상태 4종 조회와 램프 반영")
    window.action_panel.connection_button.click()
    pump(1.5)
    check(window.status_panel.lamps["printer"].value.text() == "온라인", "프린터 램프 = 온라인")
    check(window.status_panel.lamps["paper"].value.text() == "충분", "용지 램프 = 충분")
    check(window.status_panel.lamps["cutter"].value.text() == "정상", "절단기 램프 = 정상")
    shot("03_connection_test")

    mock = window.worker.transport

    print("6) 출력 테스트 — 한글·금액·절단")
    window.action_panel.print_button.click()
    pump(1.5)
    printed = "\n".join(mock.printed_lines)
    check("한글" in printed, "영수증에 한글 포함")
    check("1,234,567원" in printed, "금액 포맷 포함")
    check(b"\x1c\x26" in bytes(mock.received), "FS & 다국어 모드 진입")
    check(len(mock.cuts) == 1, f"출력 끝에 절단 1건 ({mock.cuts})")
    shot("04_print_test")

    print("7) 금전함 킥")
    window.action_panel.pin2_button.click()
    pump(1.5)
    check(len(mock.kicks) == 1, f"킥 {len(mock.kicks)}건")
    shot("05_drawer_kick")

    print("8) 커버 열림이 램프에 반영되는가")
    mock.state.cover_open = True
    window.action_panel.status_button.click()
    pump(1.5)
    check(window.status_panel.lamps["cover"].value.text() == "열림", "커버 램프 = 열림")
    shot("06_cover_open")
    mock.state.cover_open = False

    print("9) 용지 절단 — 피드 줄 수가 명령에 반영되는가")
    before = len(mock.cuts)
    window.action_panel.feed_cut_button.click()
    pump(1.2)
    check(len(mock.cuts) == before + 1, f"절단 누적 {len(mock.cuts)}건")
    check(mock.cuts[-1] == (CutMode.FULL, window.action_panel.feed_lines), f"마지막 절단 {mock.cuts[-1]}")
    shot("07_cut")

    print("10) RAW 16진 전송")
    window.action_panel.raw_panel.input.setText("10 04 01")
    window.action_panel.raw_panel.send_button.click()
    pump(1.2)
    shot("08_raw")

    print("11) USB(단방향) 모드에서 상태 조회가 잠기는가")
    window.connection_panel.connect_button.click()  # 연결 끊기
    pump(0.8)
    window.connection_panel.mode_combo.setCurrentIndex(1)
    pump(0.4)
    check(not window.action_panel.status_button.isEnabled(), "상태 새로고침 잠김")
    check(not window.connection_panel.baud_combo.isEnabled(), "속도 콤보 잠김")
    check(bool(window.status_panel.note.text()), "잠긴 이유가 화면에 표시됨")
    shot("09_usb_mode")

    print("12) 전체 테스트 순차 실행")
    window.connection_panel.mode_combo.setCurrentIndex(2)
    pump(0.3)
    window.connection_panel.connect_button.click()
    pump(1.0)
    QMessageBox.question = staticmethod(  # type: ignore[assignment]
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    window.action_panel.run_all_button.click()
    pump(5.0)
    mock = window.worker.transport
    check(len(mock.kicks) == 2, f"금전함 2회 킥 (실제 {len(mock.kicks)})")
    check(len(mock.cuts) >= 1, f"절단 {len(mock.cuts)}건")
    shot("10_run_all")

    print("13) 로그")
    log = window.log_view.plain_text()
    check("연결됨" in log, "로그에 연결 기록")
    check("1B 70 00 19 FA" in log, "로그에 금전함 킥 바이트 기록")

    print("14) 전체화면 토글 (F11)")
    window.toggle_fullscreen()
    pump(0.5)
    check(window.isFullScreen(), "전체화면 진입")
    window.toggle_fullscreen()
    pump(0.5)
    check(not window.isFullScreen(), "전체화면 해제")

    window.close()
    pump(0.4)

    print()
    print(f"스크린샷: {OUT_DIR}")
    if problems:
        print(f"결과: {len(problems)}건 실패")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("결과: 모두 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
