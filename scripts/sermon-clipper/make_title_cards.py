"""Generate title card images from a video script. Uses PIL/Pillow."""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[make_title_cards] Install Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)

from _lib import parse_long_form_script


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate title card images from video script.")
    p.add_argument("--script", required=True, help="Video script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output directory for images.")
    p.add_argument("--width", type=int, default=1920, help="Image width (default: 1920).")
    p.add_argument("--height", type=int, default=1080, help="Image height (default: 1080).")
    p.add_argument("--font-size", type=int, default=82, help="Title font size (default: 82).")
    p.add_argument("--transition-font-size", type=int, default=58, help="Transition card font size (default: 58).")
    return p.parse_args()


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for font_path in candidates:
        p = Path(font_path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = (text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width or not current:
            current.append(word)
            continue
        lines.append(" ".join(current))
        current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def _gradient_background(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), "#0f172a")
    pixels = img.load()
    for y in range(height):
        blend = y / max(height - 1, 1)
        for x in range(width):
            radial = math.hypot(x - width * 0.78, y - height * 0.22) / max(width, height)
            radial = min(max(radial, 0.0), 1.0)
            r = int(15 + 24 * (1 - blend) + 60 * (1 - radial))
            g = int(23 + 38 * blend + 16 * (1 - radial))
            b = int(42 + 70 * blend + 18 * (1 - radial))
            pixels[x, y] = (min(r, 255), min(g, 255), min(b, 255))
    return img


def main() -> None:
    args = _parse_args()
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[make_title_cards] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    parsed = parse_long_form_script(script_path)
    theme = str(parsed.get("metadata", {}).get("theme") or "sermon clips").strip()
    cards = [item for item in parsed.get("items") or [] if item.get("type") == "title_card"]
    if not cards:
        print("[make_title_cards] No title_card sections found in script", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for existing_png in out_dir.glob("*.png"):
        try:
            existing_png.unlink()
        except OSError:
            pass

    for i, card in enumerate(cards):
        card_id = card.get("id") or f"card_{i}"
        text = str(card.get("text") or "").strip()
        is_transition = card_id.startswith("transition_")
        font_size = args.transition_font_size if is_transition else args.font_size
        font = _find_font(font_size)
        label_font = _find_font(34)
        footer_font = _find_font(28)

        img = _gradient_background(args.width, args.height)
        draw = ImageDraw.Draw(img)

        if is_transition:
            draw.rounded_rectangle((112, 96, 410, 160), radius=18, fill="#1d4ed8")
            draw.text((148, 114), "Transition", fill="white", font=label_font)
        else:
            draw.rounded_rectangle((112, 96, 350, 160), radius=18, fill="#be123c")
            draw.text((148, 114), theme.title(), fill="white", font=label_font)

        max_width = args.width - 320
        lines = _wrap_text(draw, text, font, max_width=max_width)
        line_height = int(font_size * 1.28)
        total_height = len(lines) * line_height
        y = max(220, (args.height - total_height) // 2)

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (args.width - text_width) // 2
            draw.text((x, y), line, fill="#f8fafc", font=font)
            y += line_height

        footer = "prays.be"
        footer_bbox = draw.textbbox((0, 0), footer, font=footer_font)
        footer_width = footer_bbox[2] - footer_bbox[0]
        draw.text((args.width - footer_width - 120, args.height - 92), footer, fill="#cbd5e1", font=footer_font)

        out_path = out_dir / f"{card_id}.png"
        img.save(out_path, "PNG")
        print(f"[make_title_cards] {out_path}", file=sys.stderr)

    print(f"[make_title_cards] wrote {len(cards)} title cards to {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
