"""The classic profile manager using shared rows and retained profile ordering."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import flet as ft

from wisc.ui import theme
from wisc.core import state
from wisc.core import storage
from wisc.core.storage import save_installations, save_profile_options
from wisc.services.instances import remove_installed_version, remove_profile_record
from wisc.ui.components import clickable_mouse_cursor, rounded_button_style, tooltip
from wisc.services.launcher import get_profile_version_id
from wisc.ui.controls import launcher_button, launcher_icon_button
from wisc.ui.profile_assets import profile_badges, profile_icon, profile_summary
from wisc.ui.profiles import ProfileList, profile_drag_region, profile_list_surface, profile_row
from wisc.ui.glass import glass_panel

if TYPE_CHECKING:
    from wisc.ui.features import LegacyFeatures


class ClassicLibraryPage(ft.Container):
    def __init__(self, *, on_new: Callable, on_play: Callable, on_mods: Callable,
                 on_edit: Callable, on_remove: Callable, on_repair: Callable,
                 on_folder: Callable, on_move: Callable, on_order: Callable,
                 busy: Callable[[], bool]):
        self._busy = busy
        self._on_play = on_play
        self._on_mods = on_mods
        self._on_edit = on_edit
        self._on_remove = on_remove
        self._on_repair = on_repair
        self._on_folder = on_folder
        self._on_move = on_move
        self.list_view = ProfileList(on_order_changed=on_order)
        self.summary = ft.Text(size=12, color=theme.MUTED)
        self.new_button = launcher_button("New Profile", on_new, primary=True, icon=ft.Icons.ADD, height=38)
        self.header = ft.Row([
            ft.Text("Profiles", size=24, weight=ft.FontWeight.BOLD, color=theme.TEXT),
            ft.Container(expand=True), self.new_button,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        super().__init__(
            expand=True, padding=ft.Padding(left=28, top=20, right=28, bottom=20),
            content=ft.Column([self.header, self.summary, profile_list_surface(self.list_view)],
                              expand=True, spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        )

    def refresh(self, profiles: list[dict], installed_ids: set[str], selected_id: str,
                *, footer: tuple[ft.Control, ...] | list[ft.Control] = ()) -> None:
        busy = self._busy()
        self.new_button.disabled = busy
        installed = sum(get_profile_version_id(profile) in installed_ids for profile in profiles)
        self.summary.value = f"{len(profiles)} {'profile' if len(profiles) == 1 else 'profiles'} · {installed} installed"
        cards = []
        for profile in profiles:
            pid = profile["id"]
            ready = get_profile_version_id(profile) in installed_ids

            def body(icon, info, profile_id=pid):
                region = profile_drag_region(icon, info, color=theme.MUTED,
                                             view=self.list_view, profile_id=profile_id)
                region.controls[0].ignore_interactions = busy
                region.controls[0].mouse_cursor = ft.MouseCursor.BASIC if busy else ft.MouseCursor.GRAB
                return region

            badges = profile_badges(profile)
            if not ready:
                badges.append(ft.Container(
                    content=ft.Text("Not installed", size=10, color=theme.MUTED),
                    bgcolor=theme.SURFACE_STRONG, border_radius=5,
                    padding=ft.Padding.symmetric(horizontal=7, vertical=2),
                ))
            surface = profile_row(
                profile, icon=profile_icon(profile), badges=badges, details=profile_summary(profile),
                glow_color=theme.ACCENT, body_builder=body,
                actions=[
                    launcher_icon_button(icon=ft.Icons.PLAY_ARROW_ROUNDED, icon_color=theme.ACCENT,
                        tooltip=f"Play {profile['name']}" if ready else f"Install and play {profile['name']}",
                        on_click=lambda e, item=profile: self._on_play(item), disabled=busy),
                    launcher_icon_button(icon=ft.Icons.EXTENSION_OUTLINED, tooltip=f"Manage mods for {profile['name']}",
                        on_click=lambda e, profile_id=pid: self._on_mods(profile_id)),
                    launcher_icon_button(icon=ft.Icons.FOLDER_OPEN_OUTLINED, tooltip="Open game directory",
                        on_click=lambda e, item=profile: self._on_folder(item)),
                    launcher_icon_button(icon=ft.Icons.EDIT_OUTLINED, tooltip=f"Edit {profile['name']}",
                        on_click=lambda e, profile_id=pid: self._on_edit(profile_id), disabled=busy),
                    self._menu(profile, busy),
                ],
            )
            surface.foreground_decoration = None
            cards.append(ft.Container(
                key=ft.ValueKey(f"library-profile-{pid}"), data=pid, content=surface,
                border=ft.Border.all(0, theme.TRANSPARENT), border_radius=12,
                scale=1.0,
                margin=ft.Margin.only(bottom=8),
            ))
        extras = list(footer)
        if not cards:
            extras.insert(0, glass_panel(
                padding=24, bgcolor=theme.SURFACE, border_radius=12, border=ft.Border.all(1, theme.BORDER),
                content=ft.Text("No profiles yet. Create a profile to get started.", size=13, color=theme.MUTED),
            ))
        self.list_view.set_cards(cards, footer=ft.Column(extras, spacing=14) if extras else None, update=False)

    def _menu(self, profile: dict, busy: bool) -> ft.PopupMenuButton:
        def item(label: str, icon, callback: Callable) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(
                content=ft.Row([ft.Icon(icon, size=18, color=theme.MUTED),
                                ft.Text(label, size=13, color=theme.TEXT)], spacing=10),
                on_click=callback,
            )
        return ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ, icon_color=theme.MUTED, tooltip=f"More actions for {profile['name']}",
            width=36, height=36, disabled=busy, bgcolor=theme.SURFACE,
            shape=ft.RoundedRectangleBorder(radius=8),
            items=[
                item("Move up", ft.Icons.ARROW_UPWARD, lambda e: self._on_move(profile["id"], -1)),
                item("Move down", ft.Icons.ARROW_DOWNWARD, lambda e: self._on_move(profile["id"], 1)),
                item("Repair Minecraft files", ft.Icons.BUILD_OUTLINED, lambda e: self._on_repair(profile)),
                item("Remove profile", ft.Icons.DELETE_OUTLINE, lambda e: self._on_remove(profile["id"])),
            ],
        )

    def leave(self) -> None:
        self.list_view.cancel_drag()


def build_library_view(*, page: ft.Page, app_theme: dict, features: LegacyFeatures,
                       installations: list[dict], installed_versions: list[dict],
                       handled_external_profile_ids: set[str], latest_release_id: str | None,
                       navigate: Callable, notify: Callable, is_active_launch_version: Callable,
                       build_alert_dialog: Callable, show_dialog_with_blur: Callable,
                       close_dialog_with_blur: Callable) -> ClassicLibraryPage:
    """Build profile rows and raw-version management only when Library is opened."""
    theme = app_theme
    launch_selection = state.launch_selection
    player_name_state = state.player_name_state
    profile_picture_state = state.profile_picture_state
    danger_zone_state = state.danger_zone_state
    def confirm_delete(profile_id):
        profile = next((item for item in installations if item['id'] == profile_id), None)
        if profile is None or features.busy:
            notify('Wait for the current operation to finish.', 'warning')
            return
        delete_files = ft.Checkbox(label="Also permanently delete this instance's game files",
                                  value=False, visible=bool(profile.get('is_instance')))
        dialog = build_alert_dialog(
            title=ft.Text('Remove profile?', color=theme['text_primary']),
            content=ft.Column([
                ft.Text(f"Remove {profile['name']} from the launcher? Minecraft files are preserved by default.",
                        color=theme['text_secondary']), delete_files], tight=True),
            actions=[ft.TextButton('Cancel', on_click=lambda e: close_delete_dialog(dialog)),
                     ft.Button('Remove', on_click=lambda e: delete_profile(profile_id, dialog, delete_files.value))])
        show_dialog_with_blur(dialog)

    def confirm_delete_installed_version(version_id):
        if is_active_launch_version(version_id):
            notify("This version is busy installing or launching.", ft.Icons.INFO_OUTLINE)
            return
        dialog = build_alert_dialog(
            title=ft.Text(
                "Delete installed version?",
                color=theme["btn_primary"],
                weight=ft.FontWeight.BOLD,
            ),
            content=ft.Text(
                f"Permanently remove '{version_id}' from Minecraft and its launcher profile?",
                color=theme["text_primary"],
            ),
            actions=[
                ft.TextButton(
                    "Cancel",
                    on_click=lambda e: close_delete_dialog(dialog),
                    style=ft.ButtonStyle(
                        color=theme["text_secondary"],
                        mouse_cursor=clickable_mouse_cursor,
                    ),
                ),
                ft.Button(
                    "Delete version",
                    bgcolor=theme["btn_primary"],
                    color=theme["btn_primary_text"],
                    style=rounded_button_style,
                    on_click=lambda e: delete_installed_version(
                        version_id, dialog
                    ),
                ),
            ],
        )
        show_dialog_with_blur(dialog)

    def show_unconfigured_version_info(version_id):
        dialog = build_alert_dialog(
            title=ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(ft.Icons.INFO_OUTLINE, color=theme["btn_primary"], size=22),
                    ft.Text("Unconfigured Version", color=theme["text_primary"], weight=ft.FontWeight.BOLD),
                ],
            ),
            content=ft.Column(
                spacing=8,
                tight=True,
                controls=[
                    ft.Text(
                        f"'{version_id}' is saved on your disk in Minecraft's versions folder, but is not configured as a profile in the launcher.",
                        size=13,
                        color=theme["text_primary"],
                    ),
                    ft.Text(
                        "• To add this version to your launcher, click the '+' button on the right.\n"
                        "• To permanently delete this version from your disk, click the delete (trash) button on the right.",
                        size=12,
                        color=theme["text_secondary"],
                    ),
                ],
            ),
            actions=[
                ft.Button(
                    "Got it",
                    bgcolor=theme["btn_primary"],
                    color=theme["btn_primary_text"],
                    style=rounded_button_style,
                    on_click=lambda e: close_delete_dialog(dialog),
                ),
            ],
        )
        show_dialog_with_blur(dialog)

    def delete_installed_version(version_id, dialog):
        matching_ids = {
            item["id"]
            for item in installations
            if get_profile_version_id(item) == version_id
        }
        updated_installations = [
            item for item in installations if item["id"] not in matching_ids
        ]
        if not save_installations(
            updated_installations,
            handled_external_profile_ids,
            latest_release_id,
        ):
            dialog.content = ft.Text("Could not update Launcher profiles.")
            page.update()
            return
        if not remove_installed_version(version_id):
            save_installations(
                installations, handled_external_profile_ids, latest_release_id
            )
            dialog.content = ft.Text(
                "Could not delete the Minecraft version or update its launcher profile."
            )
            page.update()
            return

        installations[:] = updated_installations
        if launch_selection["key"] in matching_ids:
            launch_selection["key"] = (
                "latest-release" if latest_release_id else ""
            )
            save_profile_options(
                player_name_state["value"],
                launch_selection["key"],
                profile_picture_state["path"],
            )
        close_dialog_with_blur(dialog)
        navigate("installations", force=True)
        notify(f"Deleted Minecraft version {version_id}.", ft.Icons.DELETE_OUTLINE)

    def close_delete_dialog(dialog):
        close_dialog_with_blur(dialog)

    def delete_profile(profile_id, dialog, delete_files=False):
        if features.busy:
            notify('Wait for the current operation to finish.', 'warning')
            return
        try:
            removed = remove_profile_record(profile_id, delete_files=bool(delete_files))
        except (OSError, ValueError) as error:
            notify(error, 'error', 'Could not remove profile')
            return
        installations[:] = storage.load_installations()
        handled_external_profile_ids.clear()
        handled_external_profile_ids.update(storage.load_handled_external_profile_ids())
        if launch_selection['key'] == profile_id:
            launch_selection['key'] = 'latest-release' if latest_release_id else ''
            save_profile_options(player_name_state['value'], launch_selection['key'], profile_picture_state['path'])
        close_dialog_with_blur(dialog)
        navigate('installations', force=True)
        notify(f"Removed {removed['name']}.", 'success')

    # Installed configurations vs unconfigured local versions
    configured_version_ids = {
        get_profile_version_id(p) for p in installations
    }
    unconfigured_versions = [
        v
        for v in installed_versions
        if v["version_id"] not in configured_version_ids
    ]

    unconfigured_rows = []
    for idx, version in enumerate(unconfigured_versions):
        is_last = idx == len(unconfigured_versions) - 1
        row_controls = [
            ft.Icon(
                ft.Icons.WARNING_AMBER_ROUNDED,
                color=ft.Colors.ORANGE_400,
                size=24,
            ),
            ft.Column(
                spacing=2,
                controls=[
                    ft.Row(
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Text(
                                version["version_id"],
                                size=14,
                                weight=ft.FontWeight.W_500,
                                color=theme["text_primary"],
                            ),
                            ft.Container(
                                content=ft.Text(
                                    "RAW VERSION",
                                    size=9,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.ORANGE_300,
                                ),
                                bgcolor=ft.Colors.with_opacity(
                                    0.14, ft.Colors.ORANGE_400
                                ),
                                padding=ft.Padding.symmetric(
                                    horizontal=5, vertical=1
                                ),
                                border_radius=4,
                            ),
                        ],
                    ),
                    ft.Text(
                        profile_summary(version),
                        size=12,
                        color=theme["text_secondary"],
                    ),
                ],
                expand=True,
            ),
            ft.IconButton(
                icon=ft.Icons.INFO_OUTLINE,
                icon_size=15,
                tooltip=tooltip(f"About unconfigured version {version['version_id']}"),
                icon_color=theme["text_muted"],
                style=rounded_button_style,
                hover_color=ft.Colors.TRANSPARENT,
                on_click=lambda e, vid=version[
                    "version_id"
                ]: show_unconfigured_version_info(vid),
            ),
            ft.IconButton(
                icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                tooltip=tooltip(f"Configure {version['version_id']} as a profile"),
                icon_color=theme["btn_primary"],
                style=rounded_button_style,
                disabled=is_active_launch_version(version["version_id"]),
                on_click=lambda e, selected_version=version: navigate(
                    "configure_installed", selected_version["version_id"]
                ),
            ),
            ft.IconButton(
                icon=ft.Icons.DELETE_FOREVER,
                tooltip=tooltip(f"Permanently delete {version['version_id']} from Minecraft"),
                icon_color=ft.Colors.RED_400,
                style=rounded_button_style,
                disabled=is_active_launch_version(version["version_id"]),
                on_click=lambda e, version_id=version[
                    "version_id"
                ]: confirm_delete_installed_version(version_id),
            ),
        ]
        unconfigured_rows.append(
            ft.Container(
                padding=ft.Padding.symmetric(vertical=12, horizontal=16),
                border=None if is_last else ft.Border.only(
                    bottom=ft.BorderSide(1, color=theme["border"])
                ),
                content=ft.Row(
                    controls=row_controls,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            )
        )

    danger_zone_controls = []
    if unconfigured_rows:
        danger_zone_content = ft.Column(
            visible=danger_zone_state["expanded"],
            spacing=8,
            controls=[
                ft.Text(
                    "These raw version folders were detected on your disk in Minecraft's versions directory, but are not configured into Wisc profiles. Deleting a version here permanently removes its core jar and json files from your disk.",
                    size=11,
                    color=theme["text_muted"],
                ),
                glass_panel(
                    bgcolor=theme["surface"],
                    border=ft.Border.all(
                        1,
                        color=theme["border"],
                    ),
                    border_radius=12,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    content=ft.Column(
                        spacing=0,
                        controls=unconfigured_rows,
                    ),
                ),
            ],
        )

        danger_chevron = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_UP_ROUNDED
            if danger_zone_state["expanded"]
            else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED,
            color=theme["text_secondary"],
            size=20,
        )

        danger_count_badge = ft.Container(
            content=ft.Text(
                f"{len(unconfigured_rows)} raw {'version' if len(unconfigured_rows) == 1 else 'versions'}",
                size=10,
                weight=ft.FontWeight.W_500,
                color=theme["text_secondary"],
            ),
            bgcolor=theme["card"],
            border=ft.Border.all(
                1,
                color=theme["border"],
            ),
            padding=ft.Padding.symmetric(horizontal=7, vertical=2),
            border_radius=5,
        )

        def toggle_danger_zone(e):
            danger_zone_state["expanded"] = not danger_zone_state["expanded"]
            danger_zone_content.visible = danger_zone_state["expanded"]
            danger_chevron.icon = (
                ft.Icons.KEYBOARD_ARROW_UP_ROUNDED
                if danger_zone_state["expanded"]
                else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED
            )
            page.update()

        danger_zone_header = glass_panel(
            bgcolor=theme["surface"],
            border=ft.Border.all(
                1,
                color=theme["border"],
            ),
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=14, vertical=12),
            ink=True,
            on_click=toggle_danger_zone,
            tooltip=tooltip("Click to expand or collapse unconfigured raw versions"),
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Row(
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(
                                ft.Icons.UNARCHIVE_ROUNDED,
                                color=theme["text_secondary"],
                                size=20,
                            ),
                            ft.Column(
                                spacing=2,
                                tight=True,
                                controls=[
                                    ft.Row(
                                        spacing=8,
                                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                        controls=[
                                            ft.Text(
                                                "UNCONFIGURED RAW VERSIONS",
                                                size=12,
                                                color=theme["text_primary"],
                                                weight=ft.FontWeight.BOLD,
                                            ),
                                            danger_count_badge,
                                        ],
                                    ),
                                    ft.Text(
                                        "Hidden by default. Click to expand and manage unconfigured version folders on disk.",
                                        size=11,
                                        color=theme["text_muted"],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    danger_chevron,
                ],
            ),
        )

        def on_danger_header_hover(e):
            is_h = e.data == "true"
            danger_zone_header.bgcolor = (
                theme.get("card_hover", theme["card"])
                if is_h
                else theme["surface"]
            )
            danger_zone_header.border = ft.Border.all(
                1,
                color=theme["btn_primary"] if is_h else theme["border"],
            )
            danger_zone_header.update()

        danger_zone_header.on_hover = on_danger_header_hover

        danger_zone_controls = [
            ft.Container(
                margin=ft.Margin.only(top=16),
                content=ft.Column(
                    spacing=10,
                    tight=True,
                    controls=[
                        ft.GestureDetector(
                            mouse_cursor=ft.MouseCursor.CLICK,
                            content=danger_zone_header,
                        ),
                        danger_zone_content,
                    ],
                ),
            )
        ]


    if features.library is None:
        features.library = ClassicLibraryPage(
            on_new=lambda e: navigate("new_installation"), on_play=features.play_profile,
            on_mods=lambda pid: navigate("mods", pid),
            on_edit=lambda pid: navigate("edit_installation", pid), on_remove=confirm_delete,
            on_repair=lambda profile: page.run_task(features.repair_profile, profile),
            on_folder=features.open_profile_folder, on_move=features.move_profile,
            on_order=features.reorder_profiles, busy=lambda: features.busy,
        )
    features.library.refresh(installations, {version["version_id"] for version in installed_versions},
                             launch_selection["key"], footer=danger_zone_controls)
    return features.library
