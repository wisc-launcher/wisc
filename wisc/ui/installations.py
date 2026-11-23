"""
Installation Editor and Profiles Management for Wisc.
"""

from pathlib import Path
import re
import threading
import uuid
import tkinter as tk
from tkinter import filedialog
import flet as ft
from wisc.ui.controls import LegacySelector, SimpleInput, launcher_back_button, launcher_button
from wisc.ui.profile_assets import ProfileIconField, PROFILE_ICON_OPTIONS, profile_icon
from wisc.ui.scroll_views import ScrollColumn
from wisc.ui.glass import glass_panel
from wisc.services.launcher import get_mod_loader, minecraft_directory, get_profile_version_id
from wisc.core.storage import save_installations
from wisc.services import banners
from wisc.services import profiles as profile_creation
from wisc.core import storage
from wisc.ui.components import (
    rounded_button_style,
    clickable_mouse_cursor,
    tooltip,
    build_themed_switch,
    build_themed_alert_dialog,
)


def build_installation_editor(
    profile=None,
    name_only=False,
    *,
    page: ft.Page,
    theme: dict,
    settings: dict,
    installations: list,
    handled_external_profile_ids: set,
    latest_release_id: str,
    version_catalog: list,
    loader_catalog_cache: dict,
    navigate,
    notify,
    online_available=True,
    show_dialog_with_blur=None,
    close_dialog_with_blur=None,
    features=None,
):
    if show_dialog_with_blur is None:
        def show_dialog_with_blur(dlg):
            page.show_dialog(dlg)
            page.update()

    if close_dialog_with_blur is None:
        def close_dialog_with_blur(dlg):
            dlg.open = False
            page.update()

    existing_profile = profile or {}
    loader_names = ["Vanilla", "Fabric", "Forge", "Quilt", "NeoForge"]
    initial_loader = existing_profile.get("loader", "Vanilla")
    if initial_loader not in loader_names:
        initial_loader = "Vanilla"

    installation_name_is_default = {
        "value": not bool((existing_profile.get("name") or "").strip())
    }
    name_field = SimpleInput(
        label="Profile Name",
        value=existing_profile.get("name", ""),
        hint_text="Defaults to the selected version",
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
        cursor_color=theme["btn_primary"],
        fill_color=theme["card"],
        border_radius=5,
        expand=True,
        on_change=lambda e: installation_name_is_default.update(
            value=False
        ),
    )
    jvm_arguments_field = SimpleInput(
        label='Extra Java arguments', value=existing_profile.get('jvm_arguments', ''),
        hint_text='e.g. -Xmx4G -XX:+UseG1GC', color=theme['text_primary'],
        border_color=theme['border'], focused_border_color=theme['btn_primary'])
    icon_field = ProfileIconField(page, existing_profile, file_picker=getattr(features, "file_picker", None), notify=notify)
    loader_field = LegacySelector(
        label="Mod loader",
        value=initial_loader,
        options=[
            ft.DropdownOption(key=name, text=name) for name in loader_names
        ],
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
        fill_color=theme["card"],
        border_radius=8,
        expand=True,
    )
    channel_field = LegacySelector(
        label="Version channel",
        value=existing_profile.get("channel", "Release") or "Release",
        options=[
            ft.DropdownOption(key="Release", text="Release"),
            ft.DropdownOption(key="Snapshot", text="Snapshot"),
        ],
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
        fill_color=theme["card"],
        border_radius=8,
        expand=True,
    )

    def get_minecraft_version_ids(loader_name, channel_name):
        if loader_name == "Vanilla":
            version_type = channel_name.casefold()
            return [
                version["id"]
                for version in version_catalog
                if version.get("type") == version_type
            ]

        cache_key = (loader_name.casefold(), "minecraft")
        if cache_key not in loader_catalog_cache:
            try:
                loader_catalog_cache[cache_key] = get_mod_loader(
                    loader_name
                ).get_minecraft_versions(False)
            except Exception:
                loader_catalog_cache[cache_key] = []
        return loader_catalog_cache[cache_key]

    def get_loader_version_ids(loader_name, minecraft_version):
        if not minecraft_version:
            return []
        cache_key = (loader_name.casefold(), minecraft_version)
        if cache_key not in loader_catalog_cache:
            try:
                loader_catalog_cache[cache_key] = get_mod_loader(
                    loader_name
                ).get_loader_versions(minecraft_version, False)
            except Exception:
                loader_catalog_cache[cache_key] = []
        return loader_catalog_cache[cache_key]

    selected_version = existing_profile.get("minecraft_version", "")
    initial_mc_versions = (
        []
        if name_only
        else get_minecraft_version_ids(
            initial_loader,
            channel_field.value or "Release",
        )
    )
    if selected_version and selected_version not in initial_mc_versions:
        initial_mc_versions.insert(0, selected_version)
    version_field = LegacySelector(
        label="Minecraft version",
        value=selected_version
        or (initial_mc_versions[0] if initial_mc_versions else None),
        options=[
            ft.DropdownOption(key=version, text=version)
            for version in initial_mc_versions
        ],
        enable_filter=True,
        on_select=lambda e: update_loader_versions(),
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
        fill_color=theme["card"],
        border_radius=8,
        expand=True,
    )

    def sync_default_installation_name():
        if installation_name_is_default["value"]:
            name_field.value = (version_field.value or "").strip()

    sync_default_installation_name()
    initial_loader_versions = (
        get_loader_version_ids(initial_loader, version_field.value)
        if initial_loader != "Vanilla" and not name_only
        else []
    )
    selected_loader_version = existing_profile.get("loader_version", "")
    if (
        selected_loader_version
        and selected_loader_version not in initial_loader_versions
    ):
        initial_loader_versions.insert(0, selected_loader_version)
    loader_version_field = LegacySelector(
        label="Loader version",
        value=selected_loader_version
        or (initial_loader_versions[0] if initial_loader_versions else None),
        options=[
            ft.DropdownOption(key=version, text=version)
            for version in initial_loader_versions
        ],
        visible=initial_loader != "Vanilla",
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
        fill_color=theme["card"],
        border_radius=8,
        expand=True,
    )
    form_error = ft.Text(color=theme["btn_primary"], visible=False)

    def set_form_error(message):
        form_error.value = message
        form_error.visible = bool(message)
        notify(message, ft.Icons.ERROR_OUTLINE)

    # If editing an existing profile, use its setting; if creating new and loader != Vanilla, default to True
    initial_is_instance = (
        bool(existing_profile.get("is_instance", False))
        if profile is not None
        else (initial_loader != "Vanilla")
    )

    instance_switch_label = (
        "Separate instance (recommended)"
        if initial_loader != "Vanilla"
        else "Separate instance"
    )

    is_instance_switch = build_themed_switch(
        label=instance_switch_label,
        value=initial_is_instance,
        theme=theme,
        on_change=lambda e: toggle_instance_mode(),
    )
    instance_hint = ft.Text(
        "Keep worlds, mods, and settings in their own folder.",
        size=12,
        color=theme["text_secondary"],
    )
    instance_folder_field = SimpleInput(
        label="Instance folder name (optional)",
        value=existing_profile.get("instance_name", ""),
        hint_text="e.g. My_Modded_MC",
        border_color=theme["border"],
        focused_border_color=theme["btn_primary"],
        color=theme["text_primary"],
        label_style=ft.TextStyle(color=theme["text_secondary"], size=13),
        fill_color=theme["card"],
        border_radius=5,
        visible=initial_is_instance,
    )

    def toggle_instance_mode(e=None):
        instance_folder_field.visible = bool(is_instance_switch.value)
        if is_instance_switch.value and not instance_folder_field.value:
            clean_name = re.sub(
                r"[^a-zA-Z0-9_\-]", "_", (name_field.value or "").strip()
            )
            if clean_name:
                instance_folder_field.value = clean_name
        page.update()

    def update_loader_versions(e=None):
        selected_loader = loader_field.value or "Vanilla"
        selected_mc_version = version_field.value or ""
        loader_versions = (
            get_loader_version_ids(selected_loader, selected_mc_version)
            if selected_loader != "Vanilla"
            else []
        )
        current_loader_version = loader_version_field.value
        if (
            current_loader_version
            and current_loader_version not in loader_versions
        ):
            current_loader_version = None
        loader_version_field.options = [
            ft.DropdownOption(key=version, text=version)
            for version in loader_versions
        ]
        loader_version_field.value = current_loader_version or (
            loader_versions[0] if loader_versions else None
        )
        sync_default_installation_name()
        if selected_loader != "Vanilla" and not loader_versions:
            set_form_error(
                "No loader versions found for this Minecraft version."
            )
        elif not form_error.value or form_error.value.startswith(
            "No loader versions"
        ):
            form_error.value = ""
            form_error.visible = False
        if e is not None:
            page.update()

    def update_editor_fields(e=None):
        if name_only:
            return

        selected_loader = loader_field.value or "Vanilla"
        selected_channel = channel_field.value or "Release"
        is_vanilla = selected_loader == "Vanilla"
        channel_field.visible = is_vanilla
        loader_version_field.visible = not is_vanilla
        selected_value = version_field.value or ""
        minecraft_versions = get_minecraft_version_ids(
            selected_loader,
            selected_channel,
        )
        if (
            e is None
            and selected_value
            and selected_value not in minecraft_versions
        ):
            minecraft_versions.insert(0, selected_value)
        version_field.options = [
            ft.DropdownOption(key=version, text=version)
            for version in minecraft_versions
        ]
        if selected_value not in minecraft_versions:
            version_field.value = (
                minecraft_versions[0] if minecraft_versions else None
            )
        sync_default_installation_name()
        if is_vanilla:
            loader_version_field.options = []
            loader_version_field.value = None
            is_instance_switch.label = "Separate instance"
        else:
            is_instance_switch.label = "Separate instance (recommended)"
            if e is not None and not is_instance_switch.value:
                is_instance_switch.value = True
                instance_folder_field.visible = True
                if not instance_folder_field.value:
                    clean_name = re.sub(
                        r"[^a-zA-Z0-9_\-]", "_", (name_field.value or "").strip()
                    )
                    if clean_name:
                        instance_folder_field.value = clean_name
            update_loader_versions()
        if e is not None:
            page.update()

    loader_field.on_select = update_editor_fields
    channel_field.on_select = update_editor_fields
    version_field.on_select = update_loader_versions

    custom_banner_path = {
        "value": existing_profile.get("custom_banner", "")
    }
    banner_preview_image = ft.Image(
        src=custom_banner_path["value"] or "",
        left=0,
        right=0,
        top=0,
        bottom=0,
        height=110,
        fit=ft.BoxFit.COVER,
        border_radius=8,
        visible=bool(custom_banner_path["value"]),
    )
    banner_placeholder = ft.Container(
        left=0,
        right=0,
        top=0,
        bottom=0,
        height=110,
        border_radius=8,
        bgcolor=theme["card"],
        border=ft.Border.all(1, color=theme["border"]),
        alignment=ft.Alignment.CENTER,
        visible=not bool(custom_banner_path["value"]),
        content=ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
            controls=[
                ft.Icon(ft.Icons.IMAGE_OUTLINED, color=theme["text_secondary"], size=28),
                ft.Text("Default game artwork will be used", color=theme["text_secondary"], size=12),
            ],
        ),
    )
    clear_banner_btn = ft.IconButton(
        icon=ft.Icons.CLOSE,
        tooltip=tooltip("Remove custom banner"),
        icon_color=theme["text_secondary"],
        icon_size=18,
        visible=bool(custom_banner_path["value"]),
    )

    def select_banner_file(e=None):
        def _pick():
            try:
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                selected = filedialog.askopenfilename(
                    title="Select Profile Banner Image",
                    filetypes=[
                        ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                        ("All files", "*.*"),
                    ],
                )
                root.destroy()
                if selected and Path(selected).is_file():
                    custom_banner_path["value"] = selected
                    banner_preview_image.src = selected
                    banner_preview_image.visible = True
                    banner_placeholder.visible = False
                    clear_banner_btn.visible = True
                    page.update()
            except Exception:
                pass

        threading.Thread(target=_pick, daemon=True).start()

    def clear_banner(e=None):
        custom_banner_path["value"] = ""
        banner_preview_image.src = ""
        banner_preview_image.visible = False
        banner_placeholder.visible = True
        clear_banner_btn.visible = False
        page.update()

    clear_banner_btn.on_click = clear_banner

    banner_section = ft.Container(
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.Icon(ft.Icons.WALLPAPER, size=18, color=theme["text_primary"]),
                                ft.Text(
                                    "Profile Banner",
                                    weight=ft.FontWeight.BOLD,
                                    size=13,
                                    color=theme["text_primary"],
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=4,
                            controls=[
                                clear_banner_btn,
                                ft.Button(
                                    "Choose Banner...",
                                    icon=ft.Icons.UPLOAD_FILE,
                                    style=rounded_button_style,
                                    bgcolor=theme["card"],
                                    color=theme["text_primary"],
                                    on_click=select_banner_file,
                                ),
                            ],
                        ),
                    ],
                ),
                ft.Stack(
                    height=110,
                    controls=[
                        banner_placeholder,
                        banner_preview_image,
                    ],
                ),
            ],
        ),
    )

    def save_profile(e):
        name = (name_field.value or "").strip()
        final_banner = (custom_banner_path["value"] or "").strip()
        if name_only:
            if not name:
                name = (
                    existing_profile.get("version_id")
                    or existing_profile.get("minecraft_version")
                    or "Minecraft profile"
                )

            saved_profile = dict(existing_profile)
            saved_profile["id"] = saved_profile.get("id", uuid.uuid4().hex)
            saved_profile["name"] = name
            saved_profile["jvm_arguments"] = (jvm_arguments_field.value or "").strip()
            try:
                saved_profile["icon"] = icon_field.saved_value()
            except (OSError, ValueError) as error:
                set_form_error(f"Could not save the profile icon: {error}")
                page.update()
                return
            if final_banner:
                persisted = banners.save_custom_banner_image(saved_profile["id"], final_banner)
                saved_profile["custom_banner"] = persisted or final_banner
            else:
                saved_profile["custom_banner"] = ""
            updated_installations = list(installations)
            existing_index = next(
                (
                    index
                    for index, item in enumerate(updated_installations)
                    if item["id"] == saved_profile["id"]
                ),
                None,
            )
            if existing_index is None:
                updated_installations.append(saved_profile)
            else:
                updated_installations[existing_index] = saved_profile
            if save_installations(updated_installations):
                installations[:] = updated_installations
                navigate("installations")
                return
            set_form_error("Could not save profile data.")
            page.update()
            return

        if not online_available:
            set_form_error(
                "No internet connection. Try creating the profile again when online."
            )
            page.update()
            return

        loader_name = loader_field.value or "Vanilla"
        channel_name = channel_field.value or "Release"
        mc_version = (version_field.value or "").strip()
        mod_version = (loader_version_field.value or "").strip()
        is_instance = bool(is_instance_switch.value)

        if not mc_version:
            set_form_error("Please choose a Minecraft version.")
            page.update()
            return
        if not name:
            name = mc_version
        if loader_name != "Vanilla" and not mod_version:
            set_form_error("Please choose a loader version.")
            page.update()
            return

        profile_id = existing_profile.get("id", uuid.uuid4().hex)
        target_version_id = (
            mc_version
            if loader_name == "Vanilla"
            else get_mod_loader(loader_name).get_installed_version(
                mc_version, mod_version
            )
        )

        # Validation: Prevent duplicate default/shared configurations for the same version
        if not is_instance:
            conflicting_profile = next(
                (
                    item
                    for item in installations
                    if item["id"] != profile_id
                    and not item.get("is_instance")
                    and get_profile_version_id(item) == target_version_id
                ),
                None,
            )
            if conflicting_profile:
                notify(
                    f"{target_version_id} already has a configured profile.",
                    ft.Icons.INFO_OUTLINE,
                )

                def close_already_installed_dialog(dlg):
                    close_dialog_with_blur(dlg)

                def enable_instance_mode(dlg):
                    close_dialog_with_blur(dlg)
                    is_instance_switch.value = True
                    instance_folder_field.visible = True
                    if not instance_folder_field.value:
                        instance_folder_field.value = re.sub(
                            r"[^a-zA-Z0-9_\-]", "_", name
                        )
                    form_error.value = ""
                    form_error.visible = False
                    page.update()

                already_installed_dialog = build_themed_alert_dialog(
                    theme=theme,
                    title=ft.Row(
                        spacing=8,
                        controls=[
                            ft.Icon(
                                ft.Icons.INFO_OUTLINED,
                                color=theme["btn_primary"],
                                size=22,
                            ),
                            ft.Text(
                                "This version is already installed",
                                weight=ft.FontWeight.BOLD,
                                color=theme["text_primary"],
                            ),
                        ],
                    ),
                    content=ft.Text(
                        f"A profile for '{target_version_id}' is already configured in Wisc ('{conflicting_profile['name']}').\n\n"
                        "Creating another standard configuration for the same version will just launch into the same shared environment.\n\n"
                        "To create a new environment with separate worlds, texture packs, and settings, make it a Separate Instance.",
                        color=theme["text_primary"],
                        size=14,
                    ),
                    actions=[
                        ft.TextButton(
                            "Cancel",
                            style=ft.ButtonStyle(
                                color=theme["text_secondary"],
                                mouse_cursor=clickable_mouse_cursor,
                            ),
                            on_click=lambda e: close_already_installed_dialog(
                                already_installed_dialog
                            ),
                        ),
                        ft.Button(
                            "Make Instance",
                            bgcolor=theme["btn_primary"],
                            color=theme["btn_primary_text"],
                            style=rounded_button_style,
                            on_click=lambda e: enable_instance_mode(
                                already_installed_dialog
                            ),
                        ),
                    ],
                    on_dismiss=lambda e: close_already_installed_dialog(
                        already_installed_dialog
                    ),
                )
                show_dialog_with_blur(already_installed_dialog)
                return

        instance_folder_name = ""
        game_dir = ""
        if is_instance:
            try:
                folder = profile_creation.new_instance_directory(
                    minecraft_directory, instance_folder_field.value, name, storage.load_installations())
            except (OSError, ValueError) as error:
                set_form_error(str(error))
                page.update()
                return
            instance_folder_name = folder.name
            game_dir = str(folder)

        saved_custom_banner = ""
        if final_banner:
            persisted = banners.save_custom_banner_image(profile_id, final_banner)
            saved_custom_banner = persisted or final_banner

        saved_profile = {
            "id": profile_id,
            "name": name,
            "loader": loader_name,
            "channel": channel_name if loader_name == "Vanilla" else "",
            "minecraft_version": mc_version,
            "loader_version": (
                mod_version if loader_name != "Vanilla" else ""
            ),
            "version_id": target_version_id,
            "is_instance": is_instance,
            "instance_name": instance_folder_name,
            "game_directory": game_dir,
            "custom_banner": saved_custom_banner,
        }
        saved_profile['jvm_arguments'] = (jvm_arguments_field.value or '').strip()
        try:
            saved_profile['icon'] = icon_field.saved_value()
        except (OSError, ValueError) as error:
            set_form_error(f"Could not save the profile icon: {error}")
            page.update()
            return
        try:
            profile_creation.save_new_profile(saved_profile, minecraft_directory, instance_folder_field.value, storage)
        except (OSError, ValueError) as error:
            set_form_error(str(error))
            page.update()
            return
        installations[:] = storage.load_installations()
        notify(f"Created {name}.", ft.Icons.CHECK_CIRCLE)
        navigate('installations')

    update_editor_fields()

    icon_tiles: dict[str, ft.Button] = {}

    def refresh_icon_selection() -> None:
        for source, tile in icon_tiles.items():
            selected = source == icon_field.value
            tile.style.side = ft.BorderSide(
                1, theme["btn_primary"] if selected else theme["border"],
            )
            tile.style.bgcolor = {
                ft.ControlState.DEFAULT: (
                    ft.Colors.with_opacity(0.16, theme["btn_primary"])
                    if selected else theme["card"]
                ),
                ft.ControlState.HOVERED: theme["card_hover"],
            }
        try:
            icon_choices.update()
        except RuntimeError:
            pass

    def select_icon(source: str) -> None:
        icon_field.selector.value = source
        icon_field._changed()
        page.update()

    for source, label in PROFILE_ICON_OPTIONS:
        tile = launcher_button(
            label, lambda e, source=source: select_icon(source),
            width=40, height=40, tooltip=tooltip(label),
        )
        tile.content = profile_icon({"icon": source}, size=28)
        tile.style.padding = 0
        icon_tiles[source] = tile
    tiles = list(icon_tiles.values())
    icon_choices = ft.Column(
        [ft.Row(tiles[:8], spacing=8, run_spacing=8, wrap=True),
         ft.Row(tiles[8:], spacing=8, run_spacing=8, wrap=True)],
        spacing=8,
    )
    icon_field.on_change = refresh_icon_selection
    refresh_icon_selection()

    advanced_settings = ft.ExpansionTile(
        title=ft.Text("Java arguments", size=13, color=theme["text_primary"]),
        dense=True,
        min_tile_height=48,
        expanded=bool(existing_profile.get("jvm_arguments")),
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
        maintain_state=True,
        tile_padding=ft.Padding.symmetric(horizontal=12),
        controls_padding=ft.Padding.only(left=12, right=12, bottom=12),
        icon_color=theme["text_secondary"],
        collapsed_icon_color=theme["text_secondary"],
        shape=ft.RoundedRectangleBorder(radius=8),
        collapsed_shape=ft.RoundedRectangleBorder(radius=8),
        controls=[jvm_arguments_field],
    )

    form = ScrollColumn(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=12,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        controls=[
            name_field,
            ft.Container(loader_field, visible=not name_only),
            ft.Row(
                [version_field, channel_field, loader_version_field],
                spacing=12, visible=not name_only,
            ),
            ft.Container(
                visible=not name_only,
                bgcolor=theme["card"],
                border_radius=8,
                padding=12,
                content=ft.Column(
                    [is_instance_switch, instance_hint, instance_folder_field],
                    spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ),
            advanced_settings,
        ],
    )
    save_button = ft.Button(
        "Save Profile", on_click=save_profile, height=40,
        style=launcher_button("Save Profile", None, primary=True).style,
    )
    editor_card = glass_panel(
        expand=6,
        padding=20,
        bgcolor=theme["surface"],
        border=ft.Border.all(1, theme["border"]),
        border_radius=12,
        content=ft.Column(
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                form,
                form_error,
                ft.Row(
                    [launcher_button("Cancel", lambda e: navigate("installations"), height=40),
                     save_button],
                    alignment=ft.MainAxisAlignment.END, spacing=8,
                ),
            ],
        ),
    )
    appearance_card = glass_panel(
        expand=5,
        padding=20,
        bgcolor=theme["surface"],
        border=ft.Border.all(1, theme["border"]),
        border_radius=12,
        content=ScrollColumn(
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            spacing=16,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Text("Appearance", size=16, weight=ft.FontWeight.W_600,
                        color=theme["text_primary"]),
                icon_field,
                icon_choices,
                ft.Divider(height=1, color=theme["border"]),
                banner_section,
            ],
        ),
    )
    editor = ft.Container(
        expand=True,
        padding=ft.Padding.only(left=28, top=20, right=28, bottom=20),
        content=ft.Column(
            spacing=20,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            controls=[
                ft.Row(
                    [ft.Text("Edit Profile" if profile else "New Profile", size=24,
                             weight=ft.FontWeight.BOLD, color=theme["text_primary"], expand=True),
                     launcher_back_button(lambda e: navigate("installations"), label="Profiles")],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row([editor_card, appearance_card], expand=True, spacing=20,
                       vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ],
        ),
    )
    editor.data = {"reveal_controls": [editor_card, appearance_card]}
    return editor
