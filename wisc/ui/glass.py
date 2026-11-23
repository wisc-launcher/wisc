"""Shared dark glass colors and frosted surfaces for the launcher UI."""

from __future__ import annotations

import flet as ft


GLASS_COLOR = "#0B0D0A"
GLASS_TEXT = "#F1F5EC"
GLASS_MUTED = "#B1BAAD"
GLASS_RADIUS = 14


def glass_palette(palette: dict[str, str]) -> dict[str, str]:
    """Keep theme accents while giving every page the same translucent glass."""
    return {
        **palette,
        "surface": "#6B0B0D0A",
        "card": "#850B0D0A",
        "card_hover": "#A30B0D0A",
        "border": ft.Colors.TRANSPARENT,
        "dialog": "#C70B0D0A",
        "toast": "#AD0B0D0A",
        "btn_secondary": "#850B0D0A",
        "btn_secondary_hover": "#A30B0D0A",
        "btn_secondary_active": "#B80B0D0A",
        "btn_secondary_text": GLASS_TEXT,
        "text_primary": GLASS_TEXT,
        "text_secondary": GLASS_MUTED,
        "text_muted": "#899582",
    }


def glass_panel(content: ft.Control | None = None, *, opacity: float = 0.42,
                blur: float | None = 10, **kwargs) -> ft.Container:
    """Blur the backdrop behind a rounded panel, keeping its contents sharp."""
    defaults = {
        "content": content,
        "bgcolor": ft.Colors.with_opacity(opacity, GLASS_COLOR),
        "blur": ft.Blur(blur, blur, ft.BlurTileMode.MIRROR) if blur is not None else None,
        "border_radius": GLASS_RADIUS,
        "border": None,
        "clip_behavior": ft.ClipBehavior.ANTI_ALIAS,
    }
    defaults.update(kwargs)
    return ft.Container(**defaults)
