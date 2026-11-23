"""Shared profile artwork, badges, and details for the classic launcher."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
from typing import Callable

import flet as ft
from PIL import Image

from wisc.core import storage
from wisc.core.paths import ASSETS_DIR
from wisc.ui import theme
from wisc.ui.controls import LegacySelector, launcher_icon_button


DEFAULT_PROFILE_ICON = "icon_blocks/grass_block.png"
PROFILE_ICON_OPTIONS = [
    ("icon_blocks/grass_block.png", "Grass Block"),
    ("icon_blocks/crafting_table.png", "Crafting Table"),
    ("icon_blocks/furnace.png", "Furnace"),
    ("icon_blocks/chest.png", "Chest"),
    ("icon_blocks/diamond_ore.png", "Diamond Ore"),
    ("icon_blocks/tnt.png", "TNT"),
    ("icon_blocks/netherrack.png", "Netherrack"),
    ("icon_blocks/glass.png", "Glass"),
    ("icon_faces/creeper.png", "Creeper"),
    ("icon_faces/zombie.png", "Zombie"),
    ("icon_faces/skeleton.png", "Skeleton"),
    ("icon_faces/enderman.png", "Enderman"),
    ("icon_faces/pig.png", "Pig"),
    ("icon_faces/sheep.png", "Sheep"),
    ("icon_faces/wolf.png", "Wolf"),
    ("icon_faces/bee.png", "Bee"),
]


def profile_icon(profile: dict, *, size: int = 32) -> ft.Control:
    source = str(profile.get("icon") or DEFAULT_PROFILE_ICON)
    path = Path(source)
    if not path.is_file():
        path = ASSETS_DIR / "icons" / source
    if not path.is_file():
        path = ASSETS_DIR / "icons" / DEFAULT_PROFILE_ICON
    fallback = ft.Icon(ft.Icons.FOLDER_SPECIAL if profile.get("is_instance") else ft.Icons.INVENTORY_2,
                       size=size - 8, color=theme.MUTED)
    try:
        if path.is_file():
            return ft.Image(src=path.read_bytes(), width=size, height=size, fit=ft.BoxFit.CONTAIN,
                            filter_quality=ft.FilterQuality.NONE, error_content=fallback)
    except OSError:
        pass
    return fallback


def import_profile_icon(source: Path) -> str:
    """Keep a validated copy so moving the original image cannot lose an icon."""
    with Image.open(source) as picture:
        picture.load()
        picture = picture.convert("RGBA")
        picture.thumbnail((128, 128), Image.Resampling.LANCZOS)
        stream = io.BytesIO()
        picture.save(stream, format="PNG")
    data = stream.getvalue()
    folder = storage.DATA_DIR / "profile_icons"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (hashlib.sha256(data).hexdigest() + ".png")
    if not target.is_file():
        with tempfile.NamedTemporaryFile(dir=folder, suffix=".tmp", delete=False) as temporary:
            temporary.write(data)
            pending = Path(temporary.name)
        try:
            pending.replace(target)
        finally:
            pending.unlink(missing_ok=True)
    return str(target)


class ProfileIconField(ft.Row):
    """One classic selector, with a preview and custom-image/reset actions."""

    def __init__(self, page: ft.Page, profile: dict, *, file_picker: ft.FilePicker | None = None,
                 notify: Callable | None = None, on_change: Callable[[], None] | None = None):
        self._page = page
        self.on_change = on_change
        self._show_notification = notify or (lambda message, kind: None)
        self._custom_source: Path | None = None
        self._picker = file_picker or ft.FilePicker()
        if file_picker is None:
            page.services.append(self._picker)
        selected = str(profile.get("icon") or DEFAULT_PROFILE_ICON)
        choices = list(PROFILE_ICON_OPTIONS)
        if selected not in dict(choices):
            choices.append((selected, "Custom icon"))
        self.selector = LegacySelector(
            label="Profile icon", value=selected, expand=True,
            options=[ft.DropdownOption(key=key, text=label) for key, label in choices],
            on_select=self._changed,
        )
        self.preview = ft.Container(
            width=48, height=48, bgcolor=theme.SURFACE_STRONG, border_radius=8,
            border=ft.Border.all(1, theme.BORDER), alignment=ft.Alignment.CENTER,
            content=profile_icon({"icon": selected}),
        )
        super().__init__(controls=[
            self.preview, self.selector,
            launcher_icon_button(icon=ft.Icons.IMAGE_OUTLINED, on_click=self._choose,
                                 tooltip="Choose a custom profile icon"),
            launcher_icon_button(icon=ft.Icons.RESTART_ALT, on_click=self._reset,
                                 tooltip="Reset profile icon"),
        ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    @property
    def value(self) -> str:
        return self.selector.value or DEFAULT_PROFILE_ICON

    def _changed(self, event=None) -> None:
        self.preview.content = profile_icon({"icon": self.value})
        if self.on_change is not None:
            self.on_change()
        try:
            self.update()
        except RuntimeError:
            pass

    async def _choose(self, event) -> None:
        try:
            files = await self._picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.CUSTOM,
                                                 allowed_extensions=["png", "jpg", "jpeg", "webp"])
        except Exception as error:
            self._show_notification(f"Could not open the image picker: {error}", "error")
            return
        if not files or not files[0].path:
            return
        source = Path(files[0].path)
        try:
            with Image.open(source) as picture:
                picture.verify()
        except (OSError, ValueError):
            self._show_notification("Choose a valid PNG, JPEG, or WebP image.", "error")
            return
        self._custom_source = source
        choices = list(PROFILE_ICON_OPTIONS) + [(str(source), "Custom icon")]
        self.selector.options = [ft.DropdownOption(key=key, text=label) for key, label in choices]
        self.selector.value = str(source)
        self._changed()

    def _reset(self, event) -> None:
        self._custom_source = None
        self.selector.value = DEFAULT_PROFILE_ICON
        self._changed()

    def saved_value(self) -> str:
        if self._custom_source is not None and self.value == str(self._custom_source):
            return import_profile_icon(self._custom_source)
        return self.value


def profile_summary(profile: dict) -> str:
    loader = str(profile.get("loader") or "Vanilla")
    parts = [loader, str(profile.get("minecraft_version") or profile.get("version_id") or "Unknown version")]
    if loader.casefold() != "vanilla" and profile.get("loader_version"):
        parts.append(str(profile["loader_version"]))
    elif profile.get("channel"):
        parts.append(str(profile["channel"]))
    summary = " | ".join(parts)
    if profile.get("is_instance"):
        summary += " · Instance: " + str(profile.get("instance_name") or profile.get("name") or "Custom")
    return summary


def profile_badges(profile: dict) -> list[ft.Control]:
    loader = str(profile.get("loader") or "Vanilla")
    version = str(profile.get("minecraft_version") or profile.get("version_id") or "")
    if version.casefold() == "latest-release":
        version = "Release"
    badges = []

    def badge(label: str, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(label, size=10, weight=ft.FontWeight.W_600, color=color),
            bgcolor=theme.opacity(0.14, color), border_radius=5,
            padding=ft.Padding.symmetric(horizontal=7, vertical=2),
        )

    if version:
        badges.append(badge(version, theme.ACCENT))
    if loader.casefold() != "vanilla":
        color = {"fabric": theme.LOADER_FABRIC, "forge": theme.LOADER_FORGE,
                 "neoforge": theme.LOADER_NEOFORGE, "quilt": theme.LOADER_QUILT,
                 "optifine": theme.LOADER_QUILT}.get(loader.casefold(), theme.MUTED)
        badges.append(badge(loader, color))
    if profile.get("is_instance"):
        badges.append(badge("Instance", theme.ACCENT))
    if profile.get("modpack"):
        badges.append(badge("Modpack", theme.MUTED))
    return badges
