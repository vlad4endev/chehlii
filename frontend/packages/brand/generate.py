#!/usr/bin/env python3
"""Растр фавикона casetop: PNG/ICO из той же геометрии, что и favicon.svg."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

INK = (23, 24, 26, 255)  # #17181a
PAPER = (244, 244, 243, 255)  # #f4f4f3

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # …/ЧехлыИИ
DESTS = [
    HERE,
    ROOT / "frontend/apps/miniapp/public",
    ROOT / "frontend/apps/admin/public",
    ROOT / "backend/app/static/brand",
]


def _draw_case(draw: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float) -> None:
    rx = w * 3.5 / 13
    draw.rounded_rectangle([x, y, x + w, y + h], radius=rx, fill=PAPER)
    island_w = w * 6 / 13
    island_h = h * 2.5 / 24
    island_x = x + (w - island_w) / 2
    island_y = y + h * 2.5 / 24
    draw.rounded_rectangle(
        [island_x, island_y, island_x + island_w, island_y + island_h],
        radius=island_h / 2,
        fill=INK,
    )


def render_tile(size: int) -> Image.Image:
    """Иконка вкладки: скруглённая плитка, как в SVG."""
    scale = 4
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = canvas * 8 / 32
    draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=radius, fill=INK)
    _draw_case(draw, canvas * 9.5 / 32, canvas * 4 / 32, canvas * 13 / 32, canvas * 24 / 32)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_app(size: int) -> Image.Image:
    """Полноразмерная иконка (iOS/PWA): фон на весь квадрат, чехол с полем."""
    scale = 4
    canvas = size * scale
    img = Image.new("RGBA", (canvas, canvas), INK)
    draw = ImageDraw.Draw(img)
    pad = canvas * 0.20
    inner = canvas - pad * 2
    case_h = inner
    case_w = inner * 13 / 24
    x = (canvas - case_w) / 2
    y = pad
    _draw_case(draw, x, y, case_w, case_h)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def copy_svg(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("favicon.svg", "favicon-mask.svg"):
        (dest / name).write_bytes((HERE / name).read_bytes())


def main() -> None:
    tile_32 = render_tile(32)
    app_180 = render_app(180)
    app_192 = render_app(192)
    app_512 = render_app(512)

    for dest in DESTS:
        copy_svg(dest)
        tile_32.save(dest / "favicon-32.png", "PNG")
        app_180.save(dest / "apple-touch-icon.png", "PNG")
        app_192.save(dest / "icon-192.png", "PNG")
        app_512.save(dest / "icon-512.png", "PNG")
        tile_32.save(dest / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32)])
        print(f"wrote {dest}")


if __name__ == "__main__":
    main()
