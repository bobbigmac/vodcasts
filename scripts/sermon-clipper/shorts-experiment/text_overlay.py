"""Render text to PNG using Pillow. Reliable cross-platform; no ffmpeg font dependency."""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = ImageDraw = ImageFont = None  # type: ignore


_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _get_font(size: int):
    """Try system fonts, fallback to Pillow default (never disable text)."""
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


def _wrap_text(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int) -> list[str]:
    """Wrap text to fit max_width. Simple word-wrap."""
    words = (text or "").split()
    if not words:
        return [""]
    lines = []
    current = []
    for w in words:
        test = " ".join(current + [w])
        # Approximate: 0.6 * len * size for width
        try:
            bbox = font.getbbox(test) if hasattr(font, "getbbox") else (0, 0, len(test) * 8, 20)
            w_est = bbox[2] - bbox[0]
        except Exception:
            w_est = len(test) * 10
        if w_est > max_width and current:
            lines.append(" ".join(current))
            current = [w]
        else:
            current.append(w)
    if current:
        lines.append(" ".join(current))
    return lines


def render_card(text: str, width: int, height: int, out_path: Path, bg_color: str = "#1a1a2e", font_size: int = 48) -> Path | None:
    """Render full card (e.g. 1080x1920) with centered text. Returns out_path or None."""
    if Image is None or ImageDraw is None:
        return None
    font = _get_font(font_size)
    lines = _wrap_text(text[:120], font, width - 80)
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    line_height = int(font_size * 1.3)
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
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_context_panel(text: str, width: int, height: int, out_path: Path, bg_color: str = "#16213e", font_size: int = 28) -> Path | None:
    """Render context panel (e.g. 1080x960) with centered text."""
    if Image is None or ImageDraw is None:
        return None
    font = _get_font(font_size)
    lines = _wrap_text(text[:100], font, width - 60)
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    line_height = int(font_size * 1.2)
    total_h = len(lines) * line_height
    y = (height - total_h) // 2
    for line in lines:
        try:
            bbox = font.getbbox(line) if hasattr(font, "getbbox") else (0, 0, len(line) * 8, font_size)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(line) * 8
        x = (width - w) // 2
        draw.text((x, y), line, fill="white", font=font)
        y += line_height
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
