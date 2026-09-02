"""POSTester 진입점.

POS 단말기용 ESC/POS 프린터 · 금전함 점검 도구.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from pos_tester import __version__, use_utf8_console
from pos_tester.ui.main_window import MainWindow, build_stylesheet
from pos_tester.ui.tokens import FONT_CANDIDATES, TYPE


def _resource_path(name: str) -> Path | None:
    """번들 안, 소스 트리, build/ 순으로 리소스를 찾는다. 없으면 None."""
    bundle = getattr(sys, "_MEIPASS", None)
    roots = [Path(bundle)] if bundle else []
    roots += [Path(__file__).parent, Path(__file__).parent / "build"]
    for root in roots:
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def _pick_font_family() -> str:
    """설치된 한글 폰트 중 우선순위가 가장 높은 것을 고른다.

    윈도우에서는 Malgun Gothic 이 항상 잡히고, 리눅스에서 개발·검증할 때는
    Noto Sans KR / 나눔고딕으로 내려간다.
    """
    available = set(QFontDatabase.families())
    for family in FONT_CANDIDATES:
        if family in available:
            return family
    return FONT_CANDIDATES[0]


def _install_excepthook(app: QApplication) -> None:
    """예상 못 한 예외를 조용히 죽이지 말고 사용자에게 보여 준다."""

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(detail)
        box = QMessageBox()
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("예상치 못한 오류")
        box.setText("프로그램에서 처리하지 못한 오류가 발생했습니다.")
        box.setInformativeText(str(exc))
        box.setDetailedText(detail)
        box.exec()

    sys.excepthook = hook


def main() -> int:
    use_utf8_console()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    app = QApplication(sys.argv)
    app.setApplicationName("POSTester")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("POSTester")

    # 한글이 깨지지 않도록 설치된 한글 폰트를 직접 고른다.
    font = QFont(_pick_font_family(), TYPE["body"])
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    icon_path = _resource_path("icon.ico")
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))  # 없어도 실행에는 지장이 없다.

    app.setStyleSheet(build_stylesheet())
    _install_excepthook(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
