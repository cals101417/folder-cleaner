"""Draws assets/app.ico and assets/icon.png in brand colors. Re-run after tweaking."""
from pathlib import Path

from PIL import Image, ImageDraw

GOLD, NAVY = (211, 154, 26, 255), (11, 15, 25, 255)
LIGHT = (255, 214, 120, 255)
OUT = Path(__file__).resolve().parents[1] / "assets"


def draw(size: int = 512) -> Image.Image:
    s = size / 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(112 * s), fill=GOLD)
    # folder: tab + body
    d.rounded_rectangle([96 * s, 140 * s, 236 * s, 200 * s], radius=int(18 * s), fill=NAVY)
    d.rounded_rectangle([96 * s, 172 * s, 416 * s, 392 * s], radius=int(26 * s), fill=NAVY)
    # three tidy rows inside, shortest last (sorted, shrinking)
    for i, width in enumerate((228, 168, 108)):
        y = (226 + i * 52) * s
        d.rounded_rectangle([142 * s, y, (142 + width) * s, y + 26 * s], radius=int(13 * s), fill=GOLD)
    # sparkle
    cx, cy, r = 372 * s, 132 * s, 46 * s
    d.polygon([(cx, cy - r), (cx + r * 0.28, cy - r * 0.28), (cx + r, cy), (cx + r * 0.28, cy + r * 0.28),
               (cx, cy + r), (cx - r * 0.28, cy + r * 0.28), (cx - r, cy), (cx - r * 0.28, cy - r * 0.28)],
              fill=LIGHT)
    return img


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    big = draw(512)
    big.save(OUT / "icon.png")
    big.save(OUT / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT / "app.ico")
