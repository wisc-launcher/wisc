"""Classic Home launch panel, profile shelf, and game log view."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
from typing import TYPE_CHECKING, Callable

import flet as ft

from wisc.services import banners
from wisc.core import state
from wisc.services.launcher import get_profile_version_id
from wisc.core.storage import get_active_account, save_profile_options
from wisc.services.skins import get_account_head_avatar_bytes as get_active_player_head_avatar_bytes
from wisc.core.credentials import redact_credentials
from wisc.ui.components import clickable_mouse_cursor, tooltip
from wisc.ui.controls import launcher_button, launcher_icon_button
from wisc.ui.glass import glass_panel
from wisc.ui.profile_assets import profile_icon

if TYPE_CHECKING:
    from wisc.ui.features import LegacyFeatures


class _HomeView(ft.Container):
    """Start artwork after mounting and cancel its worker when detached."""

    def __init__(self, *, on_mount: Callable, on_unmount: Callable, **kwargs):
        super().__init__(**kwargs)
        self._on_mount = on_mount
        self._on_unmount = on_unmount

    def did_mount(self) -> None:
        self._on_mount()

    def will_unmount(self) -> None:
        self._on_unmount()


def build_home_view(*, page: ft.Page, theme: dict, installations: list[dict],
                    installed_versions: list[dict], latest_release_profile: dict | None,
                    minecraft_directory: str, assets_dir: Path, features: LegacyFeatures,
                    navigate: Callable, notify: Callable, launch_profile: Callable,
                    update_launch_progress: Callable, copy_to_clipboard: Callable,
                    open_game_folder: Callable, prepare_intro: Callable,
                    online_available: Callable[[], bool] = lambda: True,
                    on_target_selected: Callable[[dict], None] = lambda target: None) -> ft.Container:
    launcher_log_state = state.launcher_log_state
    player_name_state = state.player_name_state
    profile_picture_state = state.profile_picture_state
    launch_selection = state.launch_selection
    active_page = state.active_page
    navigation_state = state.navigation_state
    progress_host = features.progress
    local_version_ids = {version["version_id"] for version in installed_versions}
    ASSETS_DIR = assets_dir
    launch_targets = {}
    if latest_release_profile:
        launch_targets[latest_release_profile["id"]] = latest_release_profile
    for installation in installations:
        version_id = get_profile_version_id(installation)
        if not version_id:
            continue
        launch_targets[installation["id"]] = {
            **installation,
            "key": installation["id"],
            "version_id": version_id,
        }

    if launch_selection["key"] not in launch_targets:
        installed_ids = {
            version["version_id"] for version in installed_versions
        }
        launch_selection["key"] = next(
            (
                key
                for key, target in launch_targets.items()
                if target["version_id"] in installed_ids
            ),
            next(iter(launch_targets), ""),
        )
        save_profile_options(
            player_name_state["value"],
            launch_selection["key"],
            profile_picture_state["path"],
        )

    active_acc = get_active_account()
    initial_uname = active_acc.get("username", player_name_state["value"]).strip() or "Player"
    player_name_state["value"] = initial_uname

    lifecycle = {"mounted": False, "closed": False}
    account_username_text = ft.Text(
        initial_uname, size=12, weight=ft.FontWeight.W_600,
        color=theme["text_primary"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
    )
    account_avatar = ft.Image(
        src=get_active_player_head_avatar_bytes(active_acc, scale=3),
        width=24, height=24, fit=ft.BoxFit.CONTAIN, border_radius=5,
        gapless_playback=True, filter_quality=ft.FilterQuality.NONE,
    )

    def refresh_account_picture() -> None:
        account = get_active_account()
        account_avatar.src = get_active_player_head_avatar_bytes(account, scale=3)
        account_username_text.value = account.get("username", "Player")
        try:
            account_card.update()
        except RuntimeError:
            pass

    launcher_log_state["refresh_account_picture"] = refresh_account_picture
    account_card = launcher_button("Account", lambda e: navigate("options_accounts"),
                                   height=36, tooltip=tooltip("Go to account settings"))
    account_card.style.padding = 0
    account_card.content = glass_panel(
        height=36, border_radius=8, bgcolor=ft.Colors.TRANSPARENT,
        padding=ft.Padding.symmetric(horizontal=14),
        content=ft.Row(
            [account_avatar, account_username_text,
             ft.Icon(ft.Icons.EXPAND_MORE, size=16, color=theme["text_secondary"])],
            spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )
    account_row = ft.Row(
        [account_card], height=36, alignment=ft.MainAxisAlignment.END,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    selected_target = launch_targets.get(launch_selection["key"])

    def version_summary(target: dict | None) -> str:
        if not target:
            return "Create a profile to get started."
        loader = str(target.get("loader") or "Vanilla")
        loader = {"vanilla": "Vanilla", "fabric": "Fabric", "forge": "Forge",
                  "quilt": "Quilt", "neoforge": "NeoForge"}.get(loader.casefold(), loader)
        version = target.get("minecraft_version") or target.get("version_id") or "Unknown version"
        return f"{version} · {loader}"

    selected_version_name = ft.Text(
        selected_target["name"] if selected_target else "Your next adventure",
        size=42, weight=ft.FontWeight.BOLD, color=theme["text_primary"],
        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
        tooltip=tooltip(selected_target["name"] if selected_target else "Create a profile"),
    )
    selected_version_summary = ft.Text(
        version_summary(selected_target), size=13, color=theme["text_secondary"],
        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
    )

    def is_target_installed(target: dict | None) -> bool:
        return bool(target and target.get("version_id") in local_version_ids)

    hero_status_icon = ft.Icon(ft.Icons.CIRCLE, size=7, color=theme["btn_primary"])
    hero_status_text = ft.Text(size=12, color=theme["text_secondary"], expand=True,
                               max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    hero_status_row = ft.Row([hero_status_icon, hero_status_text], spacing=7,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
    footer_status = ft.Text(size=11, color=theme["text_secondary"],
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)

    def update_hero_status(target: dict | None) -> None:
        if launcher_log_state.get("cancelling"):
            message = "Cancelling after the current file..."
        elif launcher_log_state.get("running"):
            message = ("Downloading Minecraft..." if launcher_log_state.get("downloading")
                       else "Minecraft is running" if launcher_log_state.get("game_started")
                       else "Starting Minecraft...")
        else:
            message = ""
        hero_status_text.value = message
        hero_status_row.visible = bool(message)
        hero_status_icon.color = theme["btn_primary"] if is_target_installed(target) else theme["text_secondary"]
        footer_status.value = message
        footer_status.visible = bool(message)

    update_hero_status(selected_target)
    launcher_log_list = ft.ListView(
        controls=[
            ft.Text(
                line,
                size=11,
                color=theme["text_primary"],
                font_family="Consolas",
                selectable=True,
            )
            for line in launcher_log_state["lines"][-300:]
        ]
        or [
            ft.Text(
                "No launcher output yet. Launch a game to view its logs.",
                size=12,
                color=theme["text_secondary"],
            )
        ],
        expand=True,
        spacing=3,
        auto_scroll=True,
    )
    launcher_log_state["list"] = launcher_log_list

    def is_current_home() -> bool:
        return (not lifecycle["closed"] and not features.closed and active_page.get("name") == "home"
                and launcher_log_state.get("list") is launcher_log_list)

    def on_copy_logs(e):
        text = "\n".join(launcher_log_state["lines"])
        if text:
            copy_to_clipboard(text, "Copied launcher logs to clipboard!")
        else:
            notify("No logs to copy.", ft.Icons.INFO_OUTLINE)

    log_copy_button = ft.IconButton(
        hover_color=ft.Colors.TRANSPARENT,
        icon=ft.Icons.COPY,
        icon_size=16,
        tooltip=tooltip("Copy Logs"),
        icon_color=theme["text_secondary"],
        style=ft.ButtonStyle(mouse_cursor=clickable_mouse_cursor),
        on_click=on_copy_logs,
    )
    log_back_button = ft.IconButton(
        hover_color=ft.Colors.TRANSPARENT,
        icon=ft.Icons.CLOSE,
        icon_size=16,
        tooltip=tooltip("Close Logs"),
        icon_color=theme["text_secondary"],
        style=ft.ButtonStyle(mouse_cursor=clickable_mouse_cursor),
        on_click=lambda e: set_launcher_log_visible(False),
    )
    bottom_log_toggle_button = ft.Button(
        "Logs",
        icon=ft.Icons.TERMINAL,
        style=ft.ButtonStyle(
            bgcolor=theme["surface"],
            color=theme["text_secondary"],
            shape=ft.RoundedRectangleBorder(radius=8),
            mouse_cursor=clickable_mouse_cursor,
        ),
        on_click=lambda e: set_launcher_log_visible(not launcher_log_state["open"]),
    )
    launcher_log_state["bottom_log_toggle_button"] = bottom_log_toggle_button

    floating_logs_window = glass_panel(
        left=28,
        right=28,
        top=20,
        bottom=64,
        bgcolor=theme["toast"],
        border=ft.Border.all(1, theme["border"]),
        border_radius=16,
        shadow=ft.BoxShadow(
            blur_radius=28,
            spread_radius=3,
            color=ft.Colors.with_opacity(0.65, ft.Colors.BLACK),
            offset=ft.Offset(0, 8),
        ),
        padding=16,
        visible=launcher_log_state["open"],
        content=ft.Column(
            expand=True,
            spacing=10,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Icon(
                                    ft.Icons.TERMINAL,
                                    size=18,
                                    color=theme["btn_primary"],
                                ),
                                ft.Text(
                                    "MINECRAFT LOGS",
                                    size=12,
                                    weight=ft.FontWeight.BOLD,
                                    color=theme["text_primary"],
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=4,
                            controls=[
                                log_copy_button,
                                log_back_button,
                            ],
                        ),
                    ],
                ),
                ft.Container(
                    expand=True,
                    bgcolor=ft.Colors.with_opacity(0.45, theme["surface"]),
                    border=ft.Border.all(1, theme["border"]),
                    border_radius=10,
                    padding=10,
                    content=launcher_log_list,
                ),
            ],
        ),
    )
    launcher_log_state["floating_logs_window"] = floating_logs_window

    def set_launcher_log_visible(visible):
        launcher_log_state["open"] = visible
        log_back_button.visible = visible
        win = launcher_log_state.get("floating_logs_window", floating_logs_window)
        if win is not None:
            win.visible = visible
        if visible:
            active_log_list = launcher_log_state.get("list")
            if active_log_list is not None and launcher_log_state["lines"]:
                active_log_list.controls = [
                    ft.Text(
                        line,
                        size=11,
                        color=theme["text_primary"],
                        font_family="Consolas",
                        selectable=True,
                    )
                    for line in launcher_log_state["lines"][-300:]
                ]
        if active_page.get("name") != "home" and visible:
            nav_fn = navigation_state.get("navigate", navigate)
            nav_fn("home")
            return
        try:
            if win is not None:
                win.update()
        except Exception:
            pass


    def append_launcher_logs(lines):
        active_log_list = launcher_log_state["list"]
        can_update_ui = (
            active_log_list is not None
            and active_page.get("name") == "home"
            and launcher_log_state["open"]
        )
        for line in lines:
            message = redact_credentials(line.rstrip("\r\n"))
            if not message:
                continue
            if not launcher_log_state["lines"] and active_log_list is not None:
                active_log_list.controls.clear()
            launcher_log_state["lines"].append(message)
            if can_update_ui:
                active_log_list.controls.append(
                    ft.Text(
                        message,
                        size=11,
                        color=theme["text_primary"],
                        font_family="Consolas",
                        selectable=True,
                    )
                )
        if len(launcher_log_state["lines"]) > 300:
            del launcher_log_state["lines"][:-300]
        if active_log_list is not None and len(active_log_list.controls) > 300:
            del active_log_list.controls[:-300]
        if can_update_ui:
            try:
                active_log_list.update()
            except Exception:
                pass

    launcher_log_state["append_logs"] = append_launcher_logs




    def launch_is_ready():
        uname = player_name_state["value"].strip() or "Player"
        return bool(
            launch_selection["key"] in launch_targets
            and re.fullmatch(
                r"[A-Za-z0-9_]{1,16}",
                uname,
            )
        )

    library_cards: dict[str, ft.Button] = {}
    library_banner_images: dict[str, ft.Image] = {}
    selection_markers: dict[str, ft.Container] = {}
    local_art: dict[str, str | None] = {}
    artwork_queue: dict[str, dict] = {}
    attempted_art: set[str] = set()
    artwork_worker = None
    visible_keys: list[str] = []
    ordered_keys = tuple(launch_targets)

    def local_banner(key: str, target: dict) -> str | None:
        if key not in local_art:
            local_art[key] = banners.get_local_banner_for_target(target, minecraft_directory)
        return local_art[key]

    def fallback_banner(target: dict | None) -> str:
        filename = "portal.png" if target and str(target.get("loader", "Vanilla")).casefold() != "vanilla" else "farmhouse.png"
        return str(ASSETS_DIR / "banners" / filename)

    async def load_artwork() -> None:
        nonlocal artwork_worker
        try:
            while artwork_queue and is_current_home() and online_available():
                key = launch_selection["key"] if launch_selection["key"] in artwork_queue else next(iter(artwork_queue))
                target = artwork_queue.pop(key)
                if key not in visible_keys:
                    continue
                attempted_art.add(key)
                try:
                    resolved = await banners.ensure_banner_for_target(target, minecraft_directory)
                except Exception:
                    continue
                if not resolved or not is_current_home():
                    continue
                local_art[key] = resolved
                image = library_banner_images.get(key)
                if image is not None and image.src != resolved and key in visible_keys:
                    image.src = resolved
                    image.update()
        finally:
            artwork_worker = None
            if artwork_queue and is_current_home():
                request_visible_artwork()

    def request_visible_artwork() -> None:
        nonlocal artwork_worker
        if not lifecycle["mounted"] or not is_current_home() or not online_available():
            return
        keys = dict.fromkeys(visible_keys)
        for key in keys:
            target = launch_targets.get(key)
            if target and key not in attempted_art and not local_banner(key, target):
                artwork_queue[key] = target
        if artwork_queue and (artwork_worker is None or artwork_worker.done()):
            artwork_worker = page.run_task(load_artwork)

    def mount_home() -> None:
        lifecycle["mounted"] = True
        request_visible_artwork()

    def unmount_home() -> None:
        lifecycle["closed"] = True
        artwork_queue.clear()
        if artwork_worker is not None:
            artwork_worker.cancel()

    def card_style(selected: bool) -> ft.ButtonStyle:
        return ft.ButtonStyle(
            bgcolor=theme["card"], padding=0, elevation=0,
            shape=ft.RoundedRectangleBorder(radius=12),
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(2, theme["btn_primary"] if selected else theme["border"]),
                ft.ControlState.HOVERED: ft.BorderSide(2, theme["btn_primary"]),
                ft.ControlState.FOCUSED: ft.BorderSide(2, theme["btn_primary"]),
            },
            overlay_color=ft.Colors.with_opacity(0.10, theme["btn_primary"]),
            mouse_cursor=clickable_mouse_cursor,
        )

    def select_launch_target(key: str) -> None:
        if launcher_log_state.get("running") or key not in launch_targets or launch_selection["key"] == key:
            return
        old_key = launch_selection["key"]
        if not save_profile_options(player_name_state["value"], key, profile_picture_state["path"]):
            notify("Could not save the selected profile.", "error")
            return
        launch_selection["key"] = key
        target = launch_targets[key]
        selected_version_name.value = target["name"]
        selected_version_name.tooltip = tooltip(target["name"])
        selected_version_summary.value = version_summary(target)
        on_target_selected(target)
        for card_key in (old_key, key):
            if card_key in library_cards:
                selected = card_key == key
                library_cards[card_key].style = card_style(selected)
                selection_markers[card_key].visible = selected
                library_cards[card_key].update()
        refresh_launch_button(update_controls=False)
        selected_version_elements.update()
        launcher_log_state["status"] = f"Selected {target['name']}"
        progress_host.set_idle(launcher_log_state["status"])
        request_visible_artwork()

    def build_library_card(key: str, target: dict) -> ft.Button:
        selected = launch_selection["key"] == key
        caption_height = 64
        image = ft.Image(
            src=local_banner(key, target) or fallback_banner(target),
            left=0, top=0, right=0, bottom=0, fit=ft.BoxFit.COVER,
            gapless_playback=True,
        )
        library_banner_images[key] = image
        marker = ft.Container(
            top=8, right=8, bgcolor=theme["btn_primary"], border_radius=5,
            padding=ft.Padding.symmetric(horizontal=6, vertical=3), visible=selected,
            content=ft.Text("Selected", size=10, color=theme["btn_primary_text"]),
        )
        selection_markers[key] = marker
        status = "Installed" if is_target_installed(target) else "Install on launch"
        card = ft.Button(
            key=ft.ValueKey(f"home-profile-{key}"), data=key, expand=True, height=130,
            tooltip=tooltip(target["name"]), disabled=bool(launcher_log_state.get("running")),
            on_click=lambda e: select_launch_target(key), style=card_style(selected),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Container(
                # Leave the native 2px outline clear; inset artwork uses the
                # matching inner radius instead of drawing a second border.
                padding=2,
                content=ft.Container(
                    border_radius=10, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    content=ft.Stack([
                        image,
                        ft.Container(
                            left=0, top=0, right=0, bottom=0,
                            gradient=ft.LinearGradient(
                                begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                                colors=[ft.Colors.TRANSPARENT, ft.Colors.with_opacity(0.32, theme["surface"])],
                                stops=[0.2, 1],
                            ),
                        ),
                        ft.Container(
                            key=ft.ValueKey(f"home-profile-icon-{key}"),
                            left=12, top=0, bottom=caption_height, width=40,
                            alignment=ft.Alignment.CENTER, ignore_interactions=True,
                            content=ft.Container(
                                width=40, height=40, border_radius=6,
                                shadow=ft.BoxShadow(
                                    blur_radius=12, spread_radius=1,
                                    color=ft.Colors.with_opacity(0.65, ft.Colors.BLACK),
                                    offset=ft.Offset(0, 3),
                                ),
                                content=profile_icon(target, size=40),
                            ),
                        ),
                        glass_panel(
                            left=0, right=0, bottom=0, padding=12, height=caption_height,
                            bgcolor=theme["card"], border_radius=0,
                            content=ft.Column([
                                ft.Text(target["name"], size=14, weight=ft.FontWeight.W_600,
                                        color=theme["text_primary"], max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(f"{version_summary(target)} · {status}", size=11,
                                        color=theme["text_secondary"], max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                            ], spacing=3),
                        ),
                        marker,
                    ], expand=True),
                ),
            ),
        )
        library_cards[key] = card
        return card

    new_profile_card = launcher_button(
        "New Profile", lambda e: navigate("new_installation"), width=116, height=130,
        disabled=bool(launcher_log_state.get("running")),
    )
    new_profile_card.style.padding = 0
    new_profile_card.content = glass_panel(
        border_radius=8, bgcolor=ft.Colors.TRANSPARENT, width=116,
        content=ft.Column([
            ft.Icon(ft.Icons.ADD, size=26, color=theme["text_secondary"]),
            ft.Text("New Profile", size=12, color=theme["text_secondary"]),
        ], spacing=10, alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER),
    )
    library_cards_flow = ft.Row(spacing=12, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    library_shelf_container = ft.Column([
        ft.Row([
            ft.Text("Your library", size=14, weight=ft.FontWeight.W_600, color=theme["text_primary"]),
            ft.Text(f"{len(launch_targets)} {'profile' if len(launch_targets) == 1 else 'profiles'}",
                    size=11, color=theme["text_secondary"], expand=True),
            ft.TextButton("Manage all", on_click=lambda e: navigate("installations"),
                          style=ft.ButtonStyle(color=theme["text_secondary"], padding=0), height=24),
        ], height=24, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        library_cards_flow,
    ], spacing=10)

    def fit_shelf(slots: int, card_height: int) -> None:
        visible_keys[:] = ordered_keys[:slots]
        cards = [library_cards.get(key) or build_library_card(key, launch_targets[key]) for key in visible_keys]
        for card in cards:
            card.height = card_height
            image = library_banner_images[card.data]
            image.src = local_banner(card.data, launch_targets[card.data]) or fallback_banner(launch_targets[card.data])
        new_profile_card.height = card_height
        library_cards_flow.controls = [*cards, new_profile_card]
        library_cards_flow.height = card_height
        request_visible_artwork()

    fit_shelf(3, 130)
    last_running_state = None

    def refresh_launch_button(*, update_controls: bool = True):
        nonlocal last_running_state
        button = launcher_log_state.get("play_button")
        if button is None:
            return
        is_running = launcher_log_state["running"]
        is_downloading = launcher_log_state["downloading"]
        is_game_started = launcher_log_state["game_started"]
        is_cancelling = launcher_log_state["cancelling"]
        button.content = (
            "CANCELLING..."
            if is_cancelling
            else "CANCEL"
            if is_running and is_downloading
            else "RUNNING..."
            if is_running and is_game_started
            else "STARTING..."
            if is_running
            else "PLAY" if is_target_installed(launch_targets.get(launch_selection["key"])) else "INSTALL & PLAY"
        )
        button.icon = (
            ft.Icons.HOURGLASS_TOP
            if is_cancelling
            else ft.Icons.CLOSE
            if is_running and is_downloading
            else ft.Icons.SPORTS_ESPORTS_OUTLINED
            if is_running and is_game_started
            else ft.Icons.HOURGLASS_TOP
            if is_running
            else ft.Icons.PLAY_ARROW
        )
        button.disabled = (
            is_cancelling
            or (is_running and not is_downloading)
            or (not is_running and not launch_is_ready())
        )
        if is_running:
            button.style.mouse_cursor = {
                ft.ControlState.DISABLED: ft.MouseCursor.PROGRESS,
                ft.ControlState.DEFAULT: ft.MouseCursor.PROGRESS,
            }
        else:
            button.style.mouse_cursor = clickable_mouse_cursor
        update_hero_status(launch_targets.get(launch_selection["key"]))
        hero_edit_button.disabled = is_running or not bool(launch_targets)
        running_changed = last_running_state != is_running
        if running_changed:
            for card in library_cards.values():
                card.disabled = is_running
            new_profile_card.disabled = is_running
            last_running_state = is_running
        if not update_controls:
            return
        try:
            selected_version_elements.update()
            footer_status.update()
            if running_changed:
                library_cards_flow.update()
        except Exception:
            pass

    async def launch_selected_game():
        target = launch_targets.get(launch_selection['key'])
        if target is None:
            notify('Select a Minecraft profile first.', 'warning')
            return
        await launch_profile(dict(target))

    async def handle_play_button_action():
        if launcher_log_state["running"]:
            if launcher_log_state["downloading"]:
                launcher_log_state["cancelling"] = True
                cancel_event = launcher_log_state["cancel_event"]
                if cancel_event is not None:
                    cancel_event.set()
                append_launcher_logs(
                    ["[Launcher] Cancellation requested; finishing the current file..."]
                )
                update_launch_progress(
                    "Cancelling after the current file...", value=None, eta=""
                )
                refresh_launch_button()
            return
        await launch_selected_game()

    launcher_log_state["launch_selected_game"] = launch_selected_game

    play_button = ft.Button(
        "PLAY", icon=ft.Icons.PLAY_ARROW, width=176, height=42,
        style=launcher_button("PLAY", None, primary=True).style,
        on_click=lambda e: page.run_task(handle_play_button_action),
    )
    launcher_log_state["play_button"] = play_button
    launcher_log_state["refresh_play_button"] = refresh_launch_button

    def open_current_folder(e) -> None:
        target = launch_targets.get(launch_selection["key"])
        directory = (target or {}).get("game_directory")
        if not directory and target and target.get("instance_name"):
            directory = str(Path(minecraft_directory) / "instances" / target["instance_name"])
        open_game_folder(directory or minecraft_directory)

    def edit_current_profile(e) -> None:
        target = launch_targets.get(launch_selection["key"])
        if target and target.get("key") != "latest-release" and "id" in target:
            navigate("edit_installation", target["id"])
        elif target:
            features.edit_latest_profile()

    hero_edit_button = launcher_icon_button(
        icon=ft.Icons.EDIT_OUTLINED, tooltip="Edit profile", on_click=edit_current_profile,
    )
    hero_folder_button = launcher_icon_button(
        icon=ft.Icons.FOLDER_OPEN_OUTLINED, tooltip="Open profile folder", on_click=open_current_folder,
    )
    profile_actions = glass_panel(
        height=42, border_radius=8, padding=3,
        content=ft.Row([hero_edit_button, hero_folder_button], spacing=2, tight=True),
    )
    selected_version_elements = ft.Container(
        width=660,
        content=ft.Column([
            ft.Text("MINECRAFT JAVA EDITION", font_family="Pixelify Sans", size=14,
                    color=theme["text_secondary"]),
            selected_version_name,
            ft.Row([selected_version_summary], spacing=10),
            hero_status_row,
            ft.Row([play_button, profile_actions], spacing=8, wrap=True,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=12, alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )
    hero_details = ft.Container(
        left=0, top=0, right=0, bottom=0,
        padding=ft.Padding.symmetric(horizontal=32, vertical=16),
        alignment=ft.Alignment.CENTER_LEFT, content=selected_version_elements,
    )
    selected_version_elements.content.spacing = 8
    selected_installation_card = ft.Container(
        key=ft.ValueKey("home-hero"), expand=True,
        content=ft.Stack([hero_details], expand=True),
    )
    bottom_log_toggle_button.height = 28
    home_status_row = ft.Row([footer_status, bottom_log_toggle_button], height=28,
                             alignment=ft.MainAxisAlignment.END,
                             vertical_alignment=ft.CrossAxisAlignment.CENTER)
    body_column = ft.Column(
        [account_row, selected_installation_card, library_shelf_container, home_status_row],
        expand=True, spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    geometry = {"slots": 3, "card_height": 130, "text_width": 660, "scroll": False,
                "title_size": 42, "compact": True}

    def resize_home(e: ft.LayoutSizeChangeEvent) -> None:
        if not e.width or not e.height:
            return
        width = max(1, e.width - 56)
        slots = max(1, min(4, int((width - 116 + 12) // 272)))
        card_height = 150 if e.height >= 620 else 130
        text_width = min(740, max(240, int((width - 64) * 0.72) // 8 * 8))
        title_size = 48 if width >= 1180 else 42
        scroll = e.height < 520
        compact = e.height < 620
        if (slots, card_height) != (geometry["slots"], geometry["card_height"]):
            fit_shelf(slots, card_height)
            library_shelf_container.update()
        if text_width != geometry["text_width"]:
            selected_version_elements.width = text_width
            selected_version_elements.update()
        if title_size != geometry["title_size"]:
            selected_version_name.size = title_size
            selected_version_name.update()
        if compact != geometry["compact"]:
            hero_details.padding = ft.Padding.symmetric(horizontal=32, vertical=16 if compact else 24)
            selected_version_elements.content.spacing = 8 if compact else 12
            hero_details.update()
        if scroll != geometry["scroll"]:
            body_column.scroll = ft.ScrollMode.AUTO if scroll else None
            selected_installation_card.expand = False if scroll else True
            selected_installation_card.height = 250 if scroll else None
            body_column.update()
        geometry.update(slots=slots, card_height=card_height, text_width=text_width,
                        scroll=scroll, title_size=title_size, compact=compact)

    refresh_launch_button()
    reveal_controls = [account_row, selected_installation_card, library_shelf_container, home_status_row]
    for control in reveal_controls:
        prepare_intro(control)
    home_view = _HomeView(
        expand=True, on_mount=mount_home, on_unmount=unmount_home,
        content=ft.Stack([
            ft.Container(expand=True, padding=ft.Padding(left=28, top=20, right=28, bottom=16),
                         content=body_column),
            floating_logs_window,
        ], expand=True, on_size_change=resize_home),
    )
    home_view.data = {"reveal_controls": reveal_controls}
    return home_view
