"""Capture the real launcher with sample data in a headless Chromium browser."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1100, 650


def find_browser(explicit: str | None) -> Path:
    candidates = [explicit, os.environ.get("SCREENSHOT_BROWSER")]
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if directory := os.environ.get(variable):
            candidates.extend(str(Path(directory) / suffix) for suffix in (
                "Microsoft/Edge/Application/msedge.exe",
                "Google/Chrome/Application/chrome.exe",
            ))
    candidates.extend(shutil.which(name) for name in (
        "msedge", "google-chrome", "chromium", "chromium-browser",
    ))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise RuntimeError("Install Edge or Chrome, or pass --browser PATH.")


def copy_preview_source(source: Path) -> None:
    """Copy release inputs without local tests, backups, or runtime caches."""
    source.mkdir()
    shutil.copy2(PROJECT_ROOT / "main.py", source / "main.py")
    shutil.copytree(PROJECT_ROOT / "wisc", source / "wisc",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The About view resolves the version beside the copied application source.
    if (PROJECT_ROOT / "VERSION").is_file():
        shutil.copy2(PROJECT_ROOT / "VERSION", source / "VERSION")
    shutil.copytree(PROJECT_ROOT / ".assets", source / ".assets",
                    ignore=shutil.ignore_patterns("cache", "__pycache__"))


def serve_preview(directory: Path, port: int, route: str = "home") -> None:
    source = directory / "source"
    copy_preview_source(source)
    sys.path.insert(0, str(source))
    # Patch the data directory before importing any launcher modules. The copied
    # source also prevents legacy .data migration from touching local settings.
    import minecraft_launcher_lib
    minecraft_root = directory / "minecraft"
    minecraft_launcher_lib.utils.get_minecraft_directory = lambda: str(minecraft_root)

    from wisc.core import storage
    assert storage.DATA_DIR.resolve().is_relative_to(directory.resolve())
    if not storage.save_accounts({
        "active_account_id": "screenshot-player",
        "accounts": [{"id": "screenshot-player", "type": "offline",
                      "username": "Player", "created_at": 1}],
    }):
        raise RuntimeError("Could not create the screenshot account.")
    profiles = [
        {"id": "screenshot-survival", "name": "Survival", "loader": "vanilla",
         "minecraft_version": "1.21.4", "loader_version": "", "version_id": "1.21.4",
         "game_directory": str(minecraft_root / "instances" / "Survival"),
         "icon": "icon_blocks/grass_block.png"},
        {"id": "screenshot-fabric", "name": "Fabric Adventure", "loader": "fabric",
         "minecraft_version": "1.21.1", "loader_version": "0.16.10",
         "version_id": "fabric-loader-0.16.10-1.21.1",
         "game_directory": str(minecraft_root / "instances" / "Fabric Adventure"),
         "icon": "icon_blocks/diamond_ore.png"},
    ]
    for profile in profiles:
        profile["is_instance"] = True
        Path(profile["game_directory"]).mkdir(parents=True)
    if not storage.save_installations(profiles, latest_release_id="1.21.4"):
        raise RuntimeError("Could not create screenshot profiles.")
    if not storage.save_settings({**storage.DEFAULT_SETTINGS, "discord_rpc": False,
                                  "enable_orbs": False, "onboarding_completed": True}):
        raise RuntimeError("Could not create screenshot settings.")

    from wisc import app as launcher_ui
    import flet as ft
    import uvicorn
    # Use the same bundled assets as the desktop app, with web-relative paths.
    os.chdir(source / ".assets")
    launcher_ui.ASSETS_DIR = Path(".")
    launcher_ui.get_latest_release_version = lambda: ("1.21.4", True)
    launcher_ui.get_version_catalog = lambda: (
        [{"id": "1.21.4", "type": "release"}, {"id": "1.21.1", "type": "release"}], "1.21.4", True)
    launcher_ui.check_internet_connection = lambda *args, **kwargs: True
    from wisc.services import instances as launcher_services
    launcher_services.check_internet_connection = lambda *args, **kwargs: True
    from wisc.services import banners
    banners.get_local_banner_for_target = lambda target, *args: str(Path("banners") / (
        "portal.png" if str((target or {}).get("loader", "Vanilla")).casefold() != "vanilla" else "farmhouse.png"))

    async def fixture_banner(target, *args):
        return banners.get_local_banner_for_target(target)

    banners.ensure_banner_for_target = fixture_banner
    random.seed(0)

    def preview(page):
        launcher_ui.main(page)

        async def ready():
            # Wait for the launcher's entrance animations before checking paint.
            await asyncio.sleep(2)
            if route != "home":
                from wisc.core import state
                state.navigation_state["navigate"](route)
                await asyncio.sleep(1)
            (directory / "ready").write_text("ready", encoding="utf-8")
        page.run_task(ready)

    app = ft.run(preview, assets_dir=str(source / ".assets"), no_cdn=True,
                 export_asgi_app=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


class DevTools:
    def __init__(self, connection):
        self.connection = connection
        self.counter = 0
        self.errors = []

    def call(self, method: str, params: dict | None = None) -> dict:
        self.counter += 1
        self.connection.send(json.dumps({"id": self.counter, "method": method,
                                         "params": params or {}}))
        while True:
            result = json.loads(self.connection.recv(timeout=20))
            if result.get("method") == "Runtime.exceptionThrown":
                self.errors.append(result["params"])
            if result.get("id") == self.counter:
                if "error" in result:
                    raise RuntimeError(f"{method}: {result['error']}")
                return result.get("result", {})

    def evaluate(self, expression: str):
        result = self.call("Runtime.evaluate", {"expression": expression,
                                                "returnByValue": True})
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"])
        return result["result"].get("value")


def validate_screenshot(data: bytes) -> None:
    from PIL import Image, ImageStat
    with Image.open(io.BytesIO(data)) as picture:
        if picture.format != "PNG" or picture.size != (WIDTH, HEIGHT):
            raise RuntimeError("The screenshot has an unexpected format or size.")
        # A blank Flutter startup canvas must never replace a published preview.
        for box in ((70, 20, 1050, 290), (70, 290, 760, 640), (800, 290, 1080, 640)):
            deviation = ImageStat.Stat(picture.crop(box).convert("RGB")).stddev
            if max(deviation) < 12:
                raise RuntimeError("The screenshot contains an unrendered launcher panel.")


def capture(output: Path, browser: Path, *, route: str = "home") -> None:
    from websockets.sync.client import connect
    temporary_root = (PROJECT_ROOT / "temp").resolve()
    if not temporary_root.is_relative_to(PROJECT_ROOT):
        raise RuntimeError("Screenshot temporary files must stay inside the workspace.")
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="screenshot-", dir=temporary_root,
                                     ignore_cleanup_errors=True) as temporary:
        directory = Path(temporary).resolve()
        if not directory.is_relative_to(temporary_root):
            raise RuntimeError("Screenshot cleanup must stay inside its temporary directory.")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process_options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        browser_process = None
        with (directory / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen([
                sys.executable, str(Path(__file__).resolve()), "--serve", str(directory),
                "--port", str(port),
                "--route", route,
            ], stdout=log, stderr=log, **process_options)
            try:
                deadline = time.monotonic() + 75
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("The screenshot server exited before starting.")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/", timeout=1):
                            break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise RuntimeError("The screenshot server did not start.")
                        time.sleep(0.2)
                browser_profile = directory / "browser"
                browser_process = subprocess.Popen([
                    str(browser), "--headless=new", "--no-first-run", "--no-default-browser-check",
                    "--disable-background-networking", "--hide-scrollbars", "--force-device-scale-factor=1",
                    "--enable-unsafe-swiftshader", f"--window-size={WIDTH},{HEIGHT}",
                    "--remote-debugging-port=0", f"--user-data-dir={browser_profile}", "about:blank",
                ], stdout=log, stderr=log, **process_options)
                active_port = browser_profile / "DevToolsActivePort"
                while not active_port.is_file():
                    if browser_process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("The headless browser did not start.")
                    time.sleep(0.2)
                debug_port = int(active_port.read_text().splitlines()[0])
                with urlopen(f"http://127.0.0.1:{debug_port}/json/list", timeout=5) as response:
                    target = next(item for item in json.load(response) if item["type"] == "page")
                with connect(target["webSocketDebuggerUrl"], max_size=20_000_000) as connection:
                    devtools = DevTools(connection)
                    devtools.call("Page.enable")
                    devtools.call("Runtime.enable")
                    devtools.call("Emulation.setDeviceMetricsOverride", {
                        "width": WIDTH, "height": HEIGHT, "deviceScaleFactor": 1, "mobile": False,
                    })
                    devtools.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/"})
                    while True:
                        # Flutter exposes its rendered labels when semantics is enabled.
                        labels = devtools.evaluate("""(() => {
                            document.querySelector('flt-semantics-placeholder')?.click();
                            // Flutter may merge a card's text and images into
                            // one accessible label instead of DOM text nodes.
                            const accessibleLabels = Array.from(
                                document.querySelectorAll('[aria-label]'),
                                element => element.getAttribute('aria-label')
                            );
                            return [document.body?.innerText || '', ...accessibleLabels].join('\\n');
                        })()""") or ""
                        expected = {
                            "onboarding": ("WELCOME", "to Wisc.", "Continue"),
                            "home": ("Survival", "Fabric Adventure", "PLAY"),
                            "installations": ("Survival", "Fabric Adventure", "New Profile"),
                            "mods": ("Mods", "Installed", "Discover"),
                            "skins": ("Skins Disabled",),
                            "options": ("Java", "Accounts", "Updates"),
                            "options_updates": ("Launcher Updates", "Check for Updates"),
                            "options_accounts": ("Manage Accounts", "Player"),
                            "options_about": ("About", "Wisc"),
                            "new_installation": ("New Profile", "Save Profile"),
                            "account_login": ("Add Account", "Your next adventure", "Log In"),
                        }[route]
                        if (directory / "ready").is_file() and all(label in labels for label in expected):
                            break
                        if devtools.errors or time.monotonic() > deadline:
                            raise RuntimeError(f"Launcher did not render: {labels[:500]} {devtools.errors}")
                        time.sleep(0.25)
                    time.sleep(0.5)
                    screenshot = devtools.call("Page.captureScreenshot", {
                        "format": "png", "captureBeyondViewport": False,
                    })
                    if devtools.errors:
                        raise RuntimeError(f"Browser rendering errors: {devtools.errors}")
                    data = base64.b64decode(screenshot["data"])
                    if route == "home":
                        validate_screenshot(data)
                    else:
                        from PIL import Image, ImageStat
                        with Image.open(io.BytesIO(data)) as picture:
                            deviation = ImageStat.Stat(picture.crop((20, 80, WIDTH - 20, HEIGHT - 20)).convert("RGB")).stddev
                            if picture.size != (WIDTH, HEIGHT) or max(deviation) < 12:
                                raise RuntimeError("The requested launcher page did not render.")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(data)
                    devtools.call("Browser.close")
            except Exception:
                log.flush()
                print((directory / "server.log").read_text(encoding="utf-8")[-6000:], file=sys.stderr)
                raise
            finally:
                for process in (browser_process, server):
                    if process is None:
                        continue
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
    print(f"Screenshot saved: {output} ({output.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "dist/wisc-home.png")
    parser.add_argument("--browser", help="Edge or Chrome executable (auto-detected by default)")
    parser.add_argument("--checksum-file", type=Path, help="Add the PNG to an existing SHA256SUMS.txt")
    parser.add_argument("--serve", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--route", default="home", choices=("home", "onboarding", "installations", "mods", "skins", "options",
                        "options_updates", "options_accounts", "options_about", "new_installation", "account_login"),
                        help="Launcher page to capture using isolated sample data")
    parser.add_argument("--width", type=int, default=1100)
    parser.add_argument("--height", type=int, default=650)
    args = parser.parse_args()
    global WIDTH, HEIGHT
    WIDTH, HEIGHT = args.width, args.height
    if args.serve:
        serve_preview(args.serve.resolve(), args.port, args.route)
        return
    capture(args.output.resolve(), find_browser(args.browser), route=args.route)
    if args.checksum_file:
        lines = args.checksum_file.read_text(encoding="utf-8").splitlines()
        lines = [line for line in lines if line.split("  ", 1)[-1] != args.output.name]
        digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
        lines.append(f"{digest}  {args.output.name}")
        args.checksum_file.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
