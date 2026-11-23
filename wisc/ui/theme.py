"""Semantic glass colors and theme accents shared by all launcher features."""

from __future__ import annotations

import flet as ft

from wisc.core.themes import DEFAULT_THEME, get_theme
from wisc.ui.glass import glass_palette


class ThemeColor(str):
    """Remember a color's role when two palette tokens share the same hex value."""

    def __new__(cls, value: str, role: str, alpha: float | None = None):
        color = super().__new__(cls, value)
        color.role = role
        color.alpha = alpha
        return color

    def __getnewargs__(self) -> tuple:
        return str(self), self.role, self.alpha


def opacity(alpha: float, color: str) -> str:
    """Apply Flet opacity while retaining the selected theme's color role."""
    value = ft.Colors.with_opacity(alpha, color)
    return ThemeColor(value, color.role, alpha) if isinstance(color, ThemeColor) else value


def resolve_color(color: ThemeColor) -> str:
    current = globals().get(color.role, color)
    return opacity(color.alpha, current) if color.alpha is not None else current


BLACK = "#000000"
TRANSPARENT = ft.Colors.TRANSPARENT
SCRIM = ft.Colors.BLACK_54

# Feedback and Minecraft loader badges keep their meaning across themes.
SUCCESS = "#81c784"
SUCCESS_BRIGHT = "#34d399"
DANGER = "#e57373"
ERROR = "#f87171"
WARNING = "#ffb74d"
WARNING_ACTIVE = "#ffa726"
INFO = "#64b5f6"
UPDATE = "#a7c9ff"
TOAST_WARNING = "#f5cf83"
TOAST_ERROR = "#ff9292"
LOG_ERROR = "#ef5350"
LOG_WARNING = "#ffca28"
LOG_INFO = "#90caf9"
LOADER_FABRIC = "#82b1ff"
LOADER_FORGE = WARNING
LOADER_NEOFORGE = "#ff8a65"
LOADER_QUILT = "#ce93d8"
LOADER_OTHER = "#b0bec5"
MASK_OPAQUE = "#ffffffff"
MASK_TRANSPARENT = "#00ffffff"


def apply_legacy_theme(palette: dict[str, str]) -> None:
    """Apply consistent dark glass and the selected accents to every feature."""
    palette = glass_palette(palette)
    roles = {
        "BACKGROUND": "bg", "SURFACE": "surface", "SURFACE_STRONG": "card",
        "CARD_HOVER": "card_hover", "GLOW": "card_hover", "BORDER": "border",
        "ACCENT": "btn_primary", "ACCENT_HOVER": "btn_primary_hover",
        "ACCENT_ACTIVE": "btn_primary_active", "ON_ACCENT": "btn_primary_text",
        "SECONDARY": "btn_secondary", "SECONDARY_HOVER": "btn_secondary_hover",
        "SECONDARY_ACTIVE": "btn_secondary_active", "ON_SECONDARY": "btn_secondary_text",
        "TEXT": "text_primary", "MUTED": "text_secondary", "NAV_MUTED": "text_muted",
        "TOAST_BACKGROUND": "toast", "DIALOG_BACKGROUND": "dialog",
        "CODE_BACKGROUND": "surface", "QUOTE_BACKGROUND": "card",
        "AUTH_INACTIVE": "surface", "SWITCH_TRACK": "border",
        "SWITCH_INACTIVE_TRACK": "surface", "SWITCH_ACTIVE_TRACK": "btn_primary",
        "ICON_MUTED": "text_secondary", "ICON_CLOSE": "text_secondary",
    }
    roles.update({name: "text_primary" for name in (
        "TEXT_HEADING", "TEXT_DETAIL", "TEXT_STATUS", "TEXT_CODE", "TEXT_UPDATE", "TEXT_LOG",
    )})
    roles.update({name: "text_secondary" for name in (
        "TEXT_SECONDARY", "TEXT_SUPPORT", "TEXT_PLACEHOLDER", "TEXT_CAPTION", "TEXT_FOOTNOTE",
    )})
    globals().update({name: ThemeColor(palette[token], name) for name, token in roles.items()})
    globals().update({
        "TEXT_DIM": ThemeColor(ft.Colors.with_opacity(0.70, palette["text_primary"]), "TEXT_DIM"),
        "TEXT_HINT": ThemeColor(ft.Colors.with_opacity(0.55, palette["text_secondary"]), "TEXT_HINT"),
    })


apply_legacy_theme(get_theme(DEFAULT_THEME))
