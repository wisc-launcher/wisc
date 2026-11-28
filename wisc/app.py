"""PyQt6 frontend for Wisc Launcher."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import TYPE_CHECKING, Sequence

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from wisc.core.credentials import redact_credentials
from wisc.core.paths import ASSETS_DIR
from wisc.core.themes import get_theme_names
from wisc.ui import theme as theme
from wisc.ui.components import ArtworkBackground, StaggeredReveal, resolve_profile_icon_path, text_label
from wisc.ui.home import HomePage, HomeProfile
from wisc.ui.images import ContentImages
from wisc.ui.intro import StartupIntroOverlay
from wisc.ui.logs import GameLogsWindow
from wisc.ui.progress import ProgressHost
from wisc.ui.tasks import ServiceRunner
from wisc.ui.theme import (
    DEFAULT_THEME, dark_palette, get_theme, install_focus_cues, install_fonts, stylesheet,
)
from wisc.ui.toasts import ToastHost
from wisc.ui.updates import UpdateController
from wisc.ui.window import FramelessWindow, TitleBar

if TYPE_CHECKING:
    from wisc.services.discord_presence import DiscordPresence


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


def _load_saved_profiles() -> tuple[list[HomeProfile], dict[str, dict]]:
    from wisc.core.storage import load_installations, load_profile_order

    raw_list = load_installations()
    if not raw_list:
        sample = preview_profiles()
        return sample, {}

    order = load_profile_order()
    if order:
        order_index = {pid: idx for idx, pid in enumerate(order)}
        raw_list = sorted(
            raw_list,
            key=lambda item: order_index.get(str(item.get("id", "")), len(order_index)),
        )

    from wisc.services import launcher
    from wisc.services.artwork import resolve_background_artwork

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
        icon_path = resolve_profile_icon_path(item.get("icon"))
        profiles.append(
            HomeProfile(
                id=pid,
                name=str(item.get("name") or "Minecraft"),
                version=version,
                loader=loader_name,
                artwork=art_path,
                icon=icon_path,
                installed=(not installed_ids) or (vid in installed_ids),
                last_played=(
                    float(item["last_played"])
                    if isinstance(item.get("last_played"), (int, float))
                    else None
                ),
            )
        )
    if not profiles:
        return preview_profiles(), {}
    return profiles, raw_by_id


@dataclass(frozen=True)
class _StartupData:
    theme_name: str
    profiles: list[HomeProfile]
    raw_profiles: dict[str, dict]
    presence: DiscordPresence


def _prepare_startup(profiles: Sequence[HomeProfile] | None) -> _StartupData:
    from wisc.core.storage import DATA_DIR, load_settings, load_theme_choice
    from wisc.services.discord_presence import DiscordPresence, SkinPortraitCache

    theme_name = load_theme_choice(get_theme_names())
    settings = load_settings()
    if profiles is None:
        loaded_profiles, raw_profiles = _load_saved_profiles()
    else:
        loaded_profiles, raw_profiles = list(profiles), {}
    presence = DiscordPresence(
        enabled=bool(settings.get("discord_rpc", True)),
        portrait_cache=SkinPortraitCache(DATA_DIR / "discord_portraits.json"),
    )
    return _StartupData(theme_name, loaded_profiles, raw_profiles, presence)


class QtLauncherWindow(FramelessWindow):
    page_requested = pyqtSignal(str)
    launch_progress = pyqtSignal(object, object)
    log_line_received = pyqtSignal(str, tuple)
    game_exited = pyqtSignal(int, str)

    def __init__(self, profiles: Sequence[HomeProfile] | None = None, *, defer_startup: bool = False):
        super().__init__()
        install_focus_cues()
        self.setWindowTitle("Wisc")
        self.setWindowIcon(QIcon(str(ASSETS_DIR / "icons" / "wisc.ico")))
        self.resize(1100, 650)
        self.setMinimumSize(theme.WINDOW_MIN_WIDTH, theme.WINDOW_MIN_HEIGHT)
        self._home_ready = False
        self._startup_profiles = profiles if defer_startup else None
        self._startup_token: int | None = None
        self._intro_played = False
        self._intro: StartupIntroOverlay | None = None
        self.presence: DiscordPresence | None = None
        self.updater: UpdateController | None = None
        self.toasts: ToastHost | None = None
        self._logs_window: GameLogsWindow | None = None
        self._library = self._skins = self._mods = self._options = self._profile_editor = None
        self._profile_return_page = "home"
        self._current_page = "home"
        self._preparations: dict[str, int] = {}
        self._prepared_modules: set[str] = set()
        self._library_preload = QTimer(self)
        self._library_preload.setSingleShot(True)
        self._library_preload.timeout.connect(self._warm_library_modules)
        self._external_sync_timer = QTimer(self)
        self._external_sync_timer.setInterval(3000)
        self._external_sync_timer.timeout.connect(self._poll_external_profiles)
        self._external_sources_stamp = None
        self._external_sync_token: int | None = None
        self._loading_page = None
        self._pending_options_subpage: str | None = None
        self._requested_mod_profile = None
        self._launch_token: int | None = None
        self._game_running = False
        self._focus_search_attempts = 0
        self._launch_cancel: threading.Event | None = None
        self._closing = False
        self._explicit_preview = (not defer_startup) and (profiles is not None)
        self.services = ServiceRunner(self)
        self.log_line_received.connect(self._append_log_line)
        self.game_exited.connect(self._on_game_exited)
        QApplication.instance().aboutToQuit.connect(self._shutdown)
        if not defer_startup:
            self._build_home(_prepare_startup(profiles))

    def _start_loading_home(self) -> None:
        if self._closing or self._home_ready or self._startup_token is not None:
            return
        profiles, self._startup_profiles = self._startup_profiles, None
        self._startup_token = self.services.submit(
            lambda: _prepare_startup(profiles), self._finish_loading_home, self._startup_failed,
        )

    def _finish_loading_home(self, data: _StartupData) -> None:
        self._startup_token = None
        if self._closing:
            return
        try:
            install_fonts()
            self._build_home(data)
        except Exception as error:
            self._startup_failed(error)
            return
        if self._intro is not None:
            self._intro.set_home_ready()
        elif "library" not in self._prepared_modules:
            self._library_preload.start(75)

    def _startup_failed(self, error: Exception) -> None:
        self._startup_token = None
        if not self._closing:
            QMessageBox.critical(self, "Wisc", f"Could not open the launcher.\n\n{error}")
            self.close()

    def _build_home(self, data: _StartupData) -> None:
        self._profiles = data.profiles
        self._raw_profiles = data.raw_profiles
        self._colors = get_theme(data.theme_name)
        self._reveal = StaggeredReveal(self)
        self.presence = data.presence
        self.presence.start()
        self.presence.set_page("home")
        artwork = self._profiles[0].artwork if self._profiles else ASSETS_DIR / "version-art" / "java-edition.webp"
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
        from wisc.core.storage import load_settings

        selected_id = str(load_settings().get("last_selected_profile") or "") or None if self._raw_profiles else None
        self.home = HomePage(
            self._profiles,
            self._colors,
            selected_id=selected_id,
            images=ContentImages(self.services, self),
        )
        self.pages.addWidget(self.home)
        self.progress_host = ProgressHost(self.background)
        self.progress_host.cancel_requested.connect(self._cancel_operation)
        layout.addWidget(self.progress_host)
        self.toasts = ToastHost(self.background, self._colors["btn_primary"])
        self.toasts.set_bottom_offset(theme.PROGRESS_HOST_HEIGHT + 8)
        self.updater = UpdateController(
            self.services,
            parent_widget=lambda: self,
            notify=self.notify,
            busy=lambda: self._launch_token is not None,
            close_window=self.close,
            accent=self._colors["btn_primary"],
        )
        self.updater.progress_changed.connect(self._update_progress_changed)
        self.launch_progress.connect(self.home.set_operation)
        self.home.operation_changed.connect(self._home_progress_changed)
        self.home.profile_selected.connect(self._selected_profile_changed)
        self.home.library_requested.connect(lambda: self.navigate("installations"))
        self.home.launch_requested.connect(self._launch_profile)
        self.home.cancel_requested.connect(self._cancel_launch)
        self.home.folder_requested.connect(self._open_profile_folder)
        self.home.create_requested.connect(self._open_create_profile)
        self.home.edit_requested.connect(self._open_edit_profile)
        self.home.action_requested.connect(self._library_action)
        self.home.account_requested.connect(self._open_accounts)
        self.home.logs_requested.connect(self._show_logs)
        self._install_shortcuts()
        self._refresh_home_account()
        self.apply_theme(data.theme_name)
        self._home_ready = True
        self.updater.startup()
        if not self._explicit_preview:
            self._start_background_maintenance()
        if self._intro is not None:
            self._intro.raise_()
            self._intro.setFocus()

    @property
    def profile_editor(self):
        if self._profile_editor is None:
            from wisc.ui.profile_dialog import ProfileEditorPage
            self._profile_editor = ProfileEditorPage(self.services, self._colors, self)
            self._profile_editor.back_requested.connect(self._close_profile_editor)
            self._profile_editor.profile_saved.connect(self._on_profile_saved)
            self.pages.addWidget(self._profile_editor)
        return self._profile_editor

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
            self._skins.cosmetics_changed.connect(lambda _aid: self._refresh_home_account())
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
        elif source == "update" and self.updater is not None:
            self.updater.cancel_download()

    def notify(self, message: str, kind: str = "info", title: str | None = None) -> None:
        if self.toasts is not None:
            self.toasts.show_toast(message, kind, title)
        elif self._home_ready:
            self.home.show_notice(message)

    def _show_logs(self) -> None:
        if self._logs_window is None:
            self._logs_window = GameLogsWindow(
                accent=self._colors["btn_primary"],
                on_notify=self.notify,
            )
        self._logs_window.show()
        self._logs_window.raise_()
        self._logs_window.activateWindow()

    def _append_log_line(self, line: str, sensitive_values: tuple) -> None:
        if self._logs_window is None:
            self._logs_window = GameLogsWindow(
                accent=self._colors["btn_primary"],
                on_notify=self.notify,
            )
        self._logs_window.append_line(line, sensitive_values)

    def _on_game_exited(self, return_code: int, profile_name: str) -> None:
        self._game_running = False
        self.home.set_running(False)
        if self._logs_window is not None:
            self._logs_window.set_running(False)
        if self.presence is not None:
            self.presence.game_finished()
        if not self._closing:
            from wisc.core.storage import load_settings
            if load_settings().get("launch_action", "Hide launcher") == "Hide launcher":
                self.showNormal()
                self.raise_()
                self.activateWindow()
            if return_code != 0:
                self.notify(
                    f"{profile_name} exited with code {return_code}. Open Logs for details.",
                    "error",
                    "Game Crashed",
                )

    def _start_background_maintenance(self) -> None:
        from wisc.services import instances, launcher, skins

        self.services.submit(skins.prune_skin_cache, lambda _n: None, lambda _e: None)

        def sync_initial():
            changed = instances.sync_local_installations()
            stamp = instances.installation_sources_stamp(launcher.minecraft_directory)
            return changed, stamp

        def on_synced(res) -> None:
            changed, stamp = res
            self._external_sources_stamp = stamp
            if changed and not self._closing:
                self._reload_profiles()
                self.notify("Your library is synced with local Minecraft installations.", "info", "Library updated")
            if not self._closing:
                self._external_sync_timer.start()

        self.services.submit(sync_initial, on_synced, lambda _e: None)

    def _poll_external_profiles(self) -> None:
        if self._closing or self._launch_token is not None or self._external_sync_token is not None:
            return
        from wisc.services import instances, launcher

        def check_sync():
            stamp = instances.installation_sources_stamp(launcher.minecraft_directory)
            if stamp == self._external_sources_stamp:
                return False, stamp
            changed = instances.sync_local_installations()
            return changed, stamp

        def on_done(res) -> None:
            self._external_sync_token = None
            changed, stamp = res
            self._external_sources_stamp = stamp
            if changed and not self._closing:
                self._reload_profiles()
                self.notify("Your library is synced with local Minecraft installations.", "info", "Library updated")

        self._external_sync_token = self.services.submit(
            check_sync,
            on_done,
            lambda _e: setattr(self, "_external_sync_token", None),
        )

    def _shutdown(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._intro is not None:
            self._intro.shutdown()
        self.services.cancel(self._startup_token)
        self._startup_token = None
        self.services.cancel(self._external_sync_token)
        self._external_sync_token = None
        self._external_sync_timer.stop()
        self._library_preload.stop()
        for token in self._preparations.values():
            self.services.cancel(token)
        self._preparations.clear()
        if self._logs_window is not None:
            self._logs_window.close()
            self._logs_window.deleteLater()
            self._logs_window = None
        if self._mods is not None:
            self._mods.shutdown()
        if self._skins is not None:
            self._skins.shutdown()
        if self._options is not None:
            self._options.shutdown()
        if self.updater is not None and not self.updater.applying:
            self.updater.stop()
        if self.toasts is not None:
            self.toasts.clear()
        if self.presence is not None:
            self.presence.stop()
        self.services.close()

    @property
    def options(self):
        if self._options is None:
            from wisc.ui.options import OptionsPage
            self._options = OptionsPage(
                self.services,
                self._colors,
                updater=self.updater,
                progress=self._report_options_progress,
            )
            self._options.theme_requested.connect(self.apply_theme)
            self._options.accounts_changed.connect(self._refresh_home_account)
            self._options.settings_changed.connect(self._on_settings_changed)
            self.pages.addWidget(self._options)
        return self._options

    def _on_settings_changed(self, settings: dict) -> None:
        if self.presence is not None:
            self.presence.set_enabled(bool(settings.get("discord_rpc", True)))

    def _install_shortcuts(self) -> None:
        """Bind the launcher's global keyboard shortcuts once Home exists."""
        for index, page in enumerate(("home", "installations", "skins", "mods", "options"), start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.activated.connect(lambda target=page: self.navigate(target))
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self._focus_search)
        QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(self._show_logs)

    def _focus_search(self) -> None:
        if self._current_page == "installations" and self._library is not None:
            self._library.focus_search()
            return
        if self._current_page == "mods" and self._mods is not None:
            self._mods.focus_search()
            return
        self.navigate("installations")
        self._focus_search_attempts = 0
        QTimer.singleShot(150, self._focus_search_when_ready)

    def _focus_search_when_ready(self) -> None:
        if self._library is not None:
            self._library.focus_search()
            return
        # The Library builds on the service worker; wait for it instead of losing focus.
        self._focus_search_attempts += 1
        if self._focus_search_attempts < 12:
            QTimer.singleShot(250, self._focus_search_when_ready)

    def _report_options_progress(self, label: str | None, value: int | None = None) -> None:
        if label:
            self.progress_host.set_operation(
                "options-java",
                label,
                None if value is None else value * 10,
                cancelable=False,
                priority=60,
            )
        else:
            self.progress_host.set_operation("options-java", None)

    def navigate(self, page: str) -> None:
        if self._closing or not self._home_ready:
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
        if page == self._current_page and self.pages.currentWidget() not in (self._loading_page, self._profile_editor):
            return
        self._current_page = page
        if self.presence is not None:
            self.presence.set_page("settings" if page == "options" else ("library" if page == "installations" else page))
        self.background.set_frosted(page != "home")
        self.title_bar.set_current_page(page)
        attribute = attributes[page]
        self.progress_host.set_operation("navigation", None)
        if page == "home" or getattr(self, "_" + attribute) is not None or attribute in self._prepared_modules:
            if page == "home":
                self._refresh_home_account()
            existed = page == "home" or getattr(self, "_" + attribute, None) is not None
            target_widget = getattr(self, attribute)
            self.pages.setCurrentWidget(target_widget)
            if existed:
                self._reveal.reveal(target_widget)
            else:
                # A page built on first navigation is shown settled, not animated.
                self._reveal.stop()
            return
        if self._loading_page is None:
            self._loading_page = QWidget()
            loading_layout = QVBoxLayout(self._loading_page)
            loading_layout.setContentsMargins(*theme.PAGE_MARGINS)
            loading_layout.setSpacing(theme.PAGE_SPACING)
            self._loading_label = text_label("", theme.FONT_BODY, muted=True)
            loading_layout.addWidget(self._loading_label)
            loading_layout.addStretch(1)
            self.pages.addWidget(self._loading_page)
        title = {"library": "Library", "skins": "Skins", "mods": "Mods & Modpacks", "options": "Settings"}[attribute]
        self._loading_label.setText("")
        self.pages.setCurrentWidget(self._loading_page)
        self.progress_host.set_operation("navigation", title, priority=10, show_text=False)
        if page in self._preparations:
            return
        self._start_preparation(page, attribute)

    def _nav_origin(self, page: str, target_widget: QWidget) -> QPoint | None:
        button = self.title_bar.buttons.get(page)
        if button is None:
            return None
        global_pos = button.mapToGlobal(QPoint(button.width() // 2, button.height() // 2))
        return target_widget.mapFromGlobal(global_pos)

    def _start_preparation(self, page: str, attribute: str) -> None:
        def ready(module) -> None:
            self._preparations.pop(page, None)
            self._prepared_modules.add(attribute)
            if not self._closing and self._current_page == page:
                self.progress_host.set_operation("navigation", None)
                try:
                    target_widget = getattr(self, attribute)
                    if page == "options" and self._pending_options_subpage:
                        subpage = self._pending_options_subpage
                        self._pending_options_subpage = None
                        target_widget.show_subpage(subpage, animate=False)
                    # First appearance: show the settled page instead of animating content
                    # that is about to change (skin state, mod reload, settings cards), which
                    # would be cancelled mid-wave and snap into place.
                    self._reveal.stop()
                    self.pages.setCurrentWidget(target_widget)
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

    def _refresh_home_account(self) -> None:
        from wisc.core.storage import get_active_account

        account = get_active_account()
        username = str(account.get("username") or "Player")
        acc_type = str(account.get("type") or "offline")
        skin_path: Path | None = None
        try:
            from wisc.services.skins import fetch_ely_skin, get_skins_dir, load_active_skin_choice
            if acc_type == "ely":
                clean = username.strip().lower()
                ely_cache = get_skins_dir() / f"ely_{clean}.png"
                if ely_cache.is_file():
                    skin_path = ely_cache
                elif clean:
                    self.services.submit(
                        lambda u=username: fetch_ely_skin(u),
                        lambda _res, u=username, p=ely_cache: self.home.set_account(u, p) if (not self._closing and p.is_file()) else None,
                    )
            else:
                choice = load_active_skin_choice()
                custom = str(choice.get("custom_path") or "").strip()
                if custom and Path(custom).is_file():
                    skin_path = Path(custom)
                elif choice.get("model") == "slim":
                    slim = ASSETS_DIR / "skins" / "default_alex.png"
                    if slim.is_file():
                        skin_path = slim
        except Exception:
            pass
        self.home.set_account(username, skin_path)

    def _open_accounts(self) -> None:
        if self._options is not None:
            self.navigate("options")
            self._options.show_subpage("options_accounts")
        else:
            self._pending_options_subpage = "options_accounts"
            self.navigate("options")

    def _open_profile_folder(self, profile_id: str) -> None:
        from wisc.services import launcher

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
        if self._launch_token is not None or self._game_running:
            self.services.cancel(self._launch_token)
            self._launch_token = None
        self.home.set_operation(None)
        self.home.set_running(False)
        self.home.show_notice("Launch cancelled.")

    def _launch_profile(self, profile_id: str) -> None:
        if self.updater is not None and self.updater.applying:
            self.notify("Wait for the launcher update to finish before launching Minecraft.", "warning", "Updates")
            return
        if self._launch_token is not None or self._game_running:
            return
        raw = self._raw_profiles.get(profile_id)
        if raw is None:
            self.home.show_notice("Create or select a saved installation to launch.")
            return
        from wisc.core.storage import get_active_account, load_settings
        from wisc.services import launcher

        settings = load_settings()
        account = get_active_account()
        username = str(account.get("username") or "Player").strip() or "Player"
        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", username):
            self.notify("Your username must contain 1\u201316 letters, numbers, or underscores.", "warning", "Invalid username")
            return

        selected_home = self.home.selected_profile
        is_downloading = bool(selected_home and not selected_home.installed)
        if self.presence is not None:
            self.presence.prepare_game(raw, installing=is_downloading)

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

        def _run_launch_sync():
            import asyncio
            from wisc.services import instances

            async def _run_launch():
                online_available = await asyncio.to_thread(instances.check_internet_connection)
                if online_available and account.get("type") == "ely":
                    full_acc = await asyncio.to_thread(get_active_account, include_credentials=True)
                    if not full_acc.get("access_token"):
                        raise RuntimeError("Sign in again to launch Minecraft with your Ely.by account.")
                return await launcher.start_game(
                    raw,
                    username,
                    online_available,
                    callback,
                    settings=settings,
                    cancel_event=cancel_event,
                )

            return asyncio.run(_run_launch())

        def on_done(result) -> None:
            self._launch_token = None
            self._launch_cancel = None
            self.home.set_operation(None)
            process, log_file = result
            self._game_running = True
            self.home.set_running(True)
            profile_name = str(raw.get("name") or "Minecraft")
            self.home.show_notice(f"Started {profile_name}.")
            profile_id = str(raw.get("id", ""))
            self.home.update_played(profile_id, time.time())

            def _mark_played() -> bool:
                from wisc.core.storage import mark_profile_played

                return mark_profile_played(profile_id)

            self.services.submit(_mark_played, lambda _result: None, lambda _error: None)
            if self._logs_window is not None:
                self._logs_window.set_running(True)
            if self.presence is not None:
                player_info = getattr(process, "wisc_presence_player", None) or {}
                self.presence.game_started(
                    raw,
                    player_name=player_info.get("username", username),
                    face_png=getattr(process, "wisc_presence_face", None),
                )
            action = str(settings.get("launch_action", "Hide launcher"))
            if action == "Close launcher":
                self.close()
            elif action == "Hide launcher":
                self.showMinimized()

            sensitive = tuple(getattr(process, "wisc_sensitive_values", ()) or ())

            def _wait_game() -> None:
                code = 0
                try:
                    if process.stdout is not None:
                        for line in process.stdout:
                            cleaned = redact_credentials(line.rstrip("\r\n"), sensitive)
                            if cleaned and log_file is not None:
                                try:
                                    log_file.write(cleaned + "\n")
                                    log_file.flush()
                                except Exception:
                                    pass
                            self.log_line_received.emit(line, sensitive)
                    code = process.wait()
                except Exception:
                    try:
                        code = process.wait()
                    except Exception:
                        code = 0
                finally:
                    if log_file is not None:
                        try:
                            log_file.close()
                        except Exception:
                            pass
                    self.game_exited.emit(int(code), profile_name)

            threading.Thread(target=_wait_game, daemon=True).start()

        def on_fail(error: Exception) -> None:
            self._launch_token = None
            self._launch_cancel = None
            self.home.set_operation(None)
            self.home.set_running(False)
            if self.presence is not None:
                self.presence.game_finished()
            self.home.show_notice(str(error) or "Launch failed.")
            self.notify(str(error) or "Launch failed.", "error", "Launch Failed")

        self._launch_token = self.services.submit(_run_launch_sync, on_done, on_fail)

    def _selected_profile_changed(self, profile: HomeProfile) -> None:
        self.background.set_artwork(profile.artwork)
        if self._library is not None:
            self._library.set_selected(profile.id)
        if self._raw_profiles:
            from wisc.core.storage import load_settings, save_settings
            settings = load_settings()
            if settings.get("last_selected_profile") != profile.id:
                settings["last_selected_profile"] = profile.id
                save_settings(settings)

    def _library_action(self, profile_id: str, action: str) -> None:
        if action == "mods":
            if self._mods is not None:
                self._mods.enter(profile_id)
            else:
                self._requested_mod_profile = profile_id
            self.navigate("mods")
            return
        if action == "edit":
            self._open_edit_profile(profile_id)
            return
        if action == "duplicate":
            self._duplicate_profile(profile_id)
            return
        if action == "repair":
            self._repair_profile(profile_id)
            return
        if action == "move_up":
            self._move_profile(profile_id, -1)
            return
        if action == "move_down":
            self._move_profile(profile_id, 1)
            return
        if action == "delete":
            self._delete_profile(profile_id)
            return
        self.home.select_profile(profile_id)
        if action in ("home", "play"):
            self.navigate("home")
            if action == "play":
                self.home.launch_requested.emit(profile_id)
        elif action == "folder":
            self.home.folder_requested.emit(profile_id)

    def _reload_profiles(self, select_id: str | None = None) -> None:
        loaded_profiles, raw_by_id = _load_saved_profiles()
        self._profiles = loaded_profiles
        self._raw_profiles = raw_by_id
        self.home.set_profiles(loaded_profiles, selected_id=select_id)
        if self._library is not None:
            self._library.set_profiles(loaded_profiles, selected_id=select_id)

    def _open_create_profile(self) -> None:
        self._profile_return_page = self._current_page
        self.background.set_frosted(True)
        appeared = self._profile_editor is not None
        self.profile_editor.open_profile(
            None,
            existing_profiles=list(self._raw_profiles.values()),
        )
        self.pages.setCurrentWidget(self.profile_editor)
        if appeared:
            self._reveal.reveal(self.profile_editor)
        else:
            # The editor repopulates versions and choices right after it appears.
            self._reveal.stop()

    def _open_edit_profile(self, profile_id: str) -> None:
        raw = self._raw_profiles.get(profile_id)
        if raw is None:
            self.home.show_notice("Preview profiles cannot be edited. Create a new profile instead.")
            return
        self._profile_return_page = self._current_page
        self.background.set_frosted(True)
        appeared = self._profile_editor is not None
        self.profile_editor.open_profile(
            raw,
            existing_profiles=list(self._raw_profiles.values()),
        )
        self.pages.setCurrentWidget(self.profile_editor)
        if appeared:
            self._reveal.reveal(self.profile_editor)
        else:
            self._reveal.stop()

    def _close_profile_editor(self) -> None:
        target = self._profile_return_page or "home"
        self.navigate(target)

    def _on_profile_saved(self, record: dict, is_new: bool) -> None:
        self._reload_profiles(record.get("id"))
        self._close_profile_editor()
        name = record.get("name", "Profile")
        self.home.show_notice(f"Created '{name}'." if is_new else f"Saved '{name}'.")

    def _duplicate_profile(self, profile_id: str) -> None:
        raw = self._raw_profiles.get(profile_id)
        if raw is None:
            self.home.show_notice("Preview profiles cannot be duplicated.")
            return
        import uuid
        from wisc.core import storage
        from wisc.services import launcher, profiles as profile_service
        copy_record = dict(raw)
        copy_record["id"] = str(uuid.uuid4())
        copy_record["name"] = f"{raw.get('name', 'Profile')} Copy"
        copy_record.pop("game_directory", None)
        copy_record.pop("instance_name", None)
        try:
            if copy_record.get("is_instance"):
                base = profile_service.instance_folder_name("", copy_record["name"])
                folder_name = base
                suffix = 2
                all_profiles = storage.load_installations()
                while True:
                    try:
                        profile_service.new_instance_directory(
                            launcher.minecraft_directory, folder_name, copy_record["name"], all_profiles,
                        )
                        break
                    except FileExistsError:
                        folder_name = f"{base}_{suffix}"
                        suffix += 1
            else:
                folder_name = ""
            saved = profile_service.save_new_profile(
                copy_record, launcher.minecraft_directory, folder_name, storage,
            )
        except Exception as exc:
            self.home.show_notice(str(exc) or "Could not duplicate profile.")
            return
        self._reload_profiles(saved.get("id"))
        self.home.show_notice(f"Duplicated '{raw.get('name', 'Profile')}'.")

    def _delete_profile(self, profile_id: str) -> None:
        raw = self._raw_profiles.get(profile_id)
        if raw is None:
            self.home.show_notice("Preview profiles cannot be deleted.")
            return
        from wisc.services import instances
        from wisc.ui.profile_dialog import confirm_delete_profile
        name = str(raw.get("name") or "Profile")
        confirmed, delete_files = confirm_delete_profile(
            self, name, bool(raw.get("is_instance")), self._colors,
        )
        if not confirmed:
            return
        try:
            instances.remove_profile_record(profile_id, delete_files=delete_files)
        except Exception as exc:
            self.home.show_notice(str(exc) or "Could not delete profile.")
            return
        self._reload_profiles()
        self.home.show_notice(f"Deleted '{name}'.")

    def _move_profile(self, profile_id: str, delta: int) -> None:
        if not self._raw_profiles:
            return
        ids = [profile.id for profile in self._profiles]
        if profile_id not in ids:
            return
        idx = ids.index(profile_id)
        target_idx = idx + delta
        if target_idx < 0 or target_idx >= len(ids):
            return
        ids[idx], ids[target_idx] = ids[target_idx], ids[idx]
        from wisc.core.storage import save_profile_order
        if save_profile_order(ids):
            self._reload_profiles(select_id=profile_id)
            self.notify("Your profile order has been saved.", "success", "Profiles reordered")

    def _repair_profile(self, profile_id: str) -> None:
        if self._launch_token is not None:
            return
        raw = self._raw_profiles.get(profile_id)
        if raw is None:
            self.notify("Preview profiles cannot be repaired.", "info", "Repair")
            return
        from wisc.services import launcher

        loader = str(raw.get("loader") or "Vanilla").strip()
        mc_ver = str(raw.get("minecraft_version") or raw.get("version_id") or "").strip()
        loader_ver = str(raw.get("loader_version") or "").strip()
        name = str(raw.get("name") or "Profile")
        if not mc_ver:
            self.notify("This profile is missing its Minecraft version.", "error", "Cannot repair profile")
            return

        cancel_event = threading.Event()
        self._launch_cancel = cancel_event
        progress_state = {"max": 100, "status": f"Repairing {name}..."}
        self.home.set_operation(f"Repairing {name}...", None)
        self.notify(f"Repairing and verifying {name}...", "info", "Repair started")

        def emit_progress() -> None:
            maximum = max(1, int(progress_state["max"] or 100))
            current = progress_state.get("current")
            pct = None if current is None else max(0, min(100, int(current * 100 / maximum)))
            self.launch_progress.emit(progress_state["status"], pct)

        def _checked(fn):
            def wrapper(*args):
                if cancel_event.is_set():
                    raise launcher.DownloadCancelled("Repair cancelled.")
                return fn(*args)
            return wrapper

        callback = {
            "setStatus": _checked(lambda text: (progress_state.update({"status": str(text)}), emit_progress())),
            "setMax": _checked(lambda val: (progress_state.update({"max": int(val) or 100}), emit_progress())),
            "setProgress": _checked(lambda val: (progress_state.update({"current": int(val)}), emit_progress())),
        }

        def run_repair():
            import minecraft_launcher_lib
            if loader.lower() == "vanilla":
                minecraft_launcher_lib.install.install_minecraft_version(
                    mc_ver, launcher.minecraft_directory, callback,
                )
            else:
                mod_loader = launcher.get_mod_loader(loader)
                mod_loader.install(
                    mc_ver,
                    launcher.minecraft_directory,
                    loader_version=loader_ver,
                    callback=callback,
                )
            launcher.invalidate_installed_versions_cache()

        def on_done(_res) -> None:
            self._launch_token = None
            self._launch_cancel = None
            self.home.set_operation(None)
            self._reload_profiles(select_id=profile_id)
            self.notify(f"Successfully repaired {name}.", "success", "Repair complete")

        def on_fail(error: Exception) -> None:
            self._launch_token = None
            self._launch_cancel = None
            self.home.set_operation(None)
            if isinstance(error, launcher.DownloadCancelled):
                self.notify("Repair cancelled.", "info", "Repair")
            else:
                self.notify(str(error) or "Repair failed.", "error", "Repair failed")

        self._launch_token = self.services.submit(run_repair, on_done, on_fail)

    def _update_progress_changed(self, label, value, detail) -> None:
        self.progress_host.set_operation(
            "update", label, value, detail=detail or "", cancelable=True, priority=90,
        )

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
        colors = get_theme(name)
        self._colors = colors
        palette = dark_palette(colors)
        QApplication.instance().setPalette(palette)
        self.setPalette(palette)
        self.setStyleSheet(stylesheet(colors))
        self.home.apply_theme(colors)
        for secondary in (self._library, self._skins, self._mods, self._options, self._profile_editor):
            if secondary is not None:
                secondary.apply_theme(colors)
        self.title_bar.apply_theme(colors)
        if self.toasts is not None:
            self.toasts.set_accent(colors["btn_primary"])
        if self.updater is not None:
            self.updater.set_accent(colors["btn_primary"])
        if self._logs_window is not None:
            self._logs_window.set_accent(colors["btn_primary"])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._intro_played:
            self._intro_played = True
            self._intro = StartupIntroOverlay(self, home_ready=self._home_ready)
            self._intro.finished.connect(self._dispose_intro)
            if not self._home_ready:
                self._intro.first_painted.connect(
                    self._start_loading_home, Qt.ConnectionType.QueuedConnection,
                )
            self._intro.start()
        # Warm the common next tab's code after Home paints, without constructing it.
        if self._home_ready and "library" not in self._prepared_modules:
            self._library_preload.start(75)

    def _dispose_intro(self) -> None:
        intro, self._intro = self._intro, None
        if intro is not None:
            intro.deleteLater()
        if self._home_ready and "library" not in self._prepared_modules:
            self._library_preload.start(75)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        intro = getattr(self, "_intro", None)
        if intro is not None and intro.isVisible():
            intro.setGeometry(self.rect())
        if getattr(self, "toasts", None) is not None:
            self.toasts.reposition()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self._shutdown()


def run() -> None:
    application = QApplication(sys.argv)
    application.setApplicationName("Wisc")
    application.setStyle("Fusion")
    window = QtLauncherWindow(defer_startup=True)
    window.show()
    exit_code = application.exec()
    window._shutdown()
    window.deleteLater()
    application.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    sys.exit(exit_code)


if __name__ == "__main__":
    run()
