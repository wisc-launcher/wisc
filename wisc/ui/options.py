"""
Options Dashboard and Settings Subpages for Wisc.
"""

from pathlib import Path
import os
import random
import sys
import subprocess
import flet as ft
from wisc.ui.controls import LegacySelector, SimpleInput, launcher_button, launcher_back_button
from wisc.ui.scroll_views import ScrollColumn
from wisc.ui.glass import glass_panel
from wisc.ui.settings_art import settings_art
from wisc.ui.theme_picker import ThemePicker, color_wheel_surface
from wisc.services import updates as launcher_updates
from wisc.core.themes import DEFAULT_THEME
import json
import threading
from wisc.core.storage import (
    DEFAULT_SETTINGS,
    load_settings,
    save_settings,
    save_theme_choice,
    load_accounts,
    get_active_account,
    set_active_account,
    remove_account,
    update_offline_username,
)
from wisc.services import auth as ely_auth
from wisc.services import skins
from wisc.ui.components import (
    rounded_button_style,
    clickable_mouse_cursor,
    tooltip,
    build_themed_switch,
    create_ambient_gradient_orbs,
    animate_ambient_gradient_orbs,
)
from wisc.core import state

from wisc.core.paths import ASSETS_DIR
THOUGHTS_FILE = ASSETS_DIR / "thoughts.json"

DEFAULT_THOUGHTS = [
    "Don't dig straight down in Minecraft or in life; pause, look ahead, and choose a safer next step.",
    "Every great Minecraft build begins with one block, and every big change begins with one small action.",
    "Keep exploring: the diamonds you find in a cave are a reminder that hard seasons can still hold hope.",
    "Place a torch where it's dark, and offer a little kindness where someone needs encouragement.",
    "Your Minecraft inventory has limits; make room in life for what matters most.",
    "A world is built one block at a time, and a good life is shaped by small choices made with care.",
    "It's okay to wander off the map; unexpected paths can lead to your favorite discoveries.",
]


def load_thoughts() -> list[str]:
    if THOUGHTS_FILE.is_file():
        try:
            with open(THOUGHTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    parsed = [str(item).strip() for item in data if str(item).strip()]
                    if parsed:
                        return parsed
        except Exception:
            pass
    return DEFAULT_THOUGHTS


def get_random_thought() -> str:
    thoughts = load_thoughts()
    return random.choice(thoughts) if thoughts else DEFAULT_THOUGHTS[0]


def open_system_folder(folder_path: str):
    try:
        path = Path(folder_path)
        path.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def build_options_views(
    page: ft.Page,
    theme: dict,
    settings: dict,
    persist_setting,
    navigate,
    notify,
    copy_to_clipboard,
    open_url,
    theme_dropdown: LegacySelector,
    available_themes: list[str],
    maximum_memory_mb: int,
    minecraft_directory: str,
    account_picture_preview: ft.Control = None,
    refresh_account_picture = None,
    update_sidebar_username = None,
    refresh_launch_button = None,
    rebuild_page_callback = None,
    set_orbs_enabled = None,
    show_dialog_with_blur = None,
    close_dialog_with_blur = None,
    features = None,
    apply_custom_theme = None,
) -> dict[str, ft.Control]:
    selected_theme = state.selected_theme
    active_page = state.active_page
    options_background_state = state.options_background_state
    player_name_state = state.player_name_state


    def build_option_card(category: dict) -> ft.Container:
        button = launcher_button("", lambda e: navigate(category["id"]), height=108)
        button.style.bgcolor = {
            ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,
            ft.ControlState.HOVERED: theme["card_hover"],
        }
        button.style.shape = ft.RoundedRectangleBorder(radius=12)
        button.style.padding = ft.Padding.all(18)
        button.content = ft.Row(
            spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                settings_art(category["art"], theme["btn_primary"], width=48, height=48),
                ft.Column(
                    expand=True, spacing=5,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.START,
                    controls=[
                        ft.Text(category["title"], size=16, weight=ft.FontWeight.W_600,
                                color=theme["text_primary"]),
                        ft.Text(category["description"], size=12, color=theme["text_secondary"]),
                    ],
                ),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=20, color=theme["text_muted"]),
            ],
        )
        return glass_panel(
            button, border_radius=12, bgcolor=theme["surface"],
            col={"xs": 12, "md": 6, "lg": 4},
        )

    options_categories = [
        {"id": "options_ui", "title": "Appearance", "art": "appearance",
         "description": "Your colors, your atmosphere"},
        {"id": "options_java", "title": "Java & Memory", "art": "java",
         "description": "Java executable and allocated RAM"},
        {"id": "options_game", "title": "Game", "art": "game",
         "description": "Window size, fullscreen and skins"},
        {"id": "options_accounts", "title": "Accounts", "art": "accounts",
         "description": "Manage players, sign-ins and skins"},
        {"id": "options_launcher", "title": "Launcher", "art": "launcher",
         "description": "Launch behavior, Discord and logs"},
    ]
    if features:
        options_categories.append(
            {"id": "options_updates", "title": "Updates", "art": "updates",
             "description": "Check for the latest Wisc release"})

    category_cards = [build_option_card(category) for category in options_categories]
    dashboard_header = ft.Row(
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Column(
                expand=True, spacing=6,
                controls=[
                    ft.Text("Settings", size=24, weight=ft.FontWeight.BOLD, color=theme["text_primary"]),
                    ft.Text("Make Wisc feel at home.", size=13, color=theme["text_secondary"]),
                ],
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                border_radius=8, bgcolor=theme["surface"],
                content=ft.Row([
                    ft.Container(width=8, height=8, border_radius=4, bgcolor=theme["btn_primary"]),
                    ft.Text(selected_theme["name"], size=12, color=theme["text_secondary"]),
                ], spacing=8, tight=True),
            ),
        ],
    )
    dashboard_footer = glass_panel(
        bgcolor=theme["surface"], border_radius=12,
        padding=ft.Padding.symmetric(horizontal=18, vertical=12),
        content=ft.ResponsiveRow(
            spacing=12, run_spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Column([
                    ft.Text("Wisc", size=16, font_family="Pixelify Sans", color=theme["text_primary"]),
                    ft.Text("A little help for your next adventure.", size=12, color=theme["text_secondary"]),
                ], spacing=4, col={"xs": 12, "md": 6}),
                ft.Row([
                    launcher_button("About Wisc", lambda e: navigate("options_about"), icon=ft.Icons.INFO_OUTLINE),
                    launcher_button("Replay welcome tour", lambda e: navigate("onboarding"),
                                    icon=ft.Icons.AUTO_AWESOME_OUTLINED),
                ], spacing=8, wrap=True, alignment=ft.MainAxisAlignment.END, col={"xs": 12, "md": 6}),
            ],
        ),
    )
    dashboard_hero = glass_panel(
        bgcolor=theme["surface"], border_radius=12,
        padding=ft.Padding.symmetric(horizontal=24, vertical=18),
        content=ft.Row([
            ft.Column([
                ft.Text("Color studio", size=24, weight=ft.FontWeight.W_600,
                        color=theme["text_primary"]),
                ft.Text("Dial in your own accent with a color wheel and live preview.",
                        size=13, color=theme["text_secondary"]),
                launcher_button("Customize your colors", lambda e: navigate("options_ui"),
                                primary=True, height=36),
            ], expand=True, spacing=10),
            ft.Container(
                content=color_wheel_surface(116), width=116, height=116,
                ignore_interactions=True, opacity=0.9,
            ),
        ], spacing=24, vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )
    options_orb1, options_orb2 = create_ambient_gradient_orbs(theme, settings.get("enable_orbs", True))
    options_dashboard = ft.Stack(
        expand=True, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        data={"reveal_controls": [dashboard_header, dashboard_hero, *category_cards, dashboard_footer]},
        controls=[
            options_orb1, options_orb2,
            ft.Container(
                expand=True, padding=ft.Padding.symmetric(horizontal=28, vertical=20),
                content=ScrollColumn(
                    expand=True, spacing=20, scroll=ft.ScrollMode.AUTO,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    controls=[
                        dashboard_header,
                        dashboard_hero,
                        ft.ResponsiveRow(category_cards, spacing=12, run_spacing=12),
                        dashboard_footer,
                    ],
                ),
            ),
        ],
    )

    async def animate_options_background():
        if options_background_state["animation_running"]:
            return
        options_background_state["animation_running"] = True
        try:
            await animate_ambient_gradient_orbs(
                options_orb1,
                options_orb2,
                lambda: active_page.get("name") == "options",
                lambda: settings.get("enable_orbs", True),
            )
        finally:
            options_background_state["animation_running"] = False

    options_background_state["animate"] = animate_options_background

    def build_setting_container(
        title: str,
        explanation: str,
        control: ft.Control | None = None,
        extra_content: ft.Control | None = None,
    ) -> ft.Container:
        description = ft.Column(
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Text(title, size=15, weight=ft.FontWeight.W_600, color=theme["text_primary"]),
                ft.Text(explanation, size=12, color=theme["text_secondary"]),
            ],
        )
        items: list[ft.Control] = [description]
        if isinstance(control, ft.Switch):
            description.expand = True
            items = [ft.Row([description, control], spacing=24,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        elif control is not None:
            items.append(ft.Container(content=control, padding=ft.Padding.only(top=8)))
        if extra_content is not None:
            items.append(ft.Container(content=extra_content, padding=ft.Padding.only(top=6)))
        return glass_panel(
            bgcolor=theme["surface"], border_radius=12,
            padding=ft.Padding.symmetric(horizontal=20, vertical=18),
            content=ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=items),
        )

    def build_settings_page(
        title: str,
        setting_items: list[ft.Container],
        on_reset=None,
    ) -> ft.Container:
        subtitles = {
            "Appearance": "Your palette and background effects.",
            "Java & Memory": "Give Minecraft the resources it needs.",
            "Game": "Set up your next Minecraft session.",
            "Launcher": "Choose how Wisc works around your game.",
            "About": "The launcher, its creator and your game files.",
            "Updates": "Keep Wisc up to date.",
        }
        header_art = {"Appearance": "appearance", "Java & Memory": "java", "Game": "game",
                      "Launcher": "launcher", "Updates": "updates"}.get(title)
        header = ft.Row(
            spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                launcher_back_button(lambda e: navigate("options"), label="Settings", tooltip="Back to Settings"),
                ft.Column(
                    expand=True, spacing=4,
                    controls=[
                        ft.Text(title, size=24, weight=ft.FontWeight.BOLD, color=theme["text_primary"]),
                        ft.Text(subtitles.get(title, ""), size=12, color=theme["text_secondary"]),
                    ],
                ),
                *([settings_art(header_art, theme["btn_primary"], width=58, height=50)] if header_art else []),
                *([launcher_button("Reset defaults", on_reset, icon=ft.Icons.RESTORE)] if on_reset else []),
            ],
        )
        return ft.Container(
            expand=True, padding=ft.Padding.symmetric(horizontal=28, vertical=20),
            data={"reveal_controls": [header, *setting_items]},
            content=ft.Column(
                expand=True, spacing=20, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                controls=[
                    header,
                    ScrollColumn(
                        setting_items, expand=True, spacing=12, scroll=ft.ScrollMode.AUTO,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                ],
            ),
        )

    theme_palette_preview = ft.Row(
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Container(
                width=28,
                height=28,
                border_radius=6,
                bgcolor=theme["btn_primary"],
                border=ft.Border.all(1, theme["border"]),
                tooltip="Accent",
            ),
            ft.Container(
                width=28,
                height=28,
                border_radius=6,
                bgcolor=theme["card"],
                border=ft.Border.all(1, theme["border"]),
                tooltip="Card",
            ),
            ft.Container(
                width=28,
                height=28,
                border_radius=6,
                bgcolor=theme["surface"],
                border=ft.Border.all(1, theme["border"]),
                tooltip="Surface",
            ),
            ft.Container(
                width=28,
                height=28,
                border_radius=6,
                bgcolor=theme["bg"],
                border=ft.Border.all(1, theme["border"]),
                tooltip="Background",
            ),
            ft.Text(
                f"{selected_theme['name']} · {theme['btn_primary'].upper()}",
                size=11,
                color=theme["text_muted"],
            ),
        ],
    )

    def rebuild_settings_page(message):
        rebuild_page_callback(selected_theme["name"], active_page["name"])
        notify(message, ft.Icons.RESTORE)

    def reset_settings_fields(field_names, section_name):
        current = load_settings()
        for field_name in field_names:
            current[field_name] = DEFAULT_SETTINGS[field_name]
        if not save_settings(current):
            notify("Could not restore settings.", "error")
            return
        settings.update(current)
        rebuild_settings_page(f"{section_name} settings restored to defaults.")

    def reset_ui_settings(e):
        if features and features.busy:
            notify("Wait for the current operation before changing themes.", "warning")
            return
        default_theme = (
            DEFAULT_THEME
            if DEFAULT_THEME in available_themes
            else available_themes[0]
        )
        current = load_settings()
        updated = {**current, "enable_orbs": DEFAULT_SETTINGS["enable_orbs"],
                   "custom_accent": DEFAULT_SETTINGS["custom_accent"]}
        if not save_settings(updated):
            notify("Could not save appearance settings.", "error")
            return
        if not save_theme_choice(default_theme):
            save_settings(current)
            notify("Could not save the selected theme.", "error")
            return
        settings.update(updated)
        selected_theme["name"] = default_theme
        rebuild_page_callback(default_theme, active_page["name"])
        notify("UI settings restored to defaults.", ft.Icons.RESTORE)

    ui_subpage = build_settings_page(
        "Appearance",
        [
            *([build_setting_container(
                "Custom color",
                "Choose an accent for buttons, selections and focus. Preview it below, then apply.",
                extra_content=ThemePicker(settings.get("custom_accent", theme["btn_primary"]),
                                          theme, apply_custom_theme),
            )] if apply_custom_theme else []),
            build_setting_container(
                "Minecraft palettes",
                "Start with a favorite palette, or return to your saved Custom color.",
                control=theme_dropdown,
                extra_content=theme_palette_preview,
            ),
            build_setting_container(
                "Ambient Background Orbs",
                "Display subtle animated gradient orbs in the background of screens.",
                control=build_themed_switch(
                    label="Enable background orbs",
                    value=settings.get("enable_orbs", True),
                    theme=theme,
                    on_change=lambda e: set_orbs_enabled(e.control.value),
                ),
            ),
        ],
        on_reset=reset_ui_settings,
    )

    ram_input_ref = {}

    def set_ram_value(value):
        value = min(maximum_memory_mb, max(256, int(value)))
        persist_setting("ram_mb", value)
        field = ram_input_ref.get("control")
        if field is not None and field.value != str(value):
            field.value = str(value)
            field.update()

    def on_ram_slider_change(e):
        set_ram_value(round(e.control.value))

    def on_ram_input_change(e):
        try:
            value = int(e.control.value)
        except (TypeError, ValueError):
            return
        if 256 <= value <= maximum_memory_mb:
            persist_setting("ram_mb", value)
            ram_slider.value = value
            ram_slider.update()

    def on_ram_input_blur(e):
        try:
            value = int(e.control.value)
        except (TypeError, ValueError):
            value = int(settings["ram_mb"])
        set_ram_value(value)

    ram_slider = ft.Slider(
        min=256,
        max=max(512, maximum_memory_mb),
        divisions=max(1, (max(512, maximum_memory_mb) - 256) // 256),
        value=settings["ram_mb"],
        active_color=theme["btn_primary"],
        inactive_color=theme["border"],
        expand=True,
        on_change=on_ram_slider_change,
    )
    ram_input = SimpleInput(
        hint_text="RAM",
        value=str(settings["ram_mb"]),
        width=132,
        suffix=ft.Text("MB", color=theme["text_secondary"]),
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        fill_color=theme["card"],
        border_radius=5,
        on_change=on_ram_input_change,
        on_blur=on_ram_input_blur,
    )
    ram_input_ref["control"] = ram_input

    def on_java_path_change(e):
        persist_setting("java_path", e.control.value or "")

    def on_positive_integer_change(setting_key):
        def handler(e):
            try:
                value = int(e.control.value)
            except (TypeError, ValueError):
                return
            if value > 0:
                persist_setting(setting_key, value)

        return handler

    java_subpage = build_settings_page(
        "Java & Memory",
        [
            build_setting_container(
                "Allocated Memory (RAM)",
                f"Allocate between 256 MB and {maximum_memory_mb:,} MB of detected system memory.",
                control=ft.Row(
                    spacing=16,
                    controls=[
                        ram_slider,
                        ram_input,
                    ],
                ),
            ),
            build_setting_container(
                "Java Executable",
                "Leave empty to use system Java, or enter the path to your Java executable.",
                control=SimpleInput(
                    hint_text="e.g. C:\\Program Files\\Java\\jdk-21\\bin\\java.exe",
                    border_color=theme["border"],
                    focused_border_color=theme["btn_primary"],
                    color=theme["text_primary"],
                    fill_color=theme["card"],
                    border_radius=5,
                    expand=True,
                    value=settings["java_path"],
                    on_change=on_java_path_change,
                ),
            ),
        ],
        on_reset=lambda e: reset_settings_fields(
            ("ram_mb", "java_path"), "Java"
        ),
    )

    game_subpage = build_settings_page(
        "Game",
        [
            build_setting_container(
                "Default Window Resolution",
                "The window resolution applied when Minecraft starts up.",
                control=ft.Row(
                    spacing=12,
                    controls=[
                        SimpleInput(
                            hint_text="Pixels",
                            keyboard_type=ft.KeyboardType.NUMBER,
                            value=str(settings["window_width"]),
                            width=110,
                            prefix=ft.Text("W: ", color=theme["text_secondary"]),
                            border_color=theme["border"],
                            focused_border_color=theme["btn_primary"],
                            color=theme["text_primary"],
                            fill_color=theme["card"],
                            border_radius=5,
                            on_change=on_positive_integer_change("window_width"),
                        ),
                        SimpleInput(
                            hint_text="Pixels",
                            keyboard_type=ft.KeyboardType.NUMBER,
                            value=str(settings["window_height"]),
                            width=110,
                            prefix=ft.Text("H: ", color=theme["text_secondary"]),
                            border_color=theme["border"],
                            focused_border_color=theme["btn_primary"],
                            color=theme["text_primary"],
                            fill_color=theme["card"],
                            border_radius=5,
                            on_change=on_positive_integer_change("window_height"),
                        ),
                    ],
                ),
            ),
            build_setting_container(
                "Fullscreen",
                "Launch Minecraft directly in fullscreen mode.",
                control=build_themed_switch(
                    label="Start in fullscreen",
                    value=settings["fullscreen"],
                    theme=theme,
                    on_change=lambda e: persist_setting(
                        "fullscreen", e.control.value
                    ),
                ),
            ),
            build_setting_container(
                "Custom Skins",
                "Show Ely.by skins or your offline account's local skin and cape in-game.",
                control=build_themed_switch(
                    label="Enable in-game skins and capes",
                    value=settings.get("enable_custom_skins", True),
                    theme=theme,
                    on_change=lambda e: persist_setting(
                        "enable_custom_skins", e.control.value
                    ),
                ),
            ),
        ],
        on_reset=lambda e: reset_settings_fields(
            ("window_width", "window_height", "fullscreen", "enable_custom_skins"), "Game"
        ),
    )

    def open_custom_dialog(dlg):
        if callable(show_dialog_with_blur):
            show_dialog_with_blur(dlg)
        else:
            page.show_dialog(dlg)
            page.update()

    def close_custom_dialog(dlg):
        if callable(close_dialog_with_blur):
            close_dialog_with_blur(dlg)
        else:
            dlg.open = False
            try:
                page.close(dlg)
            except Exception:
                pass
            page.update()

    def show_ely_login_dialog(account=None):
        navigate("account_login", account.get("id") if account else None)

    active_account = get_active_account()
    accounts_data = load_accounts()
    saved_accounts = accounts_data.get("accounts", [])

    offline_account = active_account if active_account.get("type") == "offline" else None
    offline_name = (offline_account.get("username") if offline_account else player_name_state["value"]) or "Player"

    if features:
        features.open_ely_login = show_ely_login_dialog

    def open_edit_offline_name_dialog():
        edit_name_field = SimpleInput(
            label="Offline Player Username",
            value=offline_name,
            width=320,
            max_length=16,
            autofocus=True,
            hint_text="1-16 letters, numbers, or _",
            border_color=theme["border"],
            focused_border_color=theme["btn_primary"],
            color=theme["text_primary"],
            label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
            cursor_color=theme["btn_primary"],
            fill_color=theme["card"],
            border_radius=8,
        )

        name_error_text = ft.Text(
            "",
            size=12,
            color=ft.Colors.RED_400,
            weight=ft.FontWeight.W_500,
            visible=False,
        )

        def on_save_name(e):
            val = (edit_name_field.value or "").strip()
            if not val:
                name_error_text.value = "Username cannot be empty."
                name_error_text.visible = True
                edit_dlg.update()
                return

            if not all(char.isascii() and (char.isalnum() or char == "_") for char in val) or len(val) > 16:
                name_error_text.value = "Use 1-16 letters, numbers, or underscores."
                name_error_text.visible = True
                edit_dlg.update()
                return
            if not update_offline_username(val):
                name_error_text.value = "Could not save the username. Try again."
                name_error_text.visible = True
                edit_dlg.update()
                return
            active_acc = get_active_account()
            if active_acc.get("type") == "offline":
                player_name_state["value"] = val
                if callable(update_sidebar_username):
                    update_sidebar_username()
                if callable(refresh_account_picture):
                    refresh_account_picture()
                if callable(refresh_launch_button):
                    refresh_launch_button()

            close_custom_dialog(edit_dlg)
            rebuild_settings_page(f"Offline username changed to '{val}'.")
            notify(f"Updated offline username to '{val}'", ft.Icons.CHECK_CIRCLE)

        btn_primary_text = theme.get("btn_primary_text", theme["text_primary"])

        save_btn = ft.Button(
            "Save",
            bgcolor=theme["btn_primary"],
            color=btn_primary_text,
            style=rounded_button_style,
            on_click=on_save_name,
            height=38,
        )

        cancel_edit_btn = ft.Button(
            "Cancel",
            bgcolor=theme["surface"],
            color=theme["text_primary"],
            style=rounded_button_style,
            on_click=lambda e: close_custom_dialog(edit_dlg),
            height=38,
        )

        edit_actions_row = ft.Row(
            alignment=ft.MainAxisAlignment.END,
            spacing=10,
            controls=[cancel_edit_btn, save_btn],
        )

        edit_dialog_content = ft.Container(
            width=340,
            content=ft.Column(
                tight=True,
                spacing=14,
                controls=[
                    ft.Text(
                        "Change your username for playing in offline mode.",
                        size=12,
                        color=theme["text_secondary"],
                    ),
                    edit_name_field,
                    name_error_text,
                    ft.Container(height=4),
                    edit_actions_row,
                ],
            ),
        )

        edit_dlg = ft.AlertDialog(
            modal=False,
            bgcolor=theme["card"],
            shape=ft.RoundedRectangleBorder(radius=14),
            on_dismiss=lambda e: close_custom_dialog(edit_dlg),
            title=ft.Row(
                spacing=10,
                controls=[
                    ft.Icon(ft.Icons.EDIT_OUTLINED, color=theme["btn_primary"], size=22),
                    ft.Text("Edit Offline Username", size=18, weight=ft.FontWeight.BOLD, color=theme["text_primary"]),
                ],
            ),
            content=edit_dialog_content,
        )

        open_custom_dialog(edit_dlg)

    def make_switch_handler(target_id, target_name):
        def handler(e):
            if not set_active_account(target_id):
                notify("Could not switch accounts.", ft.Icons.ERROR_OUTLINE)
                return
            player_name_state["value"] = target_name
            if callable(update_sidebar_username):
                update_sidebar_username()
            if callable(refresh_account_picture):
                refresh_account_picture()
            if callable(refresh_launch_button):
                refresh_launch_button()
            rebuild_settings_page(f"Switched active account to {target_name}.")
        return handler

    def make_logout_handler(target_id, target_name):
        def handler(e):
            def do_logout():
                from wisc.core import storage
                account = next((item for item in storage.load_accounts(include_credentials=True).get('accounts', [])
                                if item.get('id') == target_id), {})
                token = account.get('access_token')
                client = account.get('client_token')
                if token and client:
                    try:
                        ely_auth.invalidate_token(token, client)
                    except Exception:
                        pass
                if not remove_account(target_id):
                    notify("Could not remove the account.", ft.Icons.ERROR_OUTLINE)
                    return
                new_active = get_active_account()
                player_name_state["value"] = new_active.get("username", "Player")
                if callable(update_sidebar_username):
                    update_sidebar_username()
                if callable(refresh_account_picture):
                    refresh_account_picture()
                if callable(refresh_launch_button):
                    refresh_launch_button()
                rebuild_settings_page(f"Logged out of {target_name}.")
            threading.Thread(target=do_logout, daemon=True).start()
        return handler

    def make_sync_handler(target_name):
        def handler(e):
            def do_sync():
                try:
                    skins.fetch_ely_skin(target_name, force_refresh=True, timeout=3.0)
                    if callable(refresh_account_picture):
                        refresh_account_picture()
                    notify(f"Synced latest skin from Ely.by for {target_name}!", ft.Icons.CHECK_CIRCLE)
                except Exception as err:
                    notify(f"Could not sync skin: {err}", ft.Icons.ERROR_OUTLINE)
            threading.Thread(target=do_sync, daemon=True).start()
        return handler

    from wisc.ui.accounts import build_accounts_view

    accounts_subpage = build_accounts_view(
        theme=theme, accounts=saved_accounts, active_account=active_account,
        on_add=show_ely_login_dialog, on_login=show_ely_login_dialog,
        on_switch=lambda account: make_switch_handler(account["id"], account["username"])(None),
        on_logout=lambda account: make_logout_handler(account["id"], account["username"])(None),
        on_sync=lambda account: make_sync_handler(account["username"])(None),
        on_edit_offline=open_edit_offline_name_dialog,
        on_back=lambda: navigate("options"),
    )

    launcher_subpage = build_settings_page(
        "Launcher",
        [
            build_setting_container(
                "Discord Presence", "Show your launcher and Minecraft activity in Discord.",
                control=build_themed_switch("Share activity", bool(settings.get("discord_rpc", True)), theme=theme,
                    on_change=lambda e: persist_setting("discord_rpc", e.control.value))),
            build_setting_container(
                "Action on Launch",
                "Choose what Wisc does when Minecraft starts.",
                control=LegacySelector(
                    value=settings["launch_action"],
                    options=[
                        ft.DropdownOption(
                            key="Hide launcher",
                            text="Hide launcher (Default)",
                        ),
                        ft.DropdownOption(
                            key="Keep launcher open",
                            text="Keep launcher open",
                        ),
                        ft.DropdownOption(
                            key="Close launcher",
                            text="Close launcher",
                        ),
                    ],
                    width=260,
                    border_color=theme["border"],
                    focused_border_color=theme["btn_primary"],
                    color=theme["text_primary"],
                    fill_color=theme["card"],
                    border_radius=8,
                    on_select=lambda e: persist_setting(
                        "launch_action", e.control.value
                    ),
                ),
            ),
            build_setting_container(
                "Log Capture",
                "Capture standard output to log files for crash inspection.",
                control=build_themed_switch(
                    label="Record logs to disk",
                    value=settings["capture_logs"],
                    theme=theme,
                    on_change=lambda e: persist_setting(
                        "capture_logs", e.control.value
                    ),
                ),
            ),
        ],
        on_reset=lambda e: reset_settings_fields(
            ("launch_action", "capture_logs", "discord_rpc"), "Launcher"
        ),
    )

    def on_card_hover(e, container, resting_color):
        is_hovered = e.data == "true"
        container.bgcolor = theme["card_hover"] if is_hovered else resting_color
        container.update()

    def mini_badge(text, color=None):
        return ft.Container(
            bgcolor=theme["card"],
            border=ft.Border.all(1, color=theme["border"]),
            border_radius=6,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            content=ft.Text(
                text,
                size=11,
                weight=ft.FontWeight.W_500,
                color=color or theme["text_secondary"],
            ),
        )

    # 1. Header Card (Minimal branding & vision)
    about_hero_card = glass_panel(
        bgcolor=theme["surface"],
        border=ft.Border.all(1, color=theme["border"]),
        border_radius=12,
        padding=ft.Padding.all(20),
        content=ft.Column(
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.START,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=0,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Image(src="icons/wisc_mark.png",
                                         width=36, height=26, fit=ft.BoxFit.CONTAIN),
                                ft.Container(width=10),
                                ft.Text(
                                    "Wisc",
                                    font_family="Pixelify Sans",
                                    size=24,
                                    weight=ft.FontWeight.BOLD,
                                    color=theme["text_primary"],
                                ),
                                ft.Container(width=8),
                                ft.Container(content=mini_badge(launcher_updates.version_label(), color=theme["btn_primary"]),
                                             on_click=lambda e: features and features.updater.show_release_notes(),
                                             tooltip="What's new"),
                            ],
                        ),
                        mini_badge("Stable", color=theme["btn_primary"]),
                    ],
                ),
                ft.Text(
                    "Wisc is a Minecraft Java Edition launcher for managing versions, profiles, mods, and skins.",
                    size=13,
                    color=theme["text_secondary"],
                ),
                ft.Row(
                    spacing=8,
                    controls=[
                        mini_badge("Minimalism"),
                        mini_badge("Functionality"),
                        mini_badge("Clean UX"),
                    ],
                ),
            ],
        ),
    )
    about_hero_card.on_hover = lambda e, c=about_hero_card: on_card_hover(e, c, theme["surface"])

    # 2. Creator & Links Card (Unified, clean)
    discord_id_pill_card = glass_panel(
        bgcolor=theme["card"],
        border=ft.Border.all(1, color=theme["border"]),
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=10, vertical=6),
        ink=True,
        tooltip=tooltip("Click to copy Discord ID (@jaydeeppatil23)"),
        on_click=lambda e: copy_to_clipboard(
            "@jaydeeppatil23",
            "Copied Discord ID to clipboard: @jaydeeppatil23",
        ),
        content=ft.Row(
            spacing=6,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Icon(
                    ft.Icons.DISCORD,
                    size=16,
                    color=theme["btn_primary"],
                ),
                ft.Text(
                    "@jaydeeppatil23",
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=theme["text_primary"],
                ),
                ft.Icon(
                    ft.Icons.CONTENT_COPY_ROUNDED,
                    size=13,
                    color=theme["text_muted"],
                ),
            ],
        ),
    )
    discord_id_pill_card.on_hover = lambda e, c=discord_id_pill_card: on_card_hover(e, c, theme["card"])
    discord_id_pill = ft.GestureDetector(
        mouse_cursor=ft.MouseCursor.CLICK,
        content=discord_id_pill_card,
    )

    creator_social_card = glass_panel(
        bgcolor=theme["surface"],
        border=ft.Border.all(1, color=theme["border"]),
        border_radius=12,
        padding=ft.Padding.all(20),
        content=ft.Column(
            spacing=16,
            controls=[
                # Developer info row
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Container(
                                    width=36,
                                    height=36,
                                    border_radius=8,
                                    bgcolor=theme["card"],
                                    border=ft.Border.all(1, color=theme["border"]),
                                    alignment=ft.Alignment.CENTER,
                                    content=ft.Icon(
                                        ft.Icons.CODE_ROUNDED,
                                        size=18,
                                        color=theme["btn_primary"],
                                    ),
                                ),
                                ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(
                                            "Made with ❤️ by Jaydeep Patil",
                                            size=14,
                                            weight=ft.FontWeight.BOLD,
                                            color=theme["text_primary"],
                                        ),
                                        ft.Text(
                                            "Creator & Developer",
                                            size=11,
                                            color=theme["text_muted"]
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        discord_id_pill,
                    ],
                ),
                ft.Divider(height=1, color=theme["border"]),
                # Connect & Support links row
                ft.Row(
                    spacing=12,
                    controls=[
                        # Discord Server item
                        ft.Container(
                            expand=True,
                            bgcolor=theme["card"],
                            border=ft.Border.all(1, color=theme["border"]),
                            border_radius=10,
                            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Row(
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.DISCORD,
                                                size=20,
                                                color=theme["btn_primary"],
                                            ),
                                            ft.Column(
                                                spacing=1,
                                                controls=[
                                                    ft.Text(
                                                        "Discord Community",
                                                        size=13,
                                                        weight=ft.FontWeight.BOLD,
                                                        color=theme["text_primary"],
                                                    ),
                                                    ft.Text(
                                                        "Discord community",
                                                        size=11,
                                                        color=theme["text_muted"],
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.Row(
                                        spacing=4,
                                        tight=True,
                                        controls=[
                                            ft.Button(
                                                "Join",
                                                icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                                                bgcolor=theme["btn_primary"],
                                                color=theme["btn_primary_text"],
                                                style=rounded_button_style,
                                                on_click=lambda e: open_url(
                                                    "https://dsc.gg/_gr8",
                                                    "Opening the Wisc Discord community",
                                                ),
                                            ),
                                            ft.IconButton(
                                                icon=ft.Icons.CONTENT_COPY_ROUNDED,
                                                icon_size=16,
                                                icon_color=theme["text_secondary"],
                                                hover_color=theme["card_hover"],
                                                tooltip=tooltip("Copy invite link"),
                                                style=rounded_button_style,
                                                on_click=lambda e: copy_to_clipboard(
                                                    "https://dsc.gg/_gr8",
                                                    "Copied the Discord community invite",
                                                ),
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        # Buy Me a Coffee item
                        ft.Container(
                            expand=True,
                            bgcolor=theme["card"],
                            border=ft.Border.all(1, color=theme["border"]),
                            border_radius=10,
                            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                            content=ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                controls=[
                                    ft.Row(
                                        spacing=10,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Icon(
                                                ft.Icons.COFFEE_ROUNDED,
                                                size=20,
                                                color=theme["btn_primary"],
                                            ),
                                            ft.Column(
                                                spacing=1,
                                                controls=[
                                                    ft.Text(
                                                        "Buy Me a Coffee",
                                                        size=13,
                                                        weight=ft.FontWeight.BOLD,
                                                        color=theme["text_primary"],
                                                    ),
                                                    ft.Text(
                                                        "buymeacoffee.com/jaydeeeep",
                                                        size=11,
                                                        color=theme["text_muted"],
                                                    ),
                                                ],
                                            ),
                                        ],
                                    ),
                                    ft.Row(
                                        spacing=4,
                                        tight=True,
                                        controls=[
                                            ft.Button(
                                                "Support",
                                                icon=ft.Icons.FAVORITE_ROUNDED,
                                                bgcolor=theme["btn_secondary"],
                                                color=theme["btn_secondary_text"],
                                                style=rounded_button_style,
                                                on_click=lambda e: open_url(
                                                    "https://buymeacoffee.com/jaydeeeep",
                                                    "Opening Buy Me a Coffee...",
                                                ),
                                            ),
                                            ft.IconButton(
                                                icon=ft.Icons.CONTENT_COPY_ROUNDED,
                                                icon_size=16,
                                                icon_color=theme["text_secondary"],
                                                hover_color=theme["card_hover"],
                                                tooltip=tooltip("Copy donation link"),
                                                style=rounded_button_style,
                                                on_click=lambda e: copy_to_clipboard(
                                                    "https://buymeacoffee.com/jaydeeeep",
                                                    "Copied donation link to clipboard!",
                                                ),
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            ],
        ),
    )
    creator_social_card.on_hover = lambda e, c=creator_social_card: on_card_hover(e, c, theme["surface"])

    # 3. Game Directory & Specs Card (Clean, minimal)
    storage_specs_card = glass_panel(
        bgcolor=theme["surface"],
        border=ft.Border.all(1, color=theme["border"]),
        border_radius=12,
        padding=ft.Padding.all(20),
        content=ft.Column(
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.START,
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
                                    ft.Icons.FOLDER_OPEN_OUTLINED,
                                    size=16,
                                    color=theme["btn_primary"],
                                ),
                                ft.Text(
                                    "Game Directory",
                                    size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=theme["text_primary"],
                                ),
                            ],
                        ),
                        ft.Text(
                            f"Palette: {selected_theme['name']}  •  RAM: {settings.get('ram_mb', 4096)} MB",
                            size=11,
                            color=theme["text_muted"],
                        ),
                    ],
                ),
                ft.Container(
                    bgcolor=theme["card"],
                    border=ft.Border.all(1, color=theme["border"]),
                    border_radius=8,
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(
                                str(minecraft_directory),
                                size=12,
                                color=theme["text_secondary"],
                                selectable=True,
                                expand=True,
                            ),
                            ft.Row(
                                spacing=6,
                                tight=True,
                                controls=[
                                    ft.Button(
                                        "Open Folder",
                                        icon=ft.Icons.FOLDER_ROUNDED,
                                        bgcolor=theme["btn_secondary"],
                                        color=theme["btn_secondary_text"],
                                        style=rounded_button_style,
                                        on_click=lambda e: open_system_folder(
                                            minecraft_directory
                                        ),
                                    ),
                                    ft.IconButton(
                                        icon=ft.Icons.CONTENT_COPY_ROUNDED,
                                        icon_size=16,
                                        icon_color=theme["text_secondary"],
                                        hover_color=theme["card_hover"],
                                        tooltip=tooltip("Copy path"),
                                        style=rounded_button_style,
                                        on_click=lambda e: copy_to_clipboard(
                                            str(minecraft_directory),
                                            "Copied game data path to clipboard!",
                                        ),
                                    ),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )
    storage_specs_card.on_hover = lambda e, c=storage_specs_card: on_card_hover(e, c, theme["surface"])

    about_subpage = build_settings_page(
        "About",
        [
            about_hero_card,
            creator_social_card,
            storage_specs_card,
        ],
    )

    updates_subpage = build_settings_page("Updates", [features.updater.build_section(
        lambda title, description, control: build_setting_container(title, description, control=control))]) if features else ft.Container()

    return {
        "options": options_dashboard,
        "options_ui": ui_subpage,
        "options_java": java_subpage,
        "options_game": game_subpage,
        "options_accounts": accounts_subpage,
        "options_launcher": launcher_subpage,
        "options_about": about_subpage,
        "options_updates": updates_subpage,
    }
