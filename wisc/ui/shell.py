"""Persistent window artwork and borderless dark glass for the shared shell."""

from __future__ import annotations

from pathlib import Path

import flet as ft

from wisc.services.artwork import BackgroundArtwork, resolve_background_artwork
from wisc.ui.glass import GLASS_COLOR, GLASS_TEXT, GLASS_MUTED, GLASS_RADIUS, glass_panel


TITLE_BAR_HEIGHT = 52
HOME_BACKDROP_OPACITY = 0.04
FEATURE_BACKDROP_OPACITY = 0.24
CUSTOM_ARTWORK_BLUR = 10


def _artwork_vignette(**kwargs) -> ft.Container:
    """Darken all four window edges while keeping the artwork's center clear."""
    return ft.Container(
        ignore_interactions=True,
        content=ft.Stack([
            ft.Container(
                left=0, top=0, right=0, bottom=0,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT,
                    colors=[ft.Colors.with_opacity(alpha, GLASS_COLOR)
                            for alpha in (0.42, 0.04, 0.0, 0.04, 0.42)],
                    stops=[0, 0.18, 0.5, 0.82, 1],
                ),
            ),
            ft.Container(
                left=0, top=0, right=0, bottom=0,
                gradient=ft.LinearGradient(
                    begin=ft.Alignment.TOP_CENTER, end=ft.Alignment.BOTTOM_CENTER,
                    colors=[ft.Colors.with_opacity(alpha, GLASS_COLOR)
                            for alpha in (0.36, 0.02, 0.0, 0.08, 0.48)],
                    stops=[0, 0.22, 0.48, 0.75, 1],
                ),
            ),
        ], fit=ft.StackFit.EXPAND),
        **kwargs,
    )


class GlassSurface(ft.Container):
    """Crop the window's pre-blurred cover behind a shared fixed surface.

    Only the background layer clips. Dialogs and other foreground overlays can
    extend beyond the surface without being clipped by Flet's backdrop filter.
    Custom images use a live filter on that background layer alone.
    """

    def __init__(self, content: ft.Control, artwork: BackgroundArtwork, *,
                 viewport_width: float, viewport_height: float, left: float = 0,
                 top: float = 0, opacity: float = 0.66, frosted: bool = True,
                 radius: float = GLASS_RADIUS, **kwargs):
        self._mounted = False
        self._frosted = frosted
        self._artwork = artwork
        self.artwork_image = ft.Image(
            src=artwork.frosted_source or artwork.source,
            left=-left, top=-top, width=viewport_width, height=viewport_height,
            fit=ft.BoxFit.COVER, gapless_playback=True, filter_quality=ft.FilterQuality.HIGH,
            visible=frosted and artwork.frosted_source is not None,
        )
        self.vignette = _artwork_vignette(
            left=-left, top=-top, width=viewport_width, height=viewport_height,
        )
        self.tint = ft.Container(
            left=0, top=0, right=0, bottom=0,
            bgcolor=ft.Colors.with_opacity(opacity, GLASS_COLOR),
        )
        self.background_layer = ft.Container(
            left=0, top=0, right=0, bottom=0,
            border_radius=radius, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ignore_interactions=True,
            content=ft.Stack([self.artwork_image, self.vignette, self.tint], fit=ft.StackFit.EXPAND),
        )
        self._sync_filter()
        super().__init__(
            content=ft.Stack([self.background_layer, content], fit=ft.StackFit.EXPAND,
                             clip_behavior=ft.ClipBehavior.NONE),
            border_radius=radius,
            **kwargs,
        )

    def did_mount(self) -> None:
        self._mounted = True

    def will_unmount(self) -> None:
        self._mounted = False

    def _sync_filter(self) -> None:
        self.artwork_image.visible = self._frosted and self._artwork.frosted_source is not None
        self.vignette.visible = self.artwork_image.visible
        self.background_layer.blur = (
            ft.Blur(CUSTOM_ARTWORK_BLUR, CUSTOM_ARTWORK_BLUR, ft.BlurTileMode.MIRROR)
            if self._frosted and self._artwork.frosted_source is None else None
        )

    def set_artwork(self, artwork: BackgroundArtwork) -> None:
        if artwork == self._artwork:
            return
        self._artwork = artwork
        self.artwork_image.src = artwork.frosted_source or artwork.source
        self._sync_filter()
        if self._mounted:
            self.background_layer.update()

    def set_frosted(self, frosted: bool) -> None:
        if self._frosted == frosted:
            return
        self._frosted = frosted
        self.tint.bgcolor = ft.Colors.with_opacity(
            FEATURE_BACKDROP_OPACITY if frosted else HOME_BACKDROP_OPACITY, GLASS_COLOR,
        )
        self._sync_filter()
        if self._mounted:
            self.background_layer.update()

    def resize(self, width: float, height: float) -> None:
        self.artwork_image.width = width
        self.artwork_image.height = height
        self.vignette.width = width
        self.vignette.height = height
        if self._mounted:
            self.background_layer.update()


class LauncherBackground(ft.Container):
    """Retain one selected cover across navigation and theme rebuilds."""

    def __init__(self, *, assets_dir: Path, width: float, height: float):
        self._assets_dir = assets_dir
        self._mounted = False
        self.viewport_width, self.viewport_height = width, height
        self._surfaces: list[GlassSurface] = []
        self.artwork = resolve_background_artwork(None, assets_dir=assets_dir)
        self.artwork_image = ft.Image(
            key=ft.ValueKey("launcher-background-artwork"), src=self.artwork.source,
            left=0, top=0, right=0, bottom=0, fit=ft.BoxFit.COVER,
            gapless_playback=True, filter_quality=ft.FilterQuality.HIGH,
        )
        vignette = _artwork_vignette(left=0, top=0, right=0, bottom=0)
        super().__init__(
            left=0, top=0, right=0, bottom=0, ignore_interactions=True,
            bgcolor=GLASS_COLOR,
            content=ft.Stack([self.artwork_image, vignette], fit=ft.StackFit.EXPAND),
        )

    def did_mount(self) -> None:
        self._mounted = True

    def will_unmount(self) -> None:
        self._mounted = False

    def reset_surfaces(self) -> None:
        """Discard only the old shell's chrome when its theme is rebuilt."""
        self._surfaces.clear()

    def panel(self, content: ft.Control, *, left: float = 0, top: float = 0,
              opacity: float = 0.66, frosted: bool = True, **kwargs) -> GlassSurface:
        surface = GlassSurface(
            content, self.artwork, viewport_width=self.viewport_width,
            viewport_height=self.viewport_height, left=left, top=top,
            opacity=opacity, frosted=frosted, **kwargs,
        )
        self._surfaces.append(surface)
        return surface

    def set_target(self, target: dict | None, minecraft_directory: str | None = None) -> None:
        artwork = resolve_background_artwork(target, minecraft_directory, assets_dir=self._assets_dir)
        if artwork == self.artwork:
            return
        source: str | bytes = artwork.source
        if artwork.custom_revision is not None:
            # File image providers cache by path. Bytes also refresh an edited
            # custom image when the profile keeps the same saved filename.
            try:
                source = Path(source).read_bytes()
            except OSError:
                return
        self.artwork = artwork
        self.artwork_image.src = source
        for surface in self._surfaces:
            surface.set_artwork(artwork)
        if self._mounted:
            self.artwork_image.update()

    def resize(self, width: float, height: float) -> None:
        if width <= 0 or height <= 0 or (width, height) == (self.viewport_width, self.viewport_height):
            return
        self.viewport_width, self.viewport_height = width, height
        for surface in self._surfaces:
            surface.resize(width, height)
