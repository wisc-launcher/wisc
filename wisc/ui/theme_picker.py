"""A local color draft with a vector HSV wheel and a launcher preview."""

from colorsys import hsv_to_rgb, rgb_to_hsv
from math import atan2, cos, hypot, pi, sin
from typing import Callable

import flet as ft

from wisc.core.themes import custom_theme, normalize_accent
from wisc.ui.controls import SimpleInput, launcher_button
from wisc.ui.glass import GLASS_MUTED, GLASS_TEXT, glass_panel


WHEEL_SIZE = 224
WHEEL_CENTER = WHEEL_SIZE / 2
WHEEL_RADIUS = 100


def color_wheel_surface(diameter: int = 200) -> ft.Container:
    """Draw a smooth HSV disk with native vector gradients at any size."""
    return ft.Container(
        width=diameter, height=diameter, border_radius=diameter / 2,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        gradient=ft.SweepGradient(colors=["#FF0000", "#FFFF00", "#00FF00", "#00FFFF",
                                         "#0000FF", "#FF00FF", "#FF0000"]),
        content=ft.Container(
            gradient=ft.RadialGradient(colors=["#FFFFFF", "#00FFFFFF"]),
        ),
    )


def wheel_color(x: float, y: float, previous_hue: float) -> tuple[float, float]:
    """Map a wheel position to HSV, preserving hue at the neutral center."""
    dx, dy = x - WHEEL_CENTER, y - WHEEL_CENTER
    distance = hypot(dx, dy)
    hue = (atan2(dy, dx) / (2 * pi)) % 1 if distance > 0.5 else previous_hue
    return hue, min(1, distance / WHEEL_RADIUS)


class ThemePicker(ft.Container):
    """Preview edits immediately; persist only through the Apply callback."""

    def __init__(self, accent: str, theme: dict, on_apply: Callable[[str], bool]):
        self._saved = normalize_accent(accent) or theme["btn_primary"]
        self._on_apply = on_apply
        self._mounted = False
        self._hue, self._saturation, self._brightness = self._decode(self._saved)
        self._marker = ft.Container(
            width=18, height=18, border_radius=9, border=ft.Border.all(2, "#FFFFFF"),
            shadow=ft.BoxShadow(blur_radius=3, spread_radius=1, color="#99000000"),
            ignore_interactions=True,
        )
        self._shade = ft.Container(left=12, top=12, width=200, height=200, border_radius=100,
                                   bgcolor="#000000", ignore_interactions=True)
        self._wheel = ft.GestureDetector(
            content=ft.Stack([
                ft.Container(left=12, top=12, content=color_wheel_surface()),
                self._shade, self._marker,
            ], width=224, height=224),
            mouse_cursor=ft.MouseCursor.PRECISE, drag_interval=24,
            on_tap_down=self._pick, on_pan_start=self._pick, on_pan_update=self._pick,
            tooltip="Drag to choose hue and saturation. Sliders also support keyboard adjustment.",
        )
        self._preview_action = launcher_button("Play", None, primary=True, width=94, height=36)
        self._preview_selection = ft.Container(
            border_radius=7, padding=ft.Padding.symmetric(horizontal=10, vertical=7),
            content=ft.Text("Survival", size=12, weight=ft.FontWeight.W_600),
        )
        self._preview_dot = ft.Container(width=7, height=7, border_radius=4)
        preview = glass_panel(
            bgcolor="#8C0B0D0A", blur=None, border_radius=10, padding=16,
            content=ft.Column([
                ft.Row([
                    self._preview_dot,
                    ft.Text("LIVE PREVIEW", size=10, weight=ft.FontWeight.W_600, color=GLASS_MUTED),
                ], spacing=7),
                ft.Text("Your next adventure", size=20, font_family="Pixelify Sans", color=GLASS_TEXT),
                ft.Row([self._preview_selection, self._preview_action],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ], spacing=10),
        )
        self._hex_input = SimpleInput(
            value=self._saved, label="Hex color", hint_text="#46BA34", height=48,
            max_length=7, counter="", on_change=self._edit_hex,
            on_submit=self._submit_hex, on_blur=self._submit_hex,
        )
        self._sliders: list[ft.Slider] = []
        self._slider_labels: list[ft.Text] = []
        slider_rows = []
        for name, value, maximum in (("Hue", self._hue * 360, 360),
                                     ("Saturation", self._saturation * 100, 100),
                                     ("Brightness", self._brightness * 100, 100)):
            label = ft.Text(size=11, color=GLASS_MUTED, width=34, text_align=ft.TextAlign.RIGHT)
            slider = ft.Slider(
                min=0, max=maximum, divisions=maximum, value=value, expand=True,
                label="{value}°" if name == "Hue" else "{value}%",
                inactive_color="#40545E50", tooltip=name, height=28,
                on_change=lambda e, channel=name: self._slide(channel, float(e.control.value)),
            )
            self._sliders.append(slider)
            self._slider_labels.append(label)
            slider_rows.append(ft.Row([
                ft.Text(name, size=12, color=GLASS_MUTED, width=70), slider, label,
            ], spacing=4, height=30))
        self._apply = launcher_button("Use this color", self._apply_color, primary=True, height=38)
        self._revert = launcher_button("Revert", lambda e: self._set_hex(self._saved), height=38)
        self._swatches = []
        for color, label in (("#46BA34", "Grass"), ("#76C8F0", "Ice"), ("#A78BFA", "Amethyst"),
                             ("#F28CB1", "Blossom"), ("#F4BA68", "Honey"), ("#EF7866", "Ember")):
            swatch = launcher_button("", lambda e, value=color: self._set_hex(value),
                                     width=30, height=30, tooltip=f"{label} · {color}")
            swatch.content = ft.Semantics(label=f"{label} · {color}", content=ft.Container(width=1, height=1))
            swatch.style.bgcolor = color
            swatch.style.padding = 0
            swatch.style.shape = ft.RoundedRectangleBorder(radius=9)
            swatch.style.overlay_color = {ft.ControlState.FOCUSED: "#66FFFFFF"}
            self._swatches.append((color, swatch))
        super().__init__(content=ft.ResponsiveRow([
            ft.Column([
                self._wheel,
                ft.Text("Pick a shade. Make it yours.", size=12, color=GLASS_MUTED),
                ft.Row([swatch for _, swatch in self._swatches], spacing=8,
                       alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER, col={"xs": 12, "md": 5}),
            ft.Column([
                preview, self._hex_input, ft.Column(slider_rows, spacing=0),
                ft.Row([self._apply, self._revert], spacing=8, wrap=True),
            ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, col={"xs": 12, "md": 7}),
        ], spacing=24, run_spacing=20, vertical_alignment=ft.CrossAxisAlignment.CENTER))
        self._refresh()

    @staticmethod
    def _decode(accent: str) -> tuple[float, float, float]:
        return rgb_to_hsv(*(int(accent[index:index + 2], 16) / 255 for index in (1, 3, 5)))

    @property
    def accent(self) -> str:
        return "#" + "".join(f"{round(channel * 255):02X}" for channel in
                             hsv_to_rgb(self._hue, self._saturation, self._brightness))

    def did_mount(self) -> None:
        self._mounted = True

    def will_unmount(self) -> None:
        self._mounted = False

    def _pick(self, event) -> None:
        position = event.local_position
        if position is None:
            return
        self._hue, self._saturation = wheel_color(position.x, position.y, self._hue)
        self._refresh()

    def _slide(self, channel: str, value: float) -> None:
        if channel == "Hue":
            self._hue = value / 360
        elif channel == "Saturation":
            self._saturation = value / 100
        else:
            self._brightness = value / 100
        self._refresh()

    def _set_hex(self, value: str, *, rewrite: bool = True) -> None:
        accent = normalize_accent(value)
        if accent is None:
            return
        hue, self._saturation, self._brightness = self._decode(accent)
        if self._saturation > 0:
            self._hue = hue
        self._hex_input.error_text = None
        self._refresh(rewrite=rewrite)

    def _edit_hex(self, event) -> None:
        if normalize_accent(event.control.value):
            self._set_hex(event.control.value, rewrite=False)

    def _submit_hex(self, event) -> None:
        if normalize_accent(self._hex_input.value):
            self._set_hex(self._hex_input.value)
        else:
            self._hex_input.error_text = "Enter a hex color, like #76C8F0."
            self._hex_input.height = 70
            if self._mounted:
                self.update()

    def _apply_color(self, event) -> None:
        if normalize_accent(self._hex_input.value) is None:
            self._submit_hex(event)
            return
        if self._on_apply(self.accent):
            self._saved = self.accent
            self._refresh()

    def _refresh(self, *, rewrite: bool = True) -> None:
        accent = self.accent
        palette = custom_theme(accent)
        angle = self._hue * 2 * pi
        self._marker.left = WHEEL_CENTER + cos(angle) * self._saturation * WHEEL_RADIUS - 9
        self._marker.top = WHEEL_CENTER + sin(angle) * self._saturation * WHEEL_RADIUS - 9
        self._marker.bgcolor = accent
        self._shade.opacity = 1 - self._brightness
        if rewrite:
            self._hex_input.value = accent
            self._hex_input.error_text = None
            self._hex_input.height = 48
        self._preview_dot.bgcolor = accent
        self._preview_selection.bgcolor = ft.Colors.with_opacity(0.16, accent)
        self._preview_selection.content.color = accent
        for button in (self._apply, self._preview_action):
            button.style.bgcolor = {
                ft.ControlState.DEFAULT: accent,
                ft.ControlState.HOVERED: palette["btn_primary_hover"],
                ft.ControlState.PRESSED: palette["btn_primary_active"],
            }
            button.style.color = palette["btn_primary_text"]
        values = (self._hue * 360, self._saturation * 100, self._brightness * 100)
        for index, (slider, label, value) in enumerate(zip(self._sliders, self._slider_labels, values)):
            slider.value = value
            slider.active_color = accent
            slider.thumb_color = accent
            label.value = f"{round(value)}{'°' if index == 0 else '%'}"
        for color, swatch in self._swatches:
            swatch.style.side = ft.BorderSide(2, "#FFFFFF" if color == accent else "#00FFFFFF")
        if self._mounted:
            self.update()
