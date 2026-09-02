"""POSTester 아이콘(.ico) 생성기.

별도 디자인 파일 없이 빌드할 수 있도록 코드로 그린다.
색은 ui/tokens.py 의 팔레트를 그대로 쓴다.

    python build/make_icon.py            # build/icon.ico 생성
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from pos_tester import use_utf8_console  # noqa: E402
from pos_tester.ui.tokens import COLORS  # noqa: E402

#: ICO 안에 담을 크기들. 작업 표시줄·바탕화면·탐색기가 각각 다른 크기를 쓴다.
SIZES = (16, 24, 32, 48, 64, 128, 256)
CANVAS = 256


def draw_icon() -> Image.Image:
    """256px 원본을 그린다. 영수증이 나오는 프린터 모양."""
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    bg = COLORS["bg-card"]
    accent = COLORS["accent"]
    paper = COLORS["text"]
    line = COLORS["text-mute"]

    # 배경: 둥근 사각형
    draw.rounded_rectangle((8, 8, CANVAS - 8, CANVAS - 8), radius=48, fill=bg, outline=accent, width=6)

    # 프린터 본체
    draw.rounded_rectangle((46, 116, 210, 196), radius=14, fill=accent)
    # 프린터 앞면 슬릿
    draw.rounded_rectangle((66, 178, 190, 188), radius=5, fill=bg)

    # 위로 나오는 영수증
    draw.rounded_rectangle((72, 44, 184, 128), radius=8, fill=paper)
    for index in range(4):
        y = 64 + index * 16
        width = 84 if index % 2 == 0 else 60
        draw.rounded_rectangle((88, y, 88 + width, y + 6), radius=3, fill=line)

    # 금전함(서랍) 손잡이 — 프린터 아래 짧은 선
    draw.rounded_rectangle((92, 212, 164, 224), radius=6, fill=accent)
    return image


def main() -> int:
    use_utf8_console()
    output = Path(__file__).with_name("icon.ico")
    icon = draw_icon()
    icon.save(output, format="ICO", sizes=[(s, s) for s in SIZES])

    preview = Path(__file__).with_name("icon_preview.png")
    icon.resize((128, 128), Image.LANCZOS).save(preview)

    print(f"생성: {output} ({output.stat().st_size:,} bytes)")
    print(f"미리보기: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
