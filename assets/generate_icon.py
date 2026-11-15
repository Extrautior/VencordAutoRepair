"""Render the repository-owned VencordAutoRepair application icon."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


CANVAS = 1024
ASSET_DIR = Path(__file__).resolve().parent


def _mix(start: tuple[int, int, int], end: tuple[int, int, int], amount: float):
    return tuple(round(a + (b - a) * amount) for a, b in zip(start, end))


def render() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = 218
    inset = 58

    background = Image.new("RGBA", (CANVAS, CANVAS))
    background_draw = ImageDraw.Draw(background)
    for y in range(CANVAS):
        amount = y / (CANVAS - 1)
        colour = _mix((17, 30, 55), (7, 89, 104), amount)
        background_draw.line((0, y, CANVAS, y), fill=(*colour, 255))

    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, CANVAS - inset, CANVAS - inset),
        radius=radius,
        fill=255,
    )
    image.paste(background, (0, 0), mask)

    draw.rounded_rectangle(
        (inset, inset, CANVAS - inset, CANVAS - inset),
        radius=radius,
        outline=(122, 210, 226, 105),
        width=10,
    )
    draw.arc(
        (118, 112, CANVAS - 118, CANVAS - 118),
        start=204,
        end=334,
        fill=(143, 230, 240, 58),
        width=18,
    )

    shield = [
        (512, 226),
        (316, 308),
        (316, 492),
        (358, 672),
        (512, 790),
        (666, 672),
        (708, 492),
        (708, 308),
    ]
    inner_shield = [
        (512, 286),
        (370, 347),
        (370, 486),
        (402, 638),
        (512, 722),
        (622, 638),
        (654, 486),
        (654, 347),
    ]
    draw.polygon(shield, fill=(241, 249, 252, 255))
    draw.polygon(inner_shield, fill=(19, 49, 69, 255))

    draw.line(
        [(402, 514), (486, 598), (640, 426)],
        fill=(93, 226, 210, 255),
        width=76,
        joint="curve",
    )
    for point in ((402, 514), (486, 598), (640, 426)):
        draw.ellipse(
            (point[0] - 38, point[1] - 38, point[0] + 38, point[1] + 38),
            fill=(93, 226, 210, 255),
        )

    draw.ellipse((735, 675, 897, 837), fill=(255, 166, 66, 255))
    draw.rounded_rectangle((783, 716, 849, 802), radius=26, fill=(33, 48, 62, 255))
    draw.rectangle((791, 700, 841, 731), fill=(33, 48, 62, 255))
    return image


def main() -> int:
    image = render()
    png_path = ASSET_DIR / "VencordAutoRepair.png"
    ico_path = ASSET_DIR / "VencordAutoRepair.ico"
    image.resize((512, 512), Image.Resampling.LANCZOS).save(png_path, "PNG")
    image.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(png_path)
    print(ico_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

