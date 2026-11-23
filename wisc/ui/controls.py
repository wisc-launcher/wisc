"""Classic launcher inputs, rounded buttons, cards, and anchored selectors."""

from __future__ import annotations

from typing import Callable
import flet as ft
from wisc.ui import theme
from wisc.ui.glass import glass_panel


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    return f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else f"{size / 1024:.0f} KB"


def format_downloads(count: int) -> str:
    for threshold, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if count >= threshold:
            return f"{count / threshold:.1f}".removesuffix(".0") + suffix
    return str(count)


_size = format_size
_downloads = format_downloads


class SimpleInput(ft.TextField):
    def __init__(self, hint_text="Enter text", **kwargs):
        defaults = {
            "hint_text": hint_text, "bgcolor": theme.SURFACE,
            "border_color": theme.BORDER, "focused_border_color": theme.ACCENT,
            "border_radius": 5, "hover_color": theme.CARD_HOVER,
            "color": theme.TEXT, "hint_style": ft.TextStyle(color=theme.MUTED, size=13),
            "label_style": ft.TextStyle(color=theme.MUTED, size=13),
            "cursor_color": theme.ACCENT, "text_size": 13,
            "content_padding": ft.Padding.symmetric(horizontal=14, vertical=14),
        }
        if kwargs.get("password") and kwargs.get("can_reveal_password"):
            # Balance the caret beside the native reveal icon without resizing.
            defaults["text_vertical_align"] = -0.5
        defaults.update(kwargs)
        super().__init__(**defaults)


class SimpleButton(ft.Button):
    def __init__(self, content=None, on_click=None, style=None, **kwargs):
        super().__init__(
            content=content, on_click=on_click,
            style=style or ft.ButtonStyle(
                bgcolor=theme.TRANSPARENT, overlay_color=theme.TRANSPARENT,
                shadow_color=theme.TRANSPARENT, mouse_cursor=ft.MouseCursor.CLICK,
                side=ft.BorderSide(0, theme.TRANSPARENT), padding=0,
                shape=ft.RoundedRectangleBorder(radius=0),
            ), **kwargs,
        )


def launcher_button(label: str, on_click: Callable | None, *, primary: bool = False,
                    height: int = 36, **kwargs) -> SimpleButton:
    return SimpleButton(
        ft.Text(label, size=13, weight=ft.FontWeight.W_600),
        on_click=on_click, height=height,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: theme.ACCENT if primary else theme.SECONDARY,
                ft.ControlState.HOVERED: theme.ACCENT_HOVER if primary else theme.SECONDARY_HOVER,
                ft.ControlState.PRESSED: theme.ACCENT_ACTIVE if primary else theme.SECONDARY_ACTIVE,
                ft.ControlState.DISABLED: theme.SURFACE,
            },
            color={ft.ControlState.DEFAULT: theme.ON_ACCENT if primary else theme.ON_SECONDARY,
                   ft.ControlState.DISABLED: theme.MUTED},
            overlay_color={ft.ControlState.FOCUSED: theme.opacity(0.16, theme.ACCENT),
                           ft.ControlState.DEFAULT: theme.TRANSPARENT},
            elevation=0, shadow_color=theme.TRANSPARENT,
            mouse_cursor={ft.ControlState.DEFAULT: ft.MouseCursor.CLICK,
                          ft.ControlState.DISABLED: ft.MouseCursor.BASIC},
            side=ft.BorderSide(0 if primary else 1, theme.BORDER),
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=14),
        ), **kwargs,
    )


def launcher_tab(label: str, on_click: Callable) -> SimpleButton:
    button = launcher_button(label, on_click)
    select_tab(button, False)
    return button


def select_tab(button: SimpleButton, selected: bool) -> None:
    """Apply the classic navigation's quiet, visible selection treatment."""
    button.style.bgcolor = {
        ft.ControlState.DEFAULT: theme.opacity(0.16, theme.ACCENT) if selected else theme.TRANSPARENT,
        ft.ControlState.HOVERED: theme.opacity(0.22 if selected else 0.08, theme.ACCENT),
    }
    button.style.side = ft.BorderSide(0, theme.TRANSPARENT)
    button.content.color = None
    button.style.color = {ft.ControlState.DEFAULT: theme.ACCENT if selected else theme.MUTED,
                          ft.ControlState.DISABLED: theme.MUTED}


def launcher_pill(label: str, on_click: Callable | None, *, icon=None, primary: bool = False,
                  tooltip: str | None = None, **kwargs) -> ft.Container:
    """Classic compact action, with the container API used by update feedback."""
    fg = theme.ON_ACCENT if primary else theme.ON_SECONDARY
    bg = theme.ACCENT if primary else theme.SECONDARY
    controls: list[ft.Control] = []
    if icon is not None:
        controls.append(ft.Icon(icon, size=14, color=fg))
    controls.append(ft.Text(label, color=fg, size=13, weight=ft.FontWeight.W_600))
    return glass_panel(
        bgcolor=bg,
        blur=None if primary else 10,
        border_radius=8, height=36,
        border=ft.Border.all(0 if primary else 1, theme.BORDER),
        padding=ft.Padding.symmetric(horizontal=12),
        ink=True,
        tooltip=tooltip,
        content=ft.Row(
            controls,
            spacing=6,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        on_click=on_click,
        **kwargs,
    )


def rounded_artwork(content: ft.Control, *, size: int) -> ft.Container:
    """Clip artwork to the classic icon corners on every renderer."""
    return ft.Container(
        content=content, width=size, height=size, border_radius=8,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS, alignment=ft.Alignment.CENTER,
    )


def launcher_asset_icon(src: str, *, color: str | None = None, **kwargs) -> ft.Image:
    """Tint a bundled UI icon's silhouette while retaining its alpha channel."""
    return ft.Image(
        src=src, color=theme.ACCENT if color is None else color,
        color_blend_mode=ft.BlendMode.SRC_IN, **kwargs,
    )


def launcher_back_button(on_click: Callable, *, label: str = "Back", tooltip: str | None = None,
                         **kwargs) -> SimpleButton:
    """Use the classic settings' compact arrow and system-font label."""
    return SimpleButton(
        ft.Row([
            ft.Icon(ft.Icons.ARROW_BACK, color=theme.MUTED, size=20),
            ft.Text(label, color=theme.TEXT, size=13),
        ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        on_click=on_click, tooltip=tooltip,
        style=ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: theme.TRANSPARENT, ft.ControlState.HOVERED: theme.CARD_HOVER},
            overlay_color=theme.opacity(0.12, theme.ACCENT),
            shadow_color=theme.TRANSPARENT, mouse_cursor=ft.MouseCursor.CLICK,
            side=ft.BorderSide(0, theme.TRANSPARENT),
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        ), **kwargs,
    )


def launcher_icon_button(*, icon, on_click: Callable, tooltip: str, primary: bool = False, **kwargs) -> ft.IconButton:
    """Compact classic actions with visible hover and keyboard focus feedback."""
    defaults = {
        "icon": icon, "on_click": on_click, "tooltip": tooltip,
        "icon_color": theme.ON_ACCENT if primary else theme.MUTED,
        "bgcolor": theme.ACCENT if primary else theme.TRANSPARENT,
        "icon_size": 20, "width": 36, "height": 36,
        "mouse_cursor": ft.MouseCursor.CLICK,
        "style": ft.ButtonStyle(
            bgcolor={ft.ControlState.DEFAULT: theme.ACCENT if primary else theme.TRANSPARENT,
                     ft.ControlState.HOVERED: theme.ACCENT_HOVER if primary else theme.CARD_HOVER},
            overlay_color=theme.opacity(0.12, theme.ACCENT),
            shadow_color=theme.TRANSPARENT, mouse_cursor=ft.MouseCursor.CLICK,
            shape=ft.RoundedRectangleBorder(radius=8), padding=6,
        ),
    }
    defaults.update(kwargs)
    return ft.IconButton(**defaults)


def search_input(hint_text: str = "Search", *, on_change: Callable | None = None,
                 on_submit: Callable | None = None, **kwargs) -> SimpleInput:
    """Standard launcher search bar with uniform 5px corners and muted hint."""
    defaults = {
        "hint_text": hint_text,
        "expand": True,
        "hint_style": ft.TextStyle(color=theme.MUTED),
        "height": 48,
        "prefix_icon": ft.Icons.SEARCH_SHARP,
        "on_change": on_change,
        "on_submit": on_submit,
    }
    defaults.update(kwargs)
    return SimpleInput(**defaults)


def card_surface(content: ft.Control, *, glow_color: str | None = None, horizontal_padding: int = 16,
                 margin_bottom: int = 8, key: ft.ValueKey | None = None, data=None) -> ft.Container:
    """Use the classic profile surface for mods, packs, and version rows."""
    from wisc.ui.profiles import profile_card_surface
    surface = profile_card_surface(content, glow_color=glow_color or theme.GLOW, horizontal_padding=horizontal_padding)
    if margin_bottom:
        surface.margin = ft.Margin.only(bottom=margin_bottom)
    if key is not None:
        surface.key = key
    if data is not None:
        surface.data = data
    return surface


class AcrylicSelector(ft.PopupMenuButton):
    """Dark launcher field with an anchored, keyboard-accessible acrylic menu."""

    def __init__(self, options: list[tuple[str, str]], value: str | None, on_select: Callable, *,
                 width=160, pixel=False, hint="Choose", tooltip=None, prefix: str | None = None):
        self.value = value
        self.options = options
        self._choose = on_select
        self._hint = hint
        self._pixel = pixel
        self._prefix = prefix
        self._label = ft.Text(hint, size=16 if pixel else 13, font_family="Pixelify Sans" if pixel else None,
                              color=theme.TEXT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        row_controls: list[ft.Control] = []
        if prefix:
            row_controls.append(ft.Text(prefix, size=16 if pixel else 13, font_family="Pixelify Sans" if pixel else None, color=theme.MUTED))
        row_controls.extend([self._label, ft.Icon(ft.Icons.EXPAND_MORE_SHARP, color=theme.MUTED, size=18)])
        super().__init__(
            content=glass_panel(
                height=48, bgcolor=theme.SURFACE, border_radius=5,
                border=ft.Border.all(1, theme.BORDER),
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                content=ft.Row(row_controls, spacing=8),
            ), width=width, height=48, padding=0, menu_padding=0,
            bgcolor=theme.TRANSPARENT, shadow_color=theme.SURFACE, elevation=0,
            menu_position=ft.PopupMenuPosition.UNDER,
            size_constraints=ft.BoxConstraints(min_width=width, max_width=width),
            shape=ft.RoundedRectangleBorder(radius=5), clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            style=ft.ButtonStyle(overlay_color=theme.opacity(0.12, theme.ACCENT), mouse_cursor=ft.MouseCursor.CLICK),
            tooltip=tooltip or hint,
        )
        self.refresh_options(options, value)

    def refresh_options(self, options: list[tuple[str, str]], value: str | None) -> None:
        self.options = options
        self.value = value
        self._label.value = next((label for key, label in options if key == value), self._hint)
        self.items = [
            ft.PopupMenuItem(
                key=ft.ValueKey(key), padding=0, height=46,
                content=ft.Container(
                    width=self.width, height=46, padding=ft.Padding.symmetric(horizontal=14),
                    bgcolor=theme.opacity(0.88, theme.SURFACE), blur=ft.Blur(14, 14),
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    content=ft.Row([
                        ft.Text(label, color=theme.ACCENT if key == value else theme.TEXT_SECONDARY, size=14,
                                expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Icon(ft.Icons.CHECK_SHARP, color=theme.ACCENT, size=16, visible=key == value),
                    ], spacing=8),
                ), on_click=lambda e, selected=key: self._select(selected, e),
            ) for key, label in options
        ]

    def _select(self, value: str, e) -> None:
        self.refresh_options(self.options, value)
        self._choose(e)


class LegacySelector(ft.Container):
    """Original form-field API backed by the launcher's shared acrylic selector."""

    def __init__(self, *, label=None, value=None, options=None, on_select=None,
                 width=None, expand=None, visible=True, disabled=False, **kwargs):
        self._value = value
        self._options = options or []
        self.on_select = on_select
        self.selector = AcrylicSelector(self._pairs(), value, self._selected,
                                        width=width or (456 if expand else 280), hint=label or "Choose",
                                        prefix=label, tooltip=kwargs.get("tooltip"))
        super().__init__(content=self.selector, width=width, expand=expand,
                         visible=visible, disabled=disabled, on_size_change=self._resize)

    def _pairs(self) -> list[tuple[str, str]]:
        return [(str(option.key or option.text), str(option.text or option.key)) for option in self._options]

    @property
    def options(self):
        return self._options

    @options.setter
    def options(self, options):
        self._options = options
        if hasattr(self, "selector"):
            self.selector.refresh_options(self._pairs(), self._value)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value
        if hasattr(self, "selector"):
            self.selector.refresh_options(self._pairs(), value)

    def _selected(self, event):
        from types import SimpleNamespace

        self._value = self.selector.value
        if self.on_select:
            self.on_select(SimpleNamespace(control=self, data=self.value, page=getattr(event, "page", None)))

    def _resize(self, event):
        if event.width and abs(self.selector.width - event.width) > 1:
            self.selector.width = event.width
            self.selector.size_constraints = ft.BoxConstraints(min_width=event.width, max_width=event.width)
            self.selector.refresh_options(self._pairs(), self._value)
            self.selector.update()
