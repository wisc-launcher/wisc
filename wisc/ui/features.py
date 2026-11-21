"""Current launcher features hosted inside the original tabbed interface."""

from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from typing import Callable

import flet as ft

from wisc.core.credentials import redact_credentials
from wisc.services.discord_presence import DiscordPresence, SkinPortraitCache
from wisc.services import launcher
from wisc.core import state
from wisc.core import storage
from wisc.ui import theme
from wisc.ui.shell import TITLE_BAR_HEIGHT
from wisc.ui.dialogs import ProfileDialogHost
from wisc.ui.mods import ModsPage
from wisc.ui.motion import StaggeredReveal
from wisc.ui.controls import launcher_button, search_input
from wisc.ui.profile_assets import ProfileIconField, profile_icon, profile_badges, profile_summary
from wisc.ui.progress import ProgressHost
from wisc.ui.toasts import ToastHost
from wisc.ui.updates import UpdateController


def load_ui_installations() -> list[dict]:
    """Keep saved profiles and ordering, with the original UI's loader labels."""
    names = {name.casefold(): name for name in ("Vanilla", "Fabric", "Forge", "NeoForge", "Quilt", "OptiFine")}
    profiles = storage.sort_profiles(storage.load_installations(), storage.load_profile_order())
    return [{**profile, "loader": names.get(str(profile.get("loader", "Vanilla")).casefold(), profile.get("loader"))}
            for profile in profiles]


class LegacyFeatures:
    def __init__(self, page: ft.Page, *, close: Callable):
        self.page = page
        self.dialogs: ProfileDialogHost | None = None
        self.progress = ProgressHost(page)
        self.toasts = ToastHost(page, title_bar_height=TITLE_BAR_HEIGHT)
        self.reveal = StaggeredReveal(page, ft.Container())
        self.file_picker = ft.FilePicker()
        page.services.append(self.file_picker)
        self.library = None
        self.updater = None
        self.mods = ModsPage(
            page, get_profiles=load_ui_installations, selected_profile=self.selected_profile,
            game_directory=launcher.get_profile_game_directory,
            is_running=lambda: bool(state.launcher_log_state.get("running") or (self.updater and self.updater.applying)),
            notify=self.notify, dialogs=lambda: self.dialogs, open_folder=self.open_folder,
            create_profile=lambda: self.navigate("new_installation"), profile_icon=self.profile_icon,
            profile_badges=profile_badges, profile_details=profile_summary,
            on_changed=self.profiles_changed, progress=self.progress, entrance=self.reveal,
            runtime_directory=Path(launcher.minecraft_directory), on_play=self.play_profile,
        )
        self.updater = UpdateController(
            page, notify=self.notify, progress=self.progress, dialogs=lambda: self.dialogs,
            busy=lambda: bool(state.launcher_log_state.get("running") or self.mods.busy), close=close,
        )
        self.presence = DiscordPresence(
            enabled=bool(storage.load_settings().get("discord_rpc", True)) and not page.web,
            portrait_cache=SkinPortraitCache(storage.DATA_DIR / "discord_portraits.json"),
        )
        self.on_repair = None
        self.on_profiles_changed: Callable[[], None] | None = None
        self.open_ely_login = None
        self.account_login_cancel = None
        self.started = False
        self.closed = False
        self.skin_viewer = None
        self.update_badge: ft.Container | None = None
        self.updater.on_state_change = self.refresh_update_badge

    def apply_theme(self, palette: dict[str, str]) -> None:
        theme.apply_legacy_theme(palette)
        visited = {}

        def recolor(value):
            if isinstance(value, theme.ThemeColor):
                current = theme.resolve_color(value)
                return value if current == value else current
            if isinstance(value, list):
                updated = [recolor(item) for item in value]
                return value if all(a is b for a, b in zip(value, updated)) else updated
            if isinstance(value, tuple):
                updated = tuple(recolor(item) for item in value)
                return value if all(a is b for a, b in zip(value, updated)) else updated
            if isinstance(value, dict):
                updated = {key: recolor(item) for key, item in value.items()}
                return value if all(updated[key] is item for key, item in value.items()) else updated
            if is_dataclass(value):
                if id(value) in visited:
                    return visited[id(value)]
                visited[id(value)] = value
                changes = {}
                for field in fields(value):
                    # Button styles have Flet's "skip" metadata, but contain
                    # visible colors. Exclude application data and internals.
                    if field.name.startswith("_") or not field.init or field.name in ("data", "key"):
                        continue
                    current = getattr(value, field.name)
                    updated = recolor(current)
                    if updated is not current:
                        changes[field.name] = updated
                if not isinstance(value, ft.Control) or hasattr(value, "_frozen"):
                    # Flet freezes newly reconciled menu items and their children.
                    # Replace them through their mutable parent instead of changing
                    # the frozen snapshot; shared references use the same copy.
                    updated = replace(value, **changes) if changes else value
                    visited[id(value)] = updated
                    return updated
                for name, updated in changes.items():
                    setattr(value, name, updated)
            return value

        updater_controls = [value for value in vars(self.updater).values() if isinstance(value, ft.Control)]
        for control in (self.mods, self.progress, self.toasts, *updater_controls):
            recolor(control)
        # Cached rows keep the same semantic colors, including offscreen rows.
        for cache in (self.mods._row_cache, self.mods.modpacks_page._row_cache):
            for key, (signature, control) in list(cache.items()):
                cache[key] = (signature, recolor(control))
        self.mods._render()

    def edit_latest_profile(self) -> None:
        if self.busy or self.dialogs is None:
            self.notify("Wait for the current operation to finish.", "warning")
            return
        options = storage.load_latest_release_options()
        arguments = search_input(label="Extra Java arguments", value=options.get("jvm_arguments", ""),
                                 prefix_icon=None, expand=False)
        icon = ProfileIconField(self.page, options, file_picker=self.file_picker, notify=self.notify)

        def save(event):
            try:
                saved_icon = icon.saved_value()
            except (OSError, ValueError) as error:
                self.notify(f"Could not save the profile icon: {error}", "error")
                return
            if not storage.save_latest_release_options({**options, "jvm_arguments": arguments.value or "", "icon": saved_icon}):
                self.notify("Could not save the Latest Release options.", "error")
                return
            self.dialogs.close()
            self.profiles_changed()
            self.notify("Latest Release options saved.", "success")

        self.dialogs.show(ft.Column([icon, arguments], spacing=16), title=ft.Text("Latest Release", color=theme.TEXT, size=20, weight=ft.FontWeight.BOLD),
            actions=[launcher_button("Cancel", lambda e: self.dialogs.close()),
                     launcher_button("Save", save, primary=True)], on_cancel=lambda: None, width=508, height=340)

    @property
    def busy(self) -> bool:
        return bool(state.launcher_log_state.get("running") or self.mods.busy or self.updater.applying)

    def notify(self, message, kind="info", title=None, **kwargs) -> None:
        self.toasts.show(redact_credentials(str(message)), kind, title, **kwargs)

    def mount(self, body: ft.Container, area: ft.Container) -> None:
        self.reveal.host = body
        self.dialogs = ProfileDialogHost(body, title_bar_height=0)
        area.content.controls.append(self.dialogs)
        self.page.on_keyboard_event = self.dialogs.handle_keyboard_event

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.toasts.start()
        self.progress.start()
        self.presence.start()
        self.page.run_task(self.updater.startup)

    def stop(self, event=None) -> None:
        if self.closed:
            return
        self.closed = True
        if self.account_login_cancel is not None:
            self.account_login_cancel()
            self.account_login_cancel = None
        self.updater.stop()
        if self.dialogs:
            self.dialogs.close(animate=False)
        self.mods.leave()
        if self.library:
            self.library.leave()
        self.toasts.close()
        self.progress.close()
        self.presence.stop()
        if self.skin_viewer:
            self.skin_viewer.suspend()

    def navigate(self, name: str, profile_id=None) -> None:
        navigate = state.navigation_state.get("navigate")
        if navigate:
            navigate(name, profile_id)

    def profiles_changed(self) -> None:
        if self.on_profiles_changed:
            self.on_profiles_changed()
        if state.active_page.get("name") in ("home", "installations"):
            navigate = state.navigation_state.get("navigate")
            if navigate:
                navigate(state.active_page["name"], force=True)

    def move_profile(self, profile_id: str, direction: int) -> None:
        if self.busy:
            self.notify("Wait for the current operation to finish.", "warning")
            return
        profiles = load_ui_installations()
        ids = [profile["id"] for profile in profiles]
        if profile_id not in ids:
            return
        index = ids.index(profile_id)
        target = max(0, min(len(ids) - 1, index + direction))
        ids[index], ids[target] = ids[target], ids[index]
        if not storage.save_profile_order(ids):
            self.notify("Could not save the profile order.", "error")
            return
        self.profiles_changed()

    def reorder_profiles(self, profile_ids: list[str]) -> bool:
        if self.busy:
            self.notify("Wait for the current operation to finish.", "warning")
            return False
        current = [profile["id"] for profile in load_ui_installations()]
        if len(profile_ids) != len(set(profile_ids)) or set(profile_ids) != set(current):
            self.notify("The profiles changed. Refresh the list before reordering.", "warning")
            return False
        if not storage.save_profile_order(profile_ids):
            self.notify("Could not save the profile order.", "error")
            return False
        return True

    def selected_profile(self) -> dict | None:
        key = state.launch_selection.get("key")
        return next((profile for profile in load_ui_installations() if profile["id"] == key), None)

    def play_profile(self, profile: dict) -> None:
        if self.busy:
            self.notify("Wait for the current operation to finish.", "warning")
            return
        state.launch_selection["key"] = profile["id"]
        options = storage.load_profile_options()
        if not storage.save_profile_options(options["player_name"], profile["id"], options["profile_picture_path"]):
            self.notify("Could not save the selected profile.", "error")
            return
        self.navigate("home")
        launch = state.launcher_log_state.get("launch_selected_game")
        if launch:
            self.page.run_task(launch)

    @staticmethod
    def open_folder(folder: Path) -> None:
        from wisc.ui.options import open_system_folder

        open_system_folder(str(folder))

    def open_profile_folder(self, profile: dict) -> None:
        try:
            folder = launcher.get_profile_game_directory(profile)
            if profile.get("is_instance") and not folder.is_dir():
                raise FileNotFoundError("This instance folder is missing. Restore it before opening or launching it.")
            self.open_folder(folder)
        except (OSError, ValueError) as error:
            self.notify(error, "error", "Could not open game folder")

    @staticmethod
    def profile_icon(profile: dict) -> ft.Control:
        return profile_icon(profile)

    def enter(self, name: str, profile_id=None, *, defer_load: bool = False) -> None:
        if self.account_login_cancel is not None:
            self.account_login_cancel()
            self.account_login_cancel = None
        self.reveal.finish(update=False)
        if self.library and name != "installations":
            self.library.leave()
        if self.skin_viewer:
            self.skin_viewer.suspend()
            self.skin_viewer = None
        if name == "mods":
            self.mods.enter(profile_id, defer_load=defer_load)
        else:
            self.mods.leave()
        self.presence.set_page({"installations": "library", "options_accounts": "accounts", "account_login": "accounts"}.get(
            name, "settings" if name.startswith("options") else name))
        self.presence.set_enabled(bool(storage.load_settings().get("discord_rpc", True)) and not self.page.web)

    def player_changed(self, face_png: bytes | None = None) -> None:
        account = storage.get_active_account()
        self.presence.set_player(account.get("username", "Player"), None if account.get("type") == "offline" else face_png)

    def refresh_update_badge(self) -> None:
        if self.update_badge:
            self.update_badge.visible = self.updater.phase in ("available", "downloading", "ready")
            try:
                self.update_badge.update()
            except RuntimeError:
                pass

    async def repair_profile(self, profile: dict) -> None:
        if self.on_repair:
            await self.on_repair(profile)
