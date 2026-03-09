"""Clean sermon-clipper scratch/output leftovers without deleting deliberate deliverables."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _lib import default_work_root, remove_path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Remove sermon-clipper temp artifacts.")
    p.add_argument(
        "--path",
        action="append",
        default=[],
        help="Output directory to clean work*/concat_list leftovers from. Repeat as needed.",
    )
    p.add_argument("--keep-internal-work", action="store_true", help="Do not remove scripts/sermon-clipper/.work.")
    return p.parse_args()


def _clean_target_dir(target: Path) -> list[Path]:
    removed: list[Path] = []
    if not target.exists() or not target.is_dir():
        return removed
    for child in target.iterdir():
        name = child.name.lower()
        if child.is_dir() and (name == "work" or name.startswith("work-")):
            remove_path(child)
            removed.append(child)
            continue
        if child.is_file() and name == "concat_list.txt":
            remove_path(child)
            removed.append(child)
    return removed


def main() -> None:
    args = _parse_args()
    removed: list[Path] = []

    pycache_dirs = list(Path(__file__).resolve().parent.rglob("__pycache__"))
    pyc_files = list(Path(__file__).resolve().parent.rglob("*.pyc"))
    for path in pycache_dirs + pyc_files:
        remove_path(path)
        removed.append(path)

    if not args.keep_internal_work:
        work_root = default_work_root()
        if work_root.exists():
            remove_path(work_root)
            removed.append(work_root)

    for raw_target in args.path:
        removed.extend(_clean_target_dir(Path(raw_target).resolve()))

    print(f"[cleanup] removed {len(removed)} path(s)", file=sys.stderr)
    for path in removed:
        print(str(path), file=sys.stderr)


if __name__ == "__main__":
    main()
