"""Bundled vector illustrations for Settings, tinted with the active accent."""

from functools import lru_cache

import flet as ft

from wisc.core.paths import ASSETS_DIR
from wisc.core.themes import normalize_accent


@lru_cache(maxsize=16)
def _source(name: str) -> str:
    return (ASSETS_DIR / "settings" / f"{name}.svg").read_text(encoding="utf-8")


def settings_art(name: str, accent: str, *, width: int, height: int) -> ft.Image:
    """Keep artwork vector-sharp and use only validated RGB accent values."""
    source = _source(name).replace("#46BA34", normalize_accent(accent) or "#46BA34")
    return ft.Image(src=source, width=width, height=height, fit=ft.BoxFit.CONTAIN,
                    exclude_from_semantics=True, gapless_playback=True)
