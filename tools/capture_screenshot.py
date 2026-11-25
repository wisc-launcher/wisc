"""Capture the PyQt6 launcher with sample data in offscreen mode."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def capture(output: Path, *, route: str = "home", width: int = 1100, height: int = 650) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from PyQt6.QtWidgets import QApplication
    from wisc.app import QtLauncherWindow, preview_profiles
    from wisc.ui.theme import install_fonts

    app = QApplication([])
    install_fonts()
    window = QtLauncherWindow(profiles=preview_profiles())
    window.resize(width, height)
    window.show()
    app.processEvents()

    if route in ("options_updates", "options_accounts", "options_about"):
        window.navigate("options")
        app.processEvents()
        window.options.show_subpage(route)
    elif route != "home":
        window.navigate(route)

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)

    pixmap = window.grab()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(output), "PNG"):
        raise RuntimeError(f"Failed to save screenshot to {output}")
    window._shutdown()
    print(f"Screenshot saved: {output} ({output.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist/wisc-home.png")
    parser.add_argument("--browser", help="Unused; kept for CLI compatibility")
    parser.add_argument("--checksum-file", type=Path, help="Add the PNG to an existing SHA256SUMS.txt")
    parser.add_argument(
        "--route",
        default="home",
        choices=("home", "installations", "mods", "skins", "options",
                 "options_updates", "options_accounts", "options_about"),
        help="Launcher page to capture using isolated sample data",
    )
    parser.add_argument("--width", type=int, default=1100)
    parser.add_argument("--height", type=int, default=650)
    args = parser.parse_args()

    capture(args.output.resolve(), route=args.route, width=args.width, height=args.height)
    if args.checksum_file:
        lines = args.checksum_file.read_text(encoding="utf-8").splitlines()
        lines = [line for line in lines if line.split("  ", 1)[-1] != args.output.name]
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        lines.append(f"{digest}  {args.output.name}")
        args.checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
