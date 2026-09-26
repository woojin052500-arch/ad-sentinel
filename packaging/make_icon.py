from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "ad_sentinel" / "assets"
SIZE = 1024
NAVY = (22, 63, 122, 255)
BLUE = (41, 112, 204, 255)
WHITE = (255, 255, 255, 255)
RED = (226, 59, 59, 255)


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    shield = [(512, 40), (900, 170), (900, 500), (512, 990), (124, 500), (124, 170)]
    d.polygon(shield, fill=NAVY)
    inner = [(512, 110), (840, 220), (840, 490), (512, 900), (184, 490), (184, 220)]
    d.polygon(inner, fill=BLUE)
    d.ellipse((260, 230, 660, 630), outline=WHITE, width=70)
    d.line((600, 570, 790, 760), fill=WHITE, width=110)
    d.ellipse((745, 715, 835, 805), fill=WHITE)
    d.rounded_rectangle((430, 305, 490, 480), radius=30, fill=RED)
    d.ellipse((425, 505, 495, 575), fill=RED)
    return img


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    img = draw()
    img.resize((256, 256), Image.LANCZOS).save(ASSETS / "icon.png")
    img.save(ASSETS / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"아이콘 생성: {ASSETS}")


if __name__ == "__main__":
    main()
