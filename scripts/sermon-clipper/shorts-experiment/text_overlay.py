"""Render text to PNG using Pillow. Reliable cross-platform; no ffmpeg font dependency."""
from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None  # type: ignore


_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _get_font(size: int):
    if ImageFont is None:
        return ImageFont.load_default()
    for path in _FONT_CANDIDATES:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        try:
            bbox = font.getbbox(test) if hasattr(font, "getbbox") else (0, 0, len(test) * 8, 20)
            width = bbox[2] - bbox[0]
        except Exception:
            width = len(test) * 10
        if width > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines


def _gradient(width: int, height: int, base: tuple[int, int, int], accent: tuple[int, int, int]) -> Image.Image | None:
    if Image is None:
        return None
    img = Image.new("RGB", (width, height), "#0f172a")
    px = img.load()
    for y in range(height):
        blend = y / max(1, height - 1)
        for x in range(width):
            flare = max(0.0, 1.0 - math.hypot(x - width * 0.78, y - height * 0.18) / max(width, height))
            r = int(base[0] * (1 - blend) + accent[0] * blend + 40 * flare)
            g = int(base[1] * (1 - blend) + accent[1] * blend + 18 * flare)
            b = int(base[2] * (1 - blend) + accent[2] * blend + 14 * flare)
            px[x, y] = (min(r, 255), min(g, 255), min(b, 255))
    return img


def render_card(
    text: str,
    width: int,
    height: int,
    out_path: Path,
    bg_color: str = "#1a1a2e",
    font_size: int = 72,
    label: str = "Sermon Clips",
    footer: str = "prays.be",
) -> Path | None:
    if Image is None or ImageDraw is None:
        return None
    font = _get_font(font_size)
    label_font = _get_font(30)
    footer_font = _get_font(24)
    img = _gradient(width, height, (16, 24, 40), (29, 78, 216)) or Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle((60, 54, 300, 112), radius=16, fill="#be123c")
    draw.text((88, 70), label[:20], fill="white", font=label_font)

    lines = _wrap_text(text[:140], font, width - 120)
    line_height = int(font_size * 1.25)
    total_h = len(lines) * line_height
    y = (height - total_h) // 2
    for line in lines:
        try:
            bbox = font.getbbox(line) if hasattr(font, "getbbox") else (0, 0, len(line) * 10, font_size)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(line) * 10
        x = (width - w) // 2
        draw.text((x, y), line, fill="white", font=font)
        y += line_height

    try:
        bbox = footer_font.getbbox(footer) if hasattr(footer_font, "getbbox") else (0, 0, len(footer) * 8, 20)
        footer_width = bbox[2] - bbox[0]
    except Exception:
        footer_width = len(footer) * 8
    draw.text((width - footer_width - 64, height - 62), footer, fill="#dbeafe", font=footer_font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_context_panel(
    text: str,
    width: int,
    height: int,
    out_path: Path,
    bg_color: str = "#16213e",
    font_size: int = 30,
    label: str = "Why it matters",
    footer: str = "",
) -> Path | None:
    if Image is None or ImageDraw is None:
        return None
    font = _get_font(font_size)
    label_font = _get_font(26)
    footer_font = _get_font(22)
    img = _gradient(width, height, (15, 23, 42), (2, 132, 199)) or Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((36, 34, 280, 84), radius=14, fill="#0f766e")
    draw.text((60, 48), label[:24], fill="white", font=label_font)

    lines = _wrap_text(text[:180], font, width - 96)
    line_height = int(font_size * 1.25)
    total_h = len(lines) * line_height
    y = max(118, (height - total_h) // 2)
    for line in lines:
        try:
            bbox = font.getbbox(line) if hasattr(font, "getbbox") else (0, 0, len(line) * 8, font_size)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(line) * 8
        x = (width - w) // 2
        draw.text((x, y), line, fill="white", font=font)
        y += line_height

    if footer:
        try:
            bbox = footer_font.getbbox(footer) if hasattr(footer_font, "getbbox") else (0, 0, len(footer) * 8, 20)
            footer_width = bbox[2] - bbox[0]
        except Exception:
            footer_width = len(footer) * 8
        draw.text((width - footer_width - 40, height - 46), footer[:50], fill="#dbeafe", font=footer_font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
