"""PyQt6 frontend for Wisc Launcher."""

import importlib
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Sequence

from PyQt6.QtCore import QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

from wisc.core.paths import ASSETS_DIR
from wisc.core.storage import (
    DATA_DIR,
    get_active_account,
    load_profile_order,
    load_installations,
    load_settings,
    load_theme_choice,
    sort_profiles,
)
from wisc.core.themes import get_theme_names
from wisc.services import launcher
from wisc.services.artwork import resolve_background_artwork
from wisc.services.discord_presence import DiscordPresence, SkinPortraitCache
from wisc.ui import theme as theme
from wisc.ui.components import ArtworkBackground, GlassPanel, text_label
from wisc.ui.home import HomePage, HomeProfile
from wisc.ui.images import ContentImages
from wisc.ui.progress import ProgressHost
from wisc.ui.tasks import ServiceRunner
from wisc.ui.theme import (
    DEFAULT_THEME, dark_palette, get_theme, install_focus_cues, install_fonts, stylesheet,
)
from wisc.ui.window import FramelessWindow, TitleBar


def preview_profiles() -> list[HomeProfile]:
    """Bundled sample profiles; the UI preview never reads or changes game data."""
    icons = ASSETS_DIR / "icons" / "icon_blocks"
    covers = ASSETS_DIR / "version-art"
    return [
        HomeProfile("latest", "Latest Release", "1.21.11", "Vanilla",
                    covers / "mounts-of-mayhem.webp", icons / "grass_block.png", False),
        HomeProfile("survival", "Survival", "1.21.1", "Vanilla",
                    covers / "tricky-trials.webp", icons / "grass_block.png"),
        HomeProfile("fabric", "Fabric Adventure", "1.20.1", "Fabric",
                    covers / "trails-and-tales.webp", icons / "diamond_ore.png"),
        HomeProfile("creative", "Creative", "1.16.5", "Vanilla",
                    covers / "nether-update.webp", icons / "crafting_table.png"),
    ]


def _resolve_profile_icon(icon_value: object) -> Path:
    icons_dir = ASSETS_DIR / "icons" / "icon_blocks"
    if isinstance(icon_value, str) and icon_value.strip():
        candidate = Path(icon_value)
        if candidate.is_file():
            return candidate
        named = icons_dir / (icon_value if icon_value.endswith(".png") else f"{icon_value}.png")
        if named.is_file():
            return named
    return icons_dir / "grass_block.png"


def _load_saved_profiles() -> tuple[list[HomeProfile], dict[str, dict]]:
    raw_list = sort_profiles(load_installations(), load_profile_order())
    if not raw_list:
        sample = preview_profiles()
        return sample, {}
    try:
        installed_ids = {item["version_id"] for item in launcher.get_installed_versions()}
    except Exception:
        installed_ids = set()
    profiles: list[HomeProfile] = []
    raw_by_id: dict[str, dict] = {}
    fallback_art = ASSETS_DIR / "version-art" / "java-edition.webp"
    for item in raw_list:
        pid = str(item.get("id", ""))
        if not pid:
            continue
        raw_by_id[pid] = dict(item)
        version = str(item.get("minecraft_version") or item.get("version_id") or "")
        loader_name = str(item.get("loader") or "Vanilla")
        vid = launcher.get_profile_version_id(item) or version
        art_value = resolve_background_artwork(item, launcher.minecraft_directory)
        art_path = Path(art_value.source) if art_value and art_value.source else fallback_art
        if not art_path.is_file():
            art_path = fallback_art
        icon_path = _resolve_profile_icon(item.get("icon"))
        profiles.append(
            HomeProfile(
                id=pid,
                name=str(item.get("name") or "Minecraft"),
                version=version,
                loader=loader_name,
                artwork=art_path,
                icon=icon_path,
                installed=(not installed_ids) or (vid in installed_ids),
            )
        )
    if not profiles:
        return preview_profiles(), {}
    return profiles, raw_by_id


class QtLauncherWindow(FramelessWindow):
    page_requested = pyqtSignal(str)
    launch_progress = pyqtSignal(object, object)

    def __init__(self, profiles: Sequence[HomeProfile] | None = None):
        super().__init__()
        install_focus_cues()
        self.setWindowTitle("Wisc")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "icons" / "wisc.ico")))
        self.resize(1100, 650)
        self.setMinimumSize(1100, 650)
        saved_theme = load_theme_choice(get_theme_names())
        settings = load_settings()
        colors = get_theme(saved_theme, str(settings.get("custom_accent", "#46BA34")))
        if profiles is None:
            loaded_profiles, raw_by_id = _load_saved_profiles()
        else:
            loaded_profiles, raw_by_id = list(profiles), {}
        self._profiles = loaded_profiles
        self._raw_profiles = raw_by_id
        self._colors = colors
        self._library = self._skins = self._mods = self._options = None
        self._current_page = "home"
        self._preparations: dict[str, int] = {}
        self._prepared_modules: set[str] = set()
        self._library_preload = QTimer(self)
        self._library_preload.setSingleShot(True)
        self._library_preload.timeout.connect(self._warm_library_modules)
        self._loading_page = None
        self._requested_mod_profile = None
        self._launch_token: int | None = None
        self._launch_cancel: threading.Event | None = None
        self._closing = False
        self.presence = DiscordPresence(
            enabled=bool(settings.get("discord_rpc", True)),
            portrait_cache=SkinPortraitCache(DATA_DIR / "discord_portraits.json"),
        )
        self.presence.start()
        self.presence.set_page("home")
        artwork = loaded_profiles[0].artwork if loaded_profiles else ASSETS_DIR / "version-art" / "java-edition.webp"
        self.services = ServiceRunner(self)
        self._background_images = ContentImages(self.services, self)
        self._background_images.set_visible(True)
        self.background = ArtworkBackground(artwork, images=self._background_images)
        self.setCentralWidget(self.background)
        layout = QVBoxLayout(self.background)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.title_bar = TitleBar(self)
        self.title_bar.navigation_requested.connect(self.navigate)
        layout.addWidget(self.title_bar)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.home = HomePage(loaded_profiles, colors, images=ContentImages(self.services, self))
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        self.pages.addWidget(self.home)
        self.progress_host = ProgressHost(self.background)
        self.progress_host.cancel_requested.connect(self._cancel_operation)
        layout.addWidget(self.progress_host)
        self.launch_progress.connect(self.home.set_operation)
        self.home.operation_changed.connect(self._home_progress_changed)
        self.home.profile_selected.connect(self._selected_profile_changed)
        self.home.theme_requested.connect(self.apply_theme)
        self.home.library_requested.connect(lambda: self.navigate("installations"))
        self.home.launch_requested.connect(self._launch_profile)
        self.home.cancel_requested.connect(self._cancel_launch)
        self.home.folder_requested.connect(self._open_profile_folder)
        self.home.account_requested.connect(self._open_accounts)
        self.apply_theme(saved_theme)

    @property
    def library(self):
        if self._library is None:
            from wisc.ui.library import LibraryPage
            self._library = LibraryPage(self._profiles, self._colors, runner=self.services)
            self._library.profile_selected.connect(self.home.select_profile)
            self._library.action_requested.connect(self._library_action)
            self._library.create_requested.connect(self.home.create_requested.emit)
            if self.home.selected_profile is not None:
                self._library.set_selected(self.home.selected_profile.id)
            self.pages.addWidget(self._library)
        return self._library

    @property
    def skins(self):
        if self._skins is None:
            from wisc.ui.skins import SkinsPage
            self._skins = SkinsPage(self.services, self._colors)
            self._skins.progress_changed.connect(self._skin_progress_changed)
            self.pages.addWidget(self._skins)
        return self._skins

    @property
    def mods(self):
        if self._mods is None:
            from wisc.ui.mods import ModsPage
            self._mods = ModsPage(self.services, self._colors,
                                  selected_profile=lambda: getattr(self.home.selected_profile, "id", None))
            self._mods.progress_changed.connect(self._content_progress_changed)
            self._mods.loading_changed.connect(self._content_loading_changed)
            if self._requested_mod_profile is not None:
                self._mods.enter(self._requested_mod_profile)
                self._requested_mod_profile = None
            self.pages.addWidget(self._mods)
        return self._mods

    def _cancel_operation(self, source: str) -> None:
        if source == "content" and self._mods is not None:
            self._mods.cancel_operation()
        elif source == "home":
            self.home.cancel_requested.emit()

    def _shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._library_preload.stop()
        for token in self._preparations.values():
            self.services.cancel(token)
        self._preparations.clear()
        if self._mods is not None:
            self._mods.shutdown()
        if self._skins is not None:
            self._skins.shutdown()
        if self._options is not None:
            self._options.shutdown()
        self.presence.stop()
        self.services.close()

    @property
    def options(self):
        if self._options is None:
            from wisc.ui.options import OptionsPage
            self._options = OptionsPage(self.services, self._colors)
            self._options.theme_requested.connect(self.apply_theme)
            self.pages.addWidget(self._options)
        return self._options

    def navigate(self, page: str) -> None:
        if self._closing:
            return
        attributes = {
            "home": "home",
            "installations": "library",
            "skins": "skins",
            "mods": "mods",
            "options": "options",
        }
        if page not in attributes:
            self.page_requested.emit(page)
            return
        self._current_page = page
        self.presence.set_page("settings" if page == "options" else ("library" if page == "installations" else page))
        self.background.set_frosted(page != "home")
        self.title_bar.set_current_page(page)
        attribute = attributes[page]
        self.progress_host.set_operation("navigation", None)
        if page == "home" or getattr(self, "_" + attribute) is not None or attribute in self._prepared_modules:
            self.pages.setCurrentWidget(getattr(self, attribute))
            return
        if self._loading_page is None:
            from wisc.ui.content import SkeletonList
            self._loading_page = QWidget()
            loading_layout = QVBoxLayout(self._loading_page)
            loading_layout.setContentsMargins(*theme.PAGE_MARGINS)
            loading_layout.setSpacing(theme.PAGE_SPACING)
            self._loading_label = text_label("", theme.FONT_PAGE_TITLE, bold=True)
            loading_layout.addWidget(self._loading_label)
            loading_layout.addWidget(SkeletonList(), 1)
            self.pages.addWidget(self._loading_page)
        self._loading_label.setText(
            {"library": "Library", "skins": "Skins", "mods": "Mods & Modpacks", "options": "Options"}[attribute]
        )
        self.pages.setCurrentWidget(self._loading_page)
        self.progress_host.set_operation("navigation", self._loading_label.text(), priority=10, show_text=False)
        if page in self._preparations:
            return
        self._start_preparation(page, attribute)

    def _start_preparation(self, page: str, attribute: str) -> None:
        def ready(module) -> None:
            self._preparations.pop(page, None)
            self._prepared_modules.add(attribute)
            if not self._closing and self._current_page == page:
                self.progress_host.set_operation("navigation", None)
                try:
                    self.pages.setCurrentWidget(getattr(self, attribute))
                except Exception as error:
                    failed(error)

        def failed(error: Exception) -> None:
            self._preparations.pop(page, None)
            if not self._closing and self._current_page == page:
                self.progress_host.set_operation("navigation", None)
                self._loading_label.setText("Could not open this page. Select the tab to retry.")

        # Imports prepare Python code on a worker; QWidget creation stays on Qt's thread.
        self._preparations[page] = self.services.submit(
            lambda: importlib.import_module("wisc.ui." + attribute), ready, failed,
        )

    def _warm_library_modules(self) -> None:
        if not self._closing and self._library is None and "library" not in self._prepared_modules and "installations" not in self._preparations:
            self._start_preparation("installations", "library")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Warm the common next tab's code after Home paints, without constructing it.
        if "library" not in self._prepared_modules:
            self._library_preload.start(75)

    def _open_accounts(self) -> None:
        self.navigate("options")
        if self._options is not None:
            self._options.show_subpage("options_accounts")

    def _open_profile_folder(self, profile_id: str) -> None:
        raw = self._raw_profiles.get(profile_id)
        folder = launcher.get_profile_game_directory(raw) if raw else Path(launcher.minecraft_directory)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if hasattr(os, "startfile"):
                os.startfile(str(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(folder)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _cancel_launch(self) -> None:
        if self._launch_cancel is not None:
            self._launch_cancel.set()
        if self._launch_token is not None:
            self.services.cancel(self._launch_token)
            self._launch_token = None
        self.home.set_operation(None)
        self.home.show_notice("Launch cancelled.")

    def _launch_profile(self, profile_id: str) -> None:
        if self._launch_token is not None:
            return
        raw = self._raw_profiles.get(profile_id)
        if raw is None:
            self.home.show_notice("Create or select a saved installation to launch.")
            return
        settings = load_settings()
        account = get_active_account()
        username = str(account.get("username") or "Player")
        cancel_event = threading.Event()
        self._launch_cancel = cancel_event
        progress_state = {"max": 100, "status": "Preparing launch..."}
        self.home.set_operation("Preparing launch...", None)

        def emit_progress() -> None:
            maximum = max(1, int(progress_state["max"] or 100))
            current = progress_state.get("current")
            pct = None if current is None else max(0, min(100, int(current * 100 / maximum)))
            self.launch_progress.emit(progress_state["status"], pct)

        callback = {
            "setStatus": lambda text: (progress_state.update({"status": str(text)}), emit_progress()),
            "setMax": lambda val: (progress_state.update({"max": int(val) or 100}), emit_progress()),
            "setProgress": lambda val: (progress_state.update({"current": int(val)}), emit_progress()),
        }

        async def _run_launch():
            return await launcher.start_game(
                raw,
                username,
                True,
                callback,
                settings=settings,
                cancel_event=cancel_event,
            )

        def on_done(result) -> None:
            self._launch_token = None
            self._launch_cancel = None
            self.home.set_operation(None)
            process, log_file = result
            self.home.show_notice(f"Started {raw.get('name', 'Minecraft')}.")
            action = str(settings.get("launch_action", "Hide launcher"))
            if action == "Close launcher":
                self.close()
            elif action == "Hide launcher":
                self.showMinimized()

            def _wait_game() -> None:
                try:
                    process.wait()
                finally:
                    if log_file is not None:
                        try:
                            log_file.close()
                        except Exception:
                            pass

            threading.Thread(target=_wait_game, daemon=True).start()

        def on_fail(error: Exception) -> None:
            self._launch_token = None
            self._launch_cancel = None
            self.home.set_operation(None)
            self.home.show_notice(str(error) or "Launch failed.")

        self._launch_token = self.services.submit(_run_launch(), on_done, on_fail)

    def _selected_profile_changed(self, profile: HomeProfile) -> None:
        self.background.set_artwork(profile.artwork)
        if self._library is not None:
            self._library.set_selected(profile.id)

    def _library_action(self, profile_id: str, action: str) -> None:
        if action == "mods":
            if self._mods is not None:
                self._mods.enter(profile_id)
            else:
                self._requested_mod_profile = profile_id
            self.navigate("mods")
            return
        self.home.select_profile(profile_id)
        if action in ("home", "play"):
            self.navigate("home")
            if action == "play":
                self.home.launch_requested.emit(profile_id)
        elif action == "edit":
            self.home.edit_requested.emit(profile_id)
        elif action == "folder":
            self.home.folder_requested.emit(profile_id)

    def _content_progress_changed(self, message: str, current: int, total: int | None, busy: bool) -> None:
        from wisc.ui.content import format_size
        value, detail = None, ""
        if total and total > 0:
            value = current * 1000 // total
            detail = f"{format_size(current)} / {format_size(total)}"
        self.progress_host.set_operation(
            "content", message if busy else None, value, detail=detail,
            cancelable=self._mods is not None and self._mods.can_cancel_operation, priority=100,
        )

    def _home_progress_changed(self, label: str | None, progress: int | None) -> None:
        self.progress_host.set_operation(
            "home", label, None if progress is None else progress * 10, cancelable=True, priority=100,
        )

    def _skin_progress_changed(self, message: str, busy: bool) -> None:
        self.progress_host.set_operation("skins", message if busy else None)

    def _content_loading_changed(self, loading: bool) -> None:
        self.progress_host.set_operation("content-loading", "Loading content\u2026" if loading else None,
                                         priority=10, show_text=False)

    def apply_theme(self, name: str) -> None:
        custom_accent = None
        if name == "Custom":
            from wisc.core.storage import load_settings
            from wisc.core.themes import DEFAULT_CUSTOM_ACCENT
            custom_accent = str(load_settings().get("custom_accent", DEFAULT_CUSTOM_ACCENT))
        colors = get_theme(name, custom_accent) if custom_accent else get_theme(name)
        self._colors = colors
        palette = dark_palette(colors)
        QApplication.instance().setPalette(palette)
        self.setPalette(palette)
        self.setStyleSheet(stylesheet(colors))
        self.home.apply_theme(colors)
        for secondary in (self._library, self._skins, self._mods, self._options):
            if secondary is not None:
                secondary.apply_theme(colors)
        self.title_bar.apply_theme(colors)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self._shutdown()


def run() -> None:
    application = QApplication(sys.argv)
    application.setApplicationName("Wisc")
    application.setStyle("Fusion")
    install_fonts()
    window = QtLauncherWindow()
    window.show()
    exit_code = application.exec()
    window.services.close()
    window.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
