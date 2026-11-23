"""Application navigation, launch actions, and Flet page wiring."""

import asyncio
from functools import partial
import os
import re
import subprocess
import threading
import uuid
import warnings
import webbrowser
from pathlib import Path

import minecraft_launcher_lib

from wisc.services import skins
from wisc.core import state
from wisc.core import storage
from wisc.ui.options import build_options_views
from wisc.ui.skins import build_skins_view as build_skins_view_external

warnings.filterwarnings("ignore", category=DeprecationWarning)

import flet as ft
from wisc.ui.controls import LegacySelector
from wisc.ui import theme as ui_theme
from wisc.ui.glass import glass_palette
from wisc.ui.features import LegacyFeatures, load_ui_installations as load_installations
from wisc.ui.library import build_library_view
from wisc.ui.home import build_home_view
from wisc.ui.onboarding import OnboardingView
from wisc.ui.window import build_window_resize_handles
from wisc.ui.shell import (
    GLASS_COLOR, GLASS_MUTED, GLASS_TEXT, HOME_BACKDROP_OPACITY,
    TITLE_BAR_HEIGHT, LauncherBackground,
)
from wisc.core.credentials import redact_credentials
from wisc.core.paths import ASSETS_DIR
from wisc.services.instances import check_internet_connection, read_game_output
from wisc.services.instances import installation_sources_stamp, sync_local_installations
from wisc.core.themes import CUSTOM_THEME, get_theme, get_theme_names, normalize_accent
from wisc.services.launcher import (
    discover_local_instances,
    get_external_installations,
    get_installed_versions,
    invalidate_installed_versions_cache,
    get_local_version_catalog,
    get_mod_loader,
    get_version_catalog,
    DownloadCancelled,
    import_external_installations,
    minecraft_directory,
    get_system_memory_mb,
    start_game,
    InstallationProgressTracker,
    get_profile_version_id,
    get_latest_release_version,
    prepare_launch_profile,
)
from wisc.core.storage import (
    load_handled_external_profile_ids,
    load_latest_release_id,
    load_profile_options,
    load_settings,
    load_theme_choice,
    save_installations,
    save_settings,
    save_theme_choice,
    get_active_account,
)

LATEST_RELEASE_PROFILE_ID = "latest-release"
_PROGRESS_UNCHANGED = object()


def main(page: ft.Page):
    page.window.icon = str(ASSETS_DIR / "icons" / "wisc.ico")
    available_themes = get_theme_names()
    installations = load_installations()
    profile_options = load_profile_options()
    settings = load_settings()
    maximum_memory_mb = get_system_memory_mb()
    settings["ram_mb"] = min(
        maximum_memory_mb, max(256, int(settings.get("ram_mb", 4096)))
    )
    player_name_state = state.player_name_state
    player_name_state["value"] = profile_options["player_name"]
    launch_selection = state.launch_selection
    launch_selection["key"] = profile_options["last_selected_button"]
    profile_picture_state = state.profile_picture_state
    profile_picture_state["path"] = profile_options["profile_picture_path"]
    version_catalog, local_latest_release = get_local_version_catalog()
    latest_release_id = load_latest_release_id() or local_latest_release
    online_available = False
    handled_external_profile_ids = load_handled_external_profile_ids()
    theme_choice = load_theme_choice(available_themes)
    theme = glass_palette(get_theme(theme_choice, settings["custom_accent"]))
    ui_theme.apply_legacy_theme(theme)
    selected_theme = state.selected_theme
    selected_theme["name"] = theme_choice
    active_page = state.active_page
    refresh_state = state.refresh_state
    connectivity_known = state.connectivity_known
    navigation_state = state.navigation_state
    intro_state = state.intro_state
    launcher_log_state = state.launcher_log_state
    page.title = "Wisc"
    page.window.width = 1100
    page.window.height = 650
    page.window.min_width = 1100
    page.window.min_height = 650
    page.window.resizable = True
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK

    page.window.prevent_close = False
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.fonts = {"Pixelify Sans": "fonts/PixelifySans.ttf"}
    clipboard_service = ft.Clipboard()
    page.services.append(clipboard_service)

    # imp functions----

    def minimize_window(e):
        page.window.minimized = True
        page.update()

    def maximize_window(e):
        page.window.maximized = not page.window.maximized
        page.update()

    async def close_window(e):
        features.stop()
        await page.window.close()

    features = LegacyFeatures(page, close=close_window)
    page.on_disconnect = features.stop

    progress_host = features.progress
    launch_activity = {'task': None}
    updater_ui = features.updater
    mods_content = features.mods
    discord_presence = features.presence

    async def refresh_latest_release():
        nonlocal latest_release_id, online_available
        latest, online = await asyncio.to_thread(get_latest_release_version)
        online_available = online
        if latest:
            latest_release_id = latest
            storage.save_installations(storage.load_installations(), latest_release_id=latest)
            sync_background()
        return online

    def get_latest_release_profile() -> dict:
        version_id = latest_release_id or ""
        return {
            "id": LATEST_RELEASE_PROFILE_ID,
            "key": LATEST_RELEASE_PROFILE_ID,
            "name": "Latest Release",
            "loader": "Vanilla",
            "minecraft_version": version_id,
            "loader_version": "",
            "version_id": version_id,
            **storage.load_latest_release_options(),
        }

    background = LauncherBackground(
        assets_dir=ASSETS_DIR, width=page.window.width, height=page.window.height,
    )

    def sync_background() -> None:
        key = launch_selection.get("key")
        target = (get_latest_release_profile() if key == LATEST_RELEASE_PROFILE_ID else
                  next((profile for profile in load_installations() if profile["id"] == key), None))
        background.set_target(target, minecraft_directory)

    features.on_profiles_changed = sync_background

    def get_account_avatar_bytes(account, scale=1):
        return skins.get_account_head_avatar_bytes(account, scale=scale)

    def add_log_lines(lines):
        append = state.launcher_log_state.get('append_logs')
        if append:
            append(lines)

    def add_log_line(line):
        add_log_lines([line])

    def refresh_launch_button():
        refresh = state.launcher_log_state.get('refresh_play_button')
        if refresh:
            refresh()

    def rebuild_profiles_view():
        if not features.closed:
            features.profiles_changed()

    def relogin_account(account):
        features.navigate('options_accounts')
        if features.open_ely_login:
            features.open_ely_login(account)


    def finish_launch_progress():
        if launch_activity["task"]:
            launch_activity["task"].finish()
            launch_activity["task"] = None
        progress_host.set_idle(state.launcher_log_state.get("status") or "Ready to play")

    def update_launch_progress(status=None, value=_PROGRESS_UNCHANGED, eta=None):
        if status is not None:
            state.launcher_log_state["status"] = redact_credentials(str(status))
        if value is not _PROGRESS_UNCHANGED:
            state.launcher_log_state["progress"] = value
        if eta is not None:
            state.launcher_log_state["eta"] = str(eta)
        if state.launcher_log_state.get("running") and not state.launcher_log_state.get("game_started"):
            if launch_activity["task"] is None:
                launch_activity["task"] = progress_host.begin(
                    state.launcher_log_state.get("status") or "Preparing Minecraft...",
                    priority=100, delay=0,
                )
            launch_activity["task"].update(
                state.launcher_log_state.get("status") or "Preparing Minecraft...",
                value=state.launcher_log_state.get("progress"), detail=state.launcher_log_state.get("eta", ""),
            )
        else:
            finish_launch_progress()

    async def ask_recommended_performance_mods() -> bool:
        """Ask once whether 1K FPS Mode may add the recommended mods."""
        from wisc.core import themes as colors
        from wisc.core.state import selected_theme
        from wisc.ui.components import build_themed_alert_dialog

        theme = glass_palette(
            colors.get_theme(selected_theme.get("name", colors.DEFAULT_THEME))
        )
        answer: asyncio.Future = asyncio.get_running_loop().create_future()

        def decide(accepted: bool):
            if not answer.done():
                answer.set_result(accepted)
            dialog.open = False
            page.update()

        dialog = build_themed_alert_dialog(
            "Add recommended performance mods?",
            ft.Text(
                "1K FPS Mode can also install Sodium, Lithium, FerriteCore, "
                "ImmediatelyFast, EntityCulling and ModernFix into this Fabric "
                "instance. Mods without a release for this Minecraft version "
                "are skipped. You can change this in Options > Launcher.",
                size=13,
            ),
            [
                ft.TextButton(
                    "Not now",
                    style=ft.ButtonStyle(color=theme["text_secondary"]),
                    on_click=lambda e: decide(False),
                ),
                ft.Button(
                    "Add mods",
                    bgcolor=theme["btn_primary"],
                    color=theme["btn_primary_text"],
                    on_click=lambda e: decide(True),
                ),
            ],
            theme=theme,
            modal=True,
        )
        page.show_dialog(dialog)
        page.update()
        return await answer

    async def launch_profile(target: dict):
        if updater_ui and updater_ui.applying:
            notify("Wait for the launcher update to finish before launching Minecraft.", "warning", "Updates")
            return
        if state.launcher_log_state.get("running"):
            return
        if mods_content.busy:
            notify("Wait for the mod operation to finish before launching Minecraft.", "warning", "Mods")
            return

        if (
            settings.get("performance_mode")
            and not settings.get("recommended_mods_prompted")
            and str(target.get("loader") or "").casefold() in {"fabric", "quilt"}
        ):
            accepted = await ask_recommended_performance_mods()
            persist_setting("performance_mods_enabled", accepted)
            persist_setting("recommended_mods_prompted", True)

        active_acc = storage.get_active_account()
        username = active_acc.get("username", "Player").strip() or "Player"
        online_available = False

        if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", username):
            update_launch_progress(
                "Invalid username: must be 1-16 letters, numbers, or _."
            )
            notify("Your username must contain 1–16 letters, numbers, or underscores.", "warning", "Invalid username")
            return

        discord_presence.set_player(
            username, skins.get_account_presence_avatar_bytes(active_acc),
        )

        if not target.get("loader"):
            target["loader"] = "Vanilla"
        if not target.get("minecraft_version"):
            target["minecraft_version"] = target.get("version_id", "1.21.1")

        installed_ids = {item["version_id"] for item in get_installed_versions()}
        is_downloading = target.get("version_id") not in installed_ids

        state.launcher_log_state["running"] = True
        state.launcher_log_state["game_started"] = False
        state.launcher_log_state["downloading"] = is_downloading
        state.launcher_log_state["cancelling"] = False
        state.launcher_log_state["cancel_event"] = threading.Event()
        state.launcher_log_state["target_version_id"] = target.get("version_id")
        state.launcher_log_state["target_profile_id"] = target.get("id")
        discord_presence.prepare_game(target, installing=is_downloading)

        refresh_launch_button()
        rebuild_profiles_view()

        update_launch_progress(
            f"Preparing {target.get('name', 'Minecraft')}...", value=None, eta=""
        )
        notify(f"Preparing {target.get('name', 'Minecraft')}…", "info", "Getting ready")

        is_modded = (target.get("loader") or "Vanilla").lower() != "vanilla"
        tracker = InstallationProgressTracker(is_modded=is_modded)

        def report_status(status):
            status_str = str(status)
            add_log_line(f"[*] {status_str}")
            tracker.on_status(status_str)
            lower = status_str.lower()
            if (
                "download" in lower
                or "librar" in lower
                or "asset" in lower
                or "install" in lower
                or "unpack" in lower
            ):
                if not state.launcher_log_state.get("downloading"):
                    state.launcher_log_state["downloading"] = True
                    if not state.launcher_log_state.get("game_started"):
                        discord_presence.prepare_game(target, installing=True)
                    refresh_launch_button()
            elif status_str in (
                "Building launch command...",
                "Starting Minecraft...",
                "Minecraft is running...",
            ):
                if state.launcher_log_state.get("downloading") and not state.launcher_log_state.get("cancelling"):
                    state.launcher_log_state["downloading"] = False
                    if not state.launcher_log_state.get("game_started"):
                        discord_presence.prepare_game(target)
                    refresh_launch_button()

            # During installation, only the UI loop publishes tracker snapshots.
            # Per-file statuses must not reset measured progress to indeterminate.
            if not state.launcher_log_state.get("downloading") and not state.launcher_log_state.get("cancelling"):
                update_launch_progress(status_str, value=None, eta="")

        def set_progress_maximum(maximum):
            tracker.on_max(maximum)

        def report_progress(current):
            tracker.on_progress(current)

        callback = {
            "setStatus": report_status,
            "setMax": set_progress_maximum,
            "setProgress": report_progress,
        }

        async def progress_ui_loop():
            while state.launcher_log_state.get(
                "running"
            ) and not state.launcher_log_state.get("game_started"):
                if state.launcher_log_state.get("downloading") and not state.launcher_log_state.get("cancelling"):
                    ratio, status_text, eta_text = tracker.get_display_state()
                    update_launch_progress(status_text, ratio, eta_text)
                await asyncio.sleep(0.05)

        progress_task = None
        output_task = None
        log_file = None
        settings = storage.load_settings()
        launch_action = settings.get("launch_action", "Keep launcher open")

        try:
            online_available = await refresh_latest_release()
            if online_available:
                account = await asyncio.to_thread(storage.get_active_account, include_credentials=True)
                if account.get("type") == "ely" and not account.get("access_token"):
                    update_launch_progress("Sign in to continue.", value=0.0, eta="")
                    notify("Sign in again to launch Minecraft with your Ely.by account.", "warning", "Sign-in required")
                    relogin_account(account)
                    return
            if target.get("id") == LATEST_RELEASE_PROFILE_ID:
                update_launch_progress("Checking latest release...", value=None, eta="")
                target = get_latest_release_profile()
                if state.launcher_log_state["cancel_event"].is_set():
                    raise DownloadCancelled("Version download cancelled.")
                if not target["version_id"]:
                    raise RuntimeError("Connect to the internet to find the latest release.")
                state.launcher_log_state["target_version_id"] = target["version_id"]
                state.launcher_log_state["downloading"] = (
                    target["version_id"] not in installed_ids
                )
                discord_presence.prepare_game(
                    target, installing=state.launcher_log_state["downloading"],
                )
                refresh_launch_button()
            progress_task = asyncio.create_task(progress_ui_loop())
            process, log_file = await start_game(
                target,
                username,
                online_available,
                callback,
                settings,
                state.launcher_log_state["cancel_event"],
            )
            tracker.finish()
            state.launcher_log_state["game_started"] = True
            state.launcher_log_state["downloading"] = False
            game_account = getattr(process, "wisc_presence_player", active_acc)
            game_face = getattr(process, "wisc_presence_face", None)
            if game_account.get("type") == "offline":
                game_face = None
            elif game_face is None:
                game_face = skins.get_account_presence_avatar_bytes(game_account)
            discord_presence.game_started(
                target,
                player_name=str(game_account.get("username") or username),
                face_png=game_face,
            )
            update_launch_progress("Minecraft is running...", value=1.0, eta="")
            notify(f"{target.get('name', 'Minecraft')} is running.", "success", "Minecraft started")
            refresh_launch_button()

            loop = asyncio.get_running_loop()
            output_task = asyncio.create_task(
                asyncio.to_thread(
                    read_game_output, process, log_file,
                    lambda lines: loop.call_soon_threadsafe(add_log_lines, lines),
                    sensitive_values=getattr(process, "wisc_sensitive_values", ()),
                )
            )

            if launch_action == "Hide launcher":
                page.window.visible = False
                page.update()
            elif launch_action == "Close launcher":
                page.run_task(close_window, None)

            exit_code = await asyncio.to_thread(process.wait)
            if output_task is not None:
                await output_task

            if launch_action == "Hide launcher":
                page.window.visible = True
                page.update()

            update_launch_progress(
                (
                    "Ready to play"
                    if exit_code == 0
                    else f"Minecraft exited with code {exit_code}."
                ),
                value=0.0,
                eta="",
            )
            if exit_code == 0:
                notify("Minecraft has closed. You're ready to play again.", "info", "Game closed")
            else:
                notify(f"Minecraft exited with code {exit_code}. Open the logs for details.", "error", "Minecraft stopped")
        except DownloadCancelled:
            update_launch_progress("Version download cancelled.", value=0.0, eta="")
            notify("The version download was cancelled.", "info", "Installation cancelled")
        except Exception as error:
            if launch_action == "Hide launcher":
                try:
                    page.window.visible = True
                    page.update()
                except Exception:
                    pass
            update_launch_progress(f"Launch failed: {error}", value=0.0, eta="")
            notify(str(error), "error", "Launch failed")
        finally:
            discord_presence.game_finished()
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            if log_file is not None:
                try:
                    log_file.close()
                except Exception:
                    pass

            state.launcher_log_state["running"] = False
            state.launcher_log_state["game_started"] = False
            state.launcher_log_state["downloading"] = False
            state.launcher_log_state["cancelling"] = False
            state.launcher_log_state["cancel_event"] = None
            state.launcher_log_state["target_version_id"] = None
            state.launcher_log_state["target_profile_id"] = None
            finish_launch_progress()
            refresh_launch_button()
            rebuild_profiles_view()

    async def repair_profile(target: dict):
        if updater_ui and updater_ui.applying:
            notify("Wait for the launcher update to finish before repairing Minecraft.", "warning", "Updates")
            return
        if state.launcher_log_state.get("running"):
            return
        if mods_content.busy:
            notify("Wait for the mod operation to finish before repairing Minecraft.", "warning", "Mods")
            return

        try:
            target = prepare_launch_profile(target, get_installed_versions(force_refresh=True))
        except (KeyError, ValueError) as error:
            update_launch_progress(f"Cannot repair this profile: {error}", value=0.0, eta="")
            notify(str(error), "error", "Cannot repair profile")
            return

        loader = str(target.get("loader") or "Vanilla").strip()
        mc_ver = str(
            target.get("minecraft_version") or target.get("version_id") or ""
        ).strip()
        loader_ver = str(target.get("loader_version") or "").strip()

        if not mc_ver:
            update_launch_progress(
                f"Cannot repair {target.get('name', 'Installation')}: missing Minecraft version.",
                value=0.0,
                eta="",
            )
            notify("This profile is missing its Minecraft version.", "error", "Cannot repair profile")
            return

        state.launcher_log_state["running"] = True
        state.launcher_log_state["downloading"] = True
        state.launcher_log_state["cancelling"] = False
        state.launcher_log_state["cancel_event"] = threading.Event()
        refresh_launch_button()
        rebuild_profiles_view()

        update_launch_progress(
            f"Repairing & verifying {target.get('name', 'Installation')}...",
            value=None,
            eta="",
        )
        notify(f"Repairing and verifying {target.get('name', 'Installation')}…", "info", "Repair started")

        is_modded = loader.lower() != "vanilla"
        tracker = InstallationProgressTracker(is_modded=is_modded)

        def report_status(status):
            status_str = str(status)
            add_log_line(f"[*] {status_str}")
            # Keep raw file statuses in the log; the UI loop renders progress.
            tracker.on_status(status_str)

        def set_progress_maximum(maximum):
            tracker.on_max(maximum)

        def report_progress(current):
            tracker.on_progress(current)

        def install_callback_handler(name):
            def handler(*args):
                cancel_event = state.launcher_log_state.get("cancel_event")
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Repair cancelled.")
                cb_map = {
                    "setStatus": report_status,
                    "setProgress": report_progress,
                    "setMax": set_progress_maximum,
                }
                cb_map.get(name, lambda *_: None)(*args)
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled("Repair cancelled.")

            return handler

        install_callback = {
            name: install_callback_handler(name)
            for name in ("setStatus", "setProgress", "setMax")
        }

        async def progress_ui_loop():
            while state.launcher_log_state.get(
                "running"
            ) and state.launcher_log_state.get("downloading"):
                if not state.launcher_log_state.get("cancelling"):
                    ratio, status_text, eta_text = tracker.get_display_state()
                    update_launch_progress(status_text, ratio, eta_text)
                await asyncio.sleep(0.05)

        progress_task = None
        try:
            progress_task = asyncio.create_task(progress_ui_loop())
            if loader.lower() == "vanilla":
                await asyncio.to_thread(
                    minecraft_launcher_lib.install.install_minecraft_version,
                    mc_ver,
                    minecraft_directory,
                    install_callback,
                )
            else:
                mod_loader = get_mod_loader(loader)
                repaired_version = await asyncio.to_thread(
                    mod_loader.install,
                    mc_ver,
                    minecraft_directory,
                    loader_version=loader_ver,
                    callback=install_callback,
                )
                if repaired_version != target["version_id"]:
                    raise RuntimeError("The installer returned a different version than the pinned profile.")
            invalidate_installed_versions_cache()
            tracker.finish()
            update_launch_progress(
                f"Successfully repaired {target.get('name')}.", value=0.0, eta=""
            )
            notify(f"Successfully repaired {target.get('name', 'the profile')}.", "success", "Repair complete")
        except DownloadCancelled:
            update_launch_progress("Repair cancelled.", value=0.0, eta="")
            notify("The profile repair was cancelled.", "info", "Repair cancelled")
        except Exception as error:
            update_launch_progress(f"Repair failed: {error}", value=0.0, eta="")
            notify(str(error), "error", "Repair failed")
        finally:
            if progress_task is not None:
                progress_task.cancel()
                try:
                    await progress_task
                except asyncio.CancelledError:
                    pass
            state.launcher_log_state["running"] = False
            state.launcher_log_state["downloading"] = False
            state.launcher_log_state["cancelling"] = False
            state.launcher_log_state["cancel_event"] = None
            finish_launch_progress()
            refresh_launch_button()
            rebuild_profiles_view()

    features.on_repair = repair_profile


    def notify(message, icon=ft.Icons.INFO_OUTLINE, title=None, **kwargs):
        if icon in ("info", "success", "warning", "error", "update"):
            kind = icon
        elif icon in (ft.Icons.ERROR_OUTLINE, ft.Icons.ERROR):
            kind = "error"
        elif icon in (ft.Icons.CHECK_CIRCLE, ft.Icons.CHECK_CIRCLE_OUTLINE):
            kind = "success"
        else:
            kind = "info"
        features.notify(message, kind, title, **kwargs)

    def persist_setting(key, value):
        current = load_settings()
        current[key] = value
        if not save_settings(current):
            notify("Could not save settings.", "error")
            return
        settings.update(current)
        if key == "discord_rpc":
            features.presence.set_enabled(bool(value) and not page.web)

    def change_theme(e):
        new_choice = e.control.value
        if new_choice not in available_themes:
            return

        if features.busy:
            e.control.value = selected_theme["name"]
            e.control.update()
            notify("Wait for the current operation before changing themes.", "warning")
            return
        if not save_theme_choice(new_choice):
            notify("Could not save the selected theme.", "error")
            return
        selected_theme["name"] = new_choice
        page.controls.clear()
        build_page(new_choice, active_page.get("name", "options"))

    def get_themes_options() -> list[ft.DropdownOption]:
        return [
            ft.DropdownOption(
                key=theme,
                text=theme,
            )
            for theme in available_themes
        ]

    def apply_custom_theme(accent: str) -> bool:
        accent = normalize_accent(accent)
        if accent is None:
            return False
        if features.busy:
            notify("Wait for the current operation before changing themes.", "warning")
            return False
        current = load_settings()
        updated = {**current, "custom_accent": accent}
        if not save_settings(updated):
            notify("Could not save your custom color.", "error")
            return False
        if not save_theme_choice(CUSTOM_THEME):
            save_settings(current)
            notify("Could not save the selected theme.", "error")
            return False
        settings.update(updated)
        selected_theme["name"] = CUSTOM_THEME
        page.controls.clear()
        build_page(CUSTOM_THEME, active_page.get("name", "options_ui"))
        notify("Custom color applied.", "success")
        return True


    from wisc.ui.components import (
        NavigationTabs,
        build_themed_alert_dialog,
        tooltip,
        window_button_style,
    )

    def build_page(theme_select, tab="home"):
        theme = glass_palette(get_theme(theme_select, settings["custom_accent"]))
        background.reset_surfaces()
        if features.library:
            features.library.leave()
            features.library = None
        features.apply_theme(theme)
        page.theme = ft.Theme(
            font_family="Segoe UI", color_scheme_seed=theme["btn_primary"],
            color_scheme=ft.ColorScheme(primary=theme["btn_primary"], on_primary=theme["btn_primary_text"],
                                       surface=theme["surface"], on_surface=theme["text_primary"], outline=theme["border"]),
        )
        page.bgcolor = GLASS_COLOR
        dialog_blur_overlay = ft.Container(
            left=0,
            top=0,
            right=0,
            bottom=0,
            expand=True,
            blur=ft.Blur(4, 4),
            bgcolor=ft.Colors.with_opacity(0.35, "#000000"),
            visible=False,
            animate_opacity=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
        )
        page.overlay.clear()
        page.overlay.append(dialog_blur_overlay)

        def show_dialog_with_blur(dlg: ft.AlertDialog):
            dialog_blur_overlay.visible = True
            page.show_dialog(dlg)
            page.update()

        def hide_dialog_blur(e=None):
            if dialog_blur_overlay.visible:
                dialog_blur_overlay.visible = False
                page.update()

        def close_dialog_with_blur(dlg: ft.AlertDialog):
            dlg.open = False
            hide_dialog_blur()

        launcher_log_state["tooltip_func"] = tooltip

        def copy_to_clipboard(text: str, message: str = "Copied to clipboard!"):
            try:
                page.run_task(clipboard_service.set, text)
            except Exception:
                pass
            if os.name == "nt":
                try:
                    p = subprocess.Popen(
                        ["clip"],
                        stdin=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    p.communicate(input=text.encode("utf-16le"))
                except Exception:
                    pass
            notify(message, ft.Icons.CHECK_CIRCLE_OUTLINE)

        def open_url(url: str, message: str = ""):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(url)
                else:
                    webbrowser.open(url)
            except Exception:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            if message:
                notify(message, ft.Icons.OPEN_IN_NEW)

        func_buttons = [
            ft.IconButton(
                icon=ft.Icons.HORIZONTAL_RULE,
                on_click=minimize_window,
                icon_color=GLASS_TEXT,
                hover_color=ft.Colors.with_opacity(
                    0.14, theme["btn_primary"]
                ),
                icon_size=17,
                style=window_button_style,
            ),
            ft.IconButton(
                icon=ft.Icons.CROP_SQUARE,
                on_click=maximize_window,
                icon_color=GLASS_TEXT,
                hover_color=ft.Colors.with_opacity(
                    0.14, theme["btn_primary"]
                ),
                icon_size=17,
                style=window_button_style,
            ),
            ft.IconButton(
                icon=ft.Icons.CLOSE,
                on_click=close_window,
                icon_color=theme["btn_primary"],
                hover_color=ft.Colors.with_opacity(
                    0.14, theme["btn_primary"]
                ),
                icon_size=21,
                style=window_button_style,
            ),
        ]

        # ---- animation overhaul: startup ripple & navigation transitions ----
        def prepare_intro(control):
            """Hide a control so the startup ripple can reveal it with a pop."""
            if not intro_state["pending"]:
                return control
            control.opacity = 0
            control.scale = 0.92
            control.offset = ft.Offset(0, 0.06)
            control.animate_opacity = ft.Animation(340, ft.AnimationCurve.EASE_OUT_CUBIC)
            control.animate_scale = ft.Animation(460, ft.AnimationCurve.EASE_OUT_BACK)
            control.animate_offset = ft.Animation(460, ft.AnimationCurve.EASE_OUT_BACK)
            intro_state["targets"].append(control)
            return control

        def reveal_intro(control):
            control.opacity = 1
            control.scale = 1.0
            control.offset = ft.Offset(0, 0)

        async def play_intro_ripple():
            """Reveal every registered control one by one for a ripple entrance."""
            if not intro_state["pending"]:
                return
            intro_state["pending"] = False
            intro_state["running"] = True
            raw_targets = list(intro_state["targets"])
            intro_state["targets"].clear()
            # Reorder navbar targets to the front so the ripple cascades from top to bottom
            navbar_set = set()
            try:
                navbar_set.update([title_wrap, tabs_pop_wrap, func_buttons_wrap])
            except Exception:
                pass
            targets = [t for t in raw_targets if t in navbar_set] + [
                t for t in raw_targets if t not in navbar_set
            ]
            try:
                await asyncio.sleep(0.12)
                for control in targets:
                    reveal_intro(control)
                    try:
                        control.update()
                    except Exception:
                        pass
                    await asyncio.sleep(0.045)
            finally:
                # Safety net: nothing may stay hidden, even if a control got detached.
                for control in targets:
                    reveal_intro(control)
                try:
                    page.update()
                except Exception:
                    pass
                intro_state["running"] = False

        # ---- content area: this is what swaps when you navigate ----
        page_content = ft.Container(
            expand=True,
            opacity=1.0,
            animate_opacity=ft.Animation(160, ft.AnimationCurve.EASE_IN),
        )

        page_backdrop = background.panel(
            ft.Container(), radius=0, opacity=HOME_BACKDROP_OPACITY, frosted=False,
        )
        content_area = ft.Container(
            content=ft.Stack([page_content], fit=ft.StackFit.EXPAND,
                             clip_behavior=ft.ClipBehavior.NONE),
            expand=True,
            margin=ft.Margin.only(left=10, top=0, right=10, bottom=10),
        )
        features.mount(page_content, content_area)

        transition_id = 0
        current_page = None

        async def transition_page(name, content, request_id):
            nonlocal tab
            page_content.animate_opacity = ft.Animation(90, ft.AnimationCurve.EASE_OUT)
            page_content.opacity = 0
            page.update()
            await asyncio.sleep(0.08)

            if request_id != transition_id:
                return

            page_content.content = content
            if name == "onboarding":
                tab = "home"
            elif name in tab_names:
                tab = name
            elif name.startswith("options") or name == "account_login":
                tab = "options"
            else:
                tab = "installations"
            new_tab_index = tab_names.index(tab)
            tabs_buttons.selected_index = new_tab_index
            page_content.animate_opacity = ft.Animation(160, ft.AnimationCurve.EASE_IN)
            page_content.opacity = 1
            page.update()
            if name == "mods":
                features.reveal.show(content, features.mods.reveal_controls)
                features.mods.start_loading()
            elif isinstance(content.data, dict) and "reveal_controls" in content.data:
                features.reveal.show(content, content.data["reveal_controls"])

        def show_page(name, content):
            nonlocal current_page, transition_id, tab
            if page_content.content is None:
                page_content.content = content
                current_page = name
                tab = "home" if name == "onboarding" else name if name in tab_names else "options" if name.startswith("options") or name == "account_login" else "installations"
                tabs_buttons.selected_index = tab_names.index(tab)
                page.update()
                if name == "mods":
                    features.mods.start_loading()
                elif isinstance(content.data, dict) and "reveal_controls" in content.data:
                    features.reveal.show(content, content.data["reveal_controls"])
                return
            transition_id += 1
            current_page = name
            page.run_task(transition_page, name, content, transition_id)

        loader_catalog_cache = {}

        def is_active_launch_version(version_id, profile_id=None):
            if not launcher_log_state["running"]:
                return False
            return (
                version_id == launcher_log_state["target_version_id"]
                or profile_id == launcher_log_state["target_profile_id"]
            )

        def set_orbs_enabled(enabled: bool) -> None:
            persist_setting("enable_orbs", enabled)
            navigate(active_page["name"], active_page.get("profile_id"), force=True)

        from wisc.ui.installations import build_installation_editor as _build_installation_editor

        def build_installation_editor(profile=None, name_only=False):
            return _build_installation_editor(
                profile=profile,
                name_only=name_only,
                page=page,
                theme=theme,
                settings=settings,
                installations=installations,
                handled_external_profile_ids=handled_external_profile_ids,
                latest_release_id=latest_release_id,
                version_catalog=version_catalog,
                loader_catalog_cache=loader_catalog_cache,
                navigate=navigate,
                notify=notify,
                online_available=online_available,
                show_dialog_with_blur=show_dialog_with_blur,
                close_dialog_with_blur=close_dialog_with_blur,
                features=features,
            )
        def update_account() -> None:
            account = get_active_account()
            player_name_state["value"] = account.get("username", "Player").strip() or "Player"
            features.player_changed(get_account_avatar_bytes(account, scale=4))
            refresh = launcher_log_state.get("refresh_account_picture")
            if refresh:
                refresh()
            refresh_launch_button()

        def build_options_page(name: str) -> ft.Control:
            preview = ft.Image(
                src=get_account_avatar_bytes(get_active_account(), scale=6),
                width=48, height=48, fit=ft.BoxFit.CONTAIN, border_radius=8,
                gapless_playback=True,
            )
            account_picture_preview = ft.Container(
                width=48, height=48, border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.14, theme["btn_primary"]),
                alignment=ft.Alignment.CENTER, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=preview,
            )

            def refresh_preview() -> None:
                preview.src = get_account_avatar_bytes(get_active_account(), scale=6)
                try:
                    preview.update()
                except RuntimeError:
                    pass

            theme_dropdown = LegacySelector(
                label="Choose a Theme", value=theme_select,
                label_style=ft.TextStyle(size=13, color=theme["text_secondary"]),
                on_select=change_theme, options=get_themes_options(),
                border=ft.OutlinedBorder(side=ft.BorderSide(color=theme["border"])),
            )
            return build_options_views(
                page=page, theme=theme, settings=settings,
                persist_setting=persist_setting, navigate=navigate, notify=notify,
                copy_to_clipboard=copy_to_clipboard, open_url=open_url,
                theme_dropdown=theme_dropdown, available_themes=available_themes,
                maximum_memory_mb=maximum_memory_mb, features=features,
                minecraft_directory=minecraft_directory,
                account_picture_preview=account_picture_preview,
                refresh_account_picture=refresh_preview, update_sidebar_username=update_account,
                refresh_launch_button=refresh_launch_button,
                rebuild_page_callback=lambda theme_name, cur_page: (
                    page.controls.clear(), build_page(theme_name, cur_page)),
                set_orbs_enabled=set_orbs_enabled,
                show_dialog_with_blur=show_dialog_with_blur,
                close_dialog_with_blur=close_dialog_with_blur,
                apply_custom_theme=apply_custom_theme,
            )[name]

        def finish_onboarding(theme_name: str, destination: str) -> bool:
            if features.busy and (theme_name != theme_select or destination == "new_installation"):
                notify("Wait for the current operation to finish.", "warning")
                return False
            if not save_theme_choice(theme_name):
                notify("Could not save your palette. Please try again.", "error")
                return False
            current_settings = load_settings()
            current_settings["onboarding_completed"] = True
            if not save_settings(current_settings):
                save_theme_choice(theme_select)
                notify("Could not save setup. Please try again.", "error")
                return False
            settings.update(current_settings)
            selected_theme["name"] = theme_name
            page.controls.clear()
            build_page(theme_name, destination)
            return True

        def navigate(name, profile_id=None, force=False):
            nonlocal handled_external_profile_ids
            if name == "profiles":
                name = "options_accounts"
            if current_page == name and active_page.get("profile_id") == profile_id and not force:
                return
            if features.busy and name in ("new_installation", "edit_installation", "configure_installed"):
                notify("Wait for the current operation to finish.", "warning")
                return
            installations[:] = load_installations()
            settings.update(load_settings())
            editor_profile = None
            if name == "edit_installation":
                editor_profile = next((item for item in installations if item["id"] == profile_id), None)
                if editor_profile is None:
                    notify("This profile is no longer available.", "warning")
                    return
                if is_active_launch_version(get_profile_version_id(editor_profile), profile_id):
                    notify("This profile is busy launching.", ft.Icons.INFO_OUTLINE)
                    return
            elif name == "configure_installed":
                if is_active_launch_version(profile_id):
                    notify("This version is busy installing or launching.", ft.Icons.INFO_OUTLINE)
                    return
                version = next((item for item in get_installed_versions(force_refresh=True)
                                if item["version_id"] == profile_id), None)
                if version is None:
                    notify("This installed version is no longer available.", "warning")
                    return
                editor_profile = next((item for item in installations
                                       if get_profile_version_id(item) == profile_id), None) or {
                    "id": uuid.uuid4().hex, "name": version["version_id"],
                    "loader": version["loader"], "channel": "",
                    "minecraft_version": version["minecraft_version"],
                    "loader_version": version["loader_version"], "version_id": version["version_id"],
                }

            active_page.update(name=name, profile_id=profile_id)
            features.enter(name, profile_id, defer_load=name == "mods")
            if name == "onboarding":
                sync_background()
                content = OnboardingView(
                    page=page, theme_name=theme_select, assets_dir=ASSETS_DIR,
                    artwork_source=background.artwork.source, on_complete=finish_onboarding,
                    custom_accent=settings["custom_accent"],
                )
            elif name == "mods":
                content = features.mods
            elif name.startswith("options"):
                content = build_options_page(name)
            elif name == "skins":
                content = build_skins_view_external(
                    page, theme, notify, open_url=open_url,
                    online_available=lambda: online_available, navigate=navigate, features=features,
                )
            elif name in ("new_installation", "edit_installation", "configure_installed"):
                content = build_installation_editor(editor_profile, name_only=editor_profile is not None)
            elif name == "account_login":
                from wisc.ui.accounts import build_account_login
                account = next((item for item in storage.load_accounts()["accounts"]
                                if item["id"] == profile_id), None) if profile_id else None
                content = build_account_login(
                    page=page, theme=theme, navigate=navigate, notify=notify, open_url=open_url,
                    on_account_changed=update_account, account=account, features=features,
                )
            elif name in ("home", "installations"):
                installed_versions = get_installed_versions(force_refresh=True)
                installations[:], handled_external_profile_ids, imported = import_external_installations(
                    installations, handled_external_profile_ids, installed_versions,
                    get_external_installations(), version_catalog,
                )
                installations[:], discovered = discover_local_instances(
                    minecraft_directory, installations, installed_versions, version_catalog,
                )
                if (imported or discovered) and not save_installations(
                    installations, handled_external_profile_ids, latest_release_id,
                ):
                    installations[:] = load_installations()
                    handled_external_profile_ids = load_handled_external_profile_ids()
                    notify("Could not save imported Minecraft installations.", "error")
                if name == "home":
                    content = build_home_view(
                        page=page, theme=theme, installations=installations,
                        installed_versions=installed_versions,
                        latest_release_profile=get_latest_release_profile() if latest_release_id else None,
                        minecraft_directory=minecraft_directory, assets_dir=ASSETS_DIR, features=features,
                        navigate=navigate, notify=notify, launch_profile=launch_profile,
                        update_launch_progress=update_launch_progress, copy_to_clipboard=copy_to_clipboard,
                        open_game_folder=lambda folder: features.open_folder(Path(folder or minecraft_directory)),
                        prepare_intro=prepare_intro,
                        online_available=lambda: online_available,
                        on_target_selected=lambda target: background.set_target(target, minecraft_directory),
                    )
                else:
                    content = build_library_view(
                        page=page, app_theme=theme, features=features,
                        installations=installations, installed_versions=installed_versions,
                        handled_external_profile_ids=handled_external_profile_ids,
                        latest_release_id=latest_release_id, navigate=navigate, notify=notify,
                        is_active_launch_version=is_active_launch_version,
                        build_alert_dialog=partial(build_themed_alert_dialog, theme=theme,
                                                   dialog_blur_overlay=dialog_blur_overlay),
                        show_dialog_with_blur=show_dialog_with_blur,
                        close_dialog_with_blur=close_dialog_with_blur,
                    )
            else:
                return
            sync_background()
            page_backdrop.set_frosted(name not in ("home", "onboarding"))
            show_page(name, content)

        navigation_state["navigate"] = navigate

        tab_names = ["home", "installations", "mods", "skins", "options"]

        def on_tab_select(selected_tab):
            if selected_tab != current_page:
                navigate(selected_tab)

        title_letters = []
        title_controls = []
        for character in "Wisc":
            if character == " ":
                title_controls.append(ft.Container(width=6))
                continue

            letter = ft.Container(
                content=ft.Text(
                    character,
                    font_family="Pixelify Sans",
                    size=26,
                    weight=ft.FontWeight.BOLD,
                    color=GLASS_TEXT,
                ),
                offset=ft.Offset(0, 0),
                animate_offset=ft.Animation(110, ft.AnimationCurve.EASE_OUT),
            )
            title_letters.append(letter)
            title_controls.append(letter)

        is_bouncing = False

        async def bounce_title():
            nonlocal is_bouncing
            if is_bouncing:
                return

            is_bouncing = True
            try:

                async def bounce_letter(letter, delay):
                    await asyncio.sleep(delay)
                    letter.offset = ft.Offset(0, -0.25)
                    page.update()
                    await asyncio.sleep(0.08)

                    letter.offset = ft.Offset(0, 0)
                    page.update()

                await asyncio.gather(
                    *(
                        bounce_letter(letter, index * 0.03)
                        for index, letter in enumerate(title_letters)
                    )
                )
                await asyncio.sleep(0.11)
            finally:
                is_bouncing = False

        def start_title_animation(e):
            page.run_task(bounce_title)

        root_tab = (
            tab
            if tab in tab_names
            else ("options" if tab.startswith("options") or tab == "account_login" else "installations")
        )
        tabs_buttons = NavigationTabs(
            tab_names=tab_names,
            initial_index=tab_names.index(root_tab),
            on_tab_select=on_tab_select,
            app_theme={**theme, "text_primary": GLASS_TEXT, "text_secondary": GLASS_MUTED},
            tooltip_func=tooltip,
        )

        title_wrap = prepare_intro(
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Image(src="icons/wisc_mark.png",
                                 width=31, height=22, fit=ft.BoxFit.CONTAIN),
                        ft.Container(width=10),
                        *title_controls,
                    ],
                    spacing=0, tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.Padding.only(left=15),
                on_click=start_title_animation,
            )
        )
        tabs_pop_wrap = prepare_intro(
            ft.Container(
                content=tabs_buttons,
                alignment=ft.Alignment.CENTER,
            )
        )
        func_buttons_wrap = prepare_intro(
            ft.Container(
                padding=ft.Padding.only(left=8),
                content=ft.Row(controls=func_buttons, spacing=0, tight=True),
            )
        )

        NAV_SIDE_WIDTH = 200

        navbar_content = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=title_wrap,
                        width=NAV_SIDE_WIDTH,
                        alignment=ft.Alignment.CENTER_LEFT,
                    ),
                    tabs_pop_wrap,
                    ft.Container(
                        content=func_buttons_wrap,
                        width=NAV_SIDE_WIDTH,
                        alignment=ft.Alignment.CENTER_RIGHT,
                    ),
                ],
                spacing=0,
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.TRANSPARENT,
            padding=ft.Padding.symmetric(horizontal=20, vertical=4),
            height=TITLE_BAR_HEIGHT,
        )

        navbar = ft.WindowDragArea(content=background.panel(
            navbar_content, left=0, top=0, height=TITLE_BAR_HEIGHT, radius=0,
            key=ft.ValueKey("launcher-title-bar"),
        ))

        navigate(tab)  # default page shown on load

        features.update_badge = ft.Container(
            width=8, height=8, border_radius=4, bgcolor=theme["btn_primary"],
            right=8, top=6, visible=False,
        )
        tabs_buttons.content.controls.append(features.update_badge)
        features.refresh_update_badge()
        def resize_shell(event: ft.LayoutSizeChangeEvent) -> None:
            background.resize(event.width, event.height)
            features.toasts.resize(event)

        page.add(ft.Stack(expand=True, on_size_change=resize_shell, controls=[
            background,
            # GlassSurface's left/top offsets crop its artwork. Anchor a
            # separate container so the backdrop receives full-window bounds.
            ft.Container(
                content=page_backdrop, left=0, top=0, right=0, bottom=0,
                ignore_interactions=True,
            ),
            ft.Column([
                navbar,
                content_area,
                ft.Container(padding=ft.Padding.symmetric(horizontal=8), content=features.progress),
            ], expand=True, spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            features.toasts,
            *build_window_resize_handles(page),
        ]))
        features.start()
        features.player_changed()
        # Kick off the ripple entrance now that the first frame is committed.
        page.run_task(play_intro_ripple)

    def refresh_skin_connectivity(is_online: bool) -> None:
        if active_page.get("name") != "skins":
            return
        tooltip_fn = launcher_log_state.get("tooltip_func")
        for key in ("skin_refresh_button", "skin_manage_button"):
            button = launcher_log_state.get(key)
            if button is None:
                continue
            button.disabled = not is_online
            message = "Internet connection required"
            button.tooltip = None if is_online else tooltip_fn(message) if tooltip_fn else message
            try:
                button.update()
            except RuntimeError:
                pass
        skin_sync = launcher_log_state.get("skin_sync_task")
        if skin_sync is not None:
            page.run_task(skin_sync, False)

    async def refresh_version_catalog():
        nonlocal latest_release_id, online_available
        if features.closed or refresh_state["running"]:
            return

        was_online = online_available
        was_known = connectivity_known["value"]
        old_latest_release_id = latest_release_id
        refresh_state["running"] = True
        try:
            versions, latest, is_online = await asyncio.to_thread(get_version_catalog)
        except Exception:
            versions, latest = get_local_version_catalog()
            is_online = False

        refresh_state["running"] = False
        if features.closed:
            return
        if is_online:
            version_catalog[:] = versions
            latest_release_id = latest
            save_installations(
                installations, handled_external_profile_ids, latest
            )
            online_available = True
            connectivity_known["value"] = True
            refresh_skin_connectivity(True)
            if was_known and not was_online:
                notify("Internet connection restored.", ft.Icons.WIFI)
            if active_page.get("name") == "home" and (
                not old_latest_release_id
                or old_latest_release_id != latest
            ):
                while not features.closed and (intro_state.get("pending") or intro_state.get("running")):
                    await asyncio.sleep(0.05)
                if not features.closed and navigation_state.get("navigate") and active_page.get("name") == "home":
                    navigation_state["navigate"]("home", force=True)
            return

        online_available = False
        connectivity_known["value"] = True
        refresh_skin_connectivity(False)
        if was_online or not was_known:
            notify(
                "No internet connection. Installed versions remain available.",
                ft.Icons.WIFI_OFF,
            )

    async def monitor_connectivity():
        nonlocal online_available
        while not features.closed:
            connected = await asyncio.to_thread(check_internet_connection)
            if features.closed:
                return
            if connected and not online_available:
                await refresh_version_catalog()
            elif not connected and online_available:
                online_available = False
                connectivity_known["value"] = True
                refresh_skin_connectivity(False)
                notify(
                    "No internet connection. Installed versions remain available.",
                    ft.Icons.WIFI_OFF,
                )
            await asyncio.sleep(30)

    async def watch_external_profiles():
        if features.closed:
            return
        stamp = await asyncio.to_thread(installation_sources_stamp, minecraft_directory)
        while not features.closed:
            await asyncio.sleep(2.5)
            if features.closed:
                return
            if features.busy:
                continue
            try:
                current = await asyncio.to_thread(installation_sources_stamp, minecraft_directory)
                if current == stamp:
                    continue
                changed = await asyncio.to_thread(sync_local_installations)
                stamp = current
                if changed:
                    installations[:] = load_installations()
                    features.profiles_changed()
                    notify('Synced Minecraft profiles and instances.', 'success')
            except Exception as error:
                notify(error, 'error', 'Could not sync profiles')

    build_page(theme_choice, "home" if settings.get("onboarding_completed") else "onboarding")
    page.run_task(refresh_version_catalog)
    page.run_task(monitor_connectivity)
    page.run_task(watch_external_profiles)
    page.run_task(asyncio.to_thread, skins.prune_skin_cache)

def run() -> None:
    """Start the Flet desktop client with the bundled assets."""
    ft.run(main, assets_dir=str(ASSETS_DIR))
