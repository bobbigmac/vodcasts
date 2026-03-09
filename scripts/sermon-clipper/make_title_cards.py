"""Generate title card images from a video script. Uses PIL/Pillow."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[make_title_cards] Install Pillow: pip install Pillow", file=sys.stderr)
    sys.exit(1)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate title card images from video script.")
    p.add_argument("--script", required=True, help="Video script markdown path.")
    p.add_argument("--output", "-o", required=True, help="Output directory for images.")
    p.add_argument("--width", type=int, default=1920, help="Image width (default: 1920).")
    p.add_argument("--height", type=int, default=1080, help="Image height (default: 1080).")
    p.add_argument("--bg", default="#1a1a2e", help="Background color (default: #1a1a2e).")
    p.add_argument("--fg", default="#eaeaea", help="Text color (default: #eaeaea).")
    p.add_argument("--font-size", type=int, default=72, help="Title font size (default: 72).")
    p.add_argument("--transition-font-size", type=int, default=48, help="Transition card font size (default: 48).")
    p.add_argument("--transition-duration", type=float, default=3.0, help="Suggested duration for transition cards (seconds).")
    return p.parse_args()


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert #RRGGBB to (r,g,b)."""
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 6:
        return tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4))
    return (26, 26, 46)


def _wrap_text(text: str, max_chars: int = 40) -> list[str]:
    """Simple word wrap."""
    words = text.split()
    lines = []
    current = []
    for w in words:
        if sum(len(x) for x in current) + len(current) + len(w) <= max_chars:
            current.append(w)
        else:
            if current:
                lines.append(" ".join(current))
            current = [w]
    if current:
        lines.append(" ".join(current))
    return lines


def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Try common fonts first."""
    candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _parse_script(script_path: Path) -> list[dict]:
    """Extract title_card and transition sections from script (in order)."""
    text = script_path.read_text(encoding="utf-8", errors="replace")
    cards = []
    transition_idx = 0
    current_type = None
    current_content = []

    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("## "):
            section = line_stripped[3:].strip().lower()
            if current_type == "title_card" and current_content:
                kv = {}
                for ln in current_content:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        kv[k.strip()] = v.strip()
                cards.append({"id": kv.get("id", ""), "text": kv.get("text", "")})
            elif current_type == "transition" and current_content:
                transition_idx += 1
                cards.append({"id": f"transition_{transition_idx}", "text": " ".join(current_content).strip()})
            current_type = section
            current_content = []
            continue
        if current_type in ("title_card", "transition") and line:
            current_content.append(line)

    if current_type == "title_card" and current_content:
        kv = {}
        for ln in current_content:
            if ":" in ln:
                k, v = ln.split(":", 1)
                kv[k.strip()] = v.strip()
        cards.append({"id": kv.get("id", ""), "text": kv.get("text", "")})
    elif current_type == "transition" and current_content:
        transition_idx += 1
        cards.append({"id": f"transition_{transition_idx}", "text": " ".join(current_content).strip()})

    return cards


def main() -> None:
    args = _parse_args()
    script_path = Path(args.script)
    if not script_path.exists():
        print(f"[make_title_cards] Script not found: {script_path}", file=sys.stderr)
        sys.exit(1)

    cards = _parse_script(script_path)
    if not cards:
        print("[make_title_cards] No title_card sections found in script", file=sys.stderr)
        sys.exit(2)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    bg = _hex_to_rgb(args.bg)
    fg = _hex_to_rgb(args.fg)
    for i, card in enumerate(cards):
        card_id = card.get("id") or f"card_{i}"
        text = card.get("text") or ""
        is_transition = card_id.startswith("transition_")
        font_size = args.transition_font_size if is_transition else args.font_size
        font = _find_font(font_size)
        max_chars = 50 if is_transition else 35

        img = Image.new("RGB", (args.width, args.height), bg)
        draw = ImageDraw.Draw(img)

        lines = _wrap_text(text, max_chars=max_chars)
        line_height = int(font_size * 1.4)
        total_h = len(lines) * line_height
        y = (args.height - total_h) // 2

        for ln in lines:
            bbox = draw.textbbox((0, 0), ln, font=font)
            tw = bbox[2] - bbox[0]
            x = (args.width - tw) // 2
            draw.text((x, y), ln, fill=fg, font=font)
            y += line_height

        out_path = out_dir / f"{card_id}.png"
        img.save(out_path, "PNG")
        print(f"[make_title_cards] {out_path}", file=sys.stderr)

    print(f"[make_title_cards] wrote {len(cards)} title cards to {out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
