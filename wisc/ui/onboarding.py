"""A short, replayable introduction to Wisc with a live palette preview."""

from pathlib import Path
from typing import Callable

import flet as ft

from wisc.core.themes import DEFAULT_CUSTOM_ACCENT, get_theme, get_theme_names
from wisc.ui.glass import GLASS_MUTED, GLASS_TEXT, glass_palette, glass_panel
from wisc.ui.motion import StaggeredReveal


class OnboardingView(ft.Container):
    """Keep draft choices local until the user finishes or explicitly skips."""

    STEPS = ("Welcome", "Palette", "Start")
    DESTINATIONS = (
        ("home", "Open launcher", "Go straight to your library.", ft.Icons.PLAY_ARROW),
        ("account_login", "Add an account", "Use Ely.by or choose an offline player name.", ft.Icons.PERSON_ADD_OUTLINED),
        ("new_installation", "Create a profile", "Choose a Minecraft version and mod loader.", ft.Icons.ADD_BOX_OUTLINED),
    )

    def __init__(self, *, page: ft.Page, theme_name: str, assets_dir: Path,
                 artwork_source: str, on_complete: Callable[[str, str], bool],
                 custom_accent: str = DEFAULT_CUSTOM_ACCENT):
        self._ui_page = page
        self._initial_theme = theme_name
        self.theme_name = theme_name
        self._custom_accent = custom_accent
        self.step = 0
        self.destination = "home"
        self._on_complete = on_complete
        self._mounted = False
        self._finishing = False
        cover = Path(artwork_source)
        self._artwork_label = cover.stem.replace("-", " ").title() if cover.parent.name == "version-art" else "Your artwork"
        self._host = ft.Container(expand=True)
        self._reveal = StaggeredReveal(page, self._host)
        self._steps = ft.Row(spacing=18)
        self._dots = ft.Row(spacing=6, tight=True)
        self._back = ft.TextButton("Back", icon=ft.Icons.ARROW_BACK,
                                   on_click=lambda e: self.go_to(self.step - 1))
        self._next = ft.Button(on_click=self._advance, width=178, height=46)
        self._skip = ft.TextButton("Skip", on_click=self._skip_setup)
        super().__init__(
            key=ft.ValueKey("wisc-onboarding"), expand=True,
            content=ft.Stack([
                ft.Container(left=0, top=0, right=0, bottom=0, ignore_interactions=True,
                             gradient=ft.LinearGradient(
                                 begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT,
                                 colors=["#B30B0D0A", "#5C0B0D0A", "#000B0D0A"], stops=[0, 0.4, 0.75])),
                ft.Container(padding=ft.Padding.symmetric(horizontal=40, vertical=28),
                             content=ft.Column([
                ft.Row([self._steps, self._skip], height=36,
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self._host,
                ft.Row([
                    ft.Container(self._back, width=178), self._dots, self._next,
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, height=46),
            ], expand=True, spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
            ], expand=True, fit=ft.StackFit.EXPAND),
        )
        self._render(animate=False)

    @property
    def palette(self) -> dict:
        return glass_palette(get_theme(self.theme_name, self._custom_accent))

    def did_mount(self) -> None:
        self._mounted = True
        self._render()

    def will_unmount(self) -> None:
        self._mounted = False
        self._reveal.finish(update=False)

    def go_to(self, step: int) -> None:
        if self._finishing or not 0 <= step < len(self.STEPS):
            return
        self.step = step
        self._render()

    def choose_theme(self, name: str) -> None:
        if self._finishing or name not in get_theme_names():
            return
        self.theme_name = name
        self._render(animate=False)

    def choose_destination(self, destination: str) -> None:
        if self._finishing or destination not in {item[0] for item in self.DESTINATIONS}:
            return
        self.destination = destination
        self._render(animate=False)

    def _advance(self, event=None) -> None:
        if self.step < len(self.STEPS) - 1:
            self.go_to(self.step + 1)
        else:
            self._finish(self.theme_name, self.destination)

    def _skip_setup(self, event=None) -> None:
        self._finish(self._initial_theme, "home")

    def _finish(self, theme_name: str, destination: str) -> None:
        if self._finishing:
            return
        self._finishing = True
        self._next.disabled = self._skip.disabled = True
        if self._mounted:
            self.update()
        if not self._on_complete(theme_name, destination):
            self._finishing = False
            self._next.disabled = self._skip.disabled = False
            if self._mounted:
                self.update()

    def _button_style(self, *, selected: bool = False, primary: bool = False) -> ft.ButtonStyle:
        palette = self.palette
        accent = palette["btn_primary"]
        return ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT: accent if primary else ft.Colors.with_opacity(0.17, accent) if selected else palette["card"],
                ft.ControlState.HOVERED: palette["btn_primary_hover"] if primary else palette["card_hover"],
            },
            color=palette["btn_primary_text"] if primary else GLASS_TEXT,
            side={
                ft.ControlState.DEFAULT: ft.BorderSide(1.5, accent) if selected else ft.BorderSide(0, ft.Colors.TRANSPARENT),
                ft.ControlState.FOCUSED: ft.BorderSide(2, accent),
            },
            overlay_color=ft.Colors.with_opacity(0.12, accent),
            elevation=0, padding=12, shape=ft.RoundedRectangleBorder(radius=8),
            mouse_cursor=ft.MouseCursor.CLICK,
        )

    def _heading(self, eyebrow: str, title: str, description: str, *, size: int = 48) -> list[ft.Control]:
        return [
            ft.Text(eyebrow, size=11, color=GLASS_MUTED),
            ft.Text(title, size=size,
                    weight=ft.FontWeight.BOLD, color=GLASS_TEXT),
            ft.Text(description, size=14, color=GLASS_MUTED),
        ]

    def _welcome(self) -> list[ft.Control]:
        return self._heading("WELCOME", "Welcome\nto Wisc.",
                             "Choose your colors and where to start.", size=54)

    def _themes(self) -> list[ft.Control]:
        choices = []
        names = get_theme_names()
        names = [self._initial_theme, *[name for name in names if name != self._initial_theme]]
        for name in names:
            accent = get_theme(name, self._custom_accent)["btn_primary"]
            selected = name == self.theme_name
            choices.append(ft.Button(
                key=ft.ValueKey(f"onboarding-theme-{name}"), width=196, height=54,
                tooltip=f"Choose {name}", style=self._button_style(selected=selected),
                on_click=lambda e, choice=name: self.choose_theme(choice),
                content=ft.Row([
                    ft.Container(width=22, height=22, border_radius=6, bgcolor=accent),
                    ft.Text(name, size=13, expand=True),
                    ft.Icon(ft.Icons.CHECK, size=16, color=self.palette["btn_primary"], visible=selected),
                ], spacing=10),
            ))
        return [
            *self._heading("APPEARANCE", "Choose a palette.",
                           "You can change this in Options.", size=36),
            ft.Row(choices, spacing=10, run_spacing=10, wrap=True),
        ]

    def _destinations(self) -> list[ft.Control]:
        choices = []
        for destination, title, description, icon in self.DESTINATIONS:
            selected = destination == self.destination
            choices.append(ft.Button(
                key=ft.ValueKey(f"onboarding-start-{destination}"), height=74,
                tooltip=title, style=self._button_style(selected=selected),
                on_click=lambda e, choice=destination: self.choose_destination(choice),
                content=ft.Row([
                    ft.Icon(icon, size=22, color=self.palette["btn_primary"]),
                    ft.Column([ft.Text(title, size=14, weight=ft.FontWeight.W_600),
                               ft.Text(description, size=12, color=GLASS_MUTED)],
                              spacing=4, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                    ft.Icon(ft.Icons.CHECK_CIRCLE if selected else ft.Icons.RADIO_BUTTON_UNCHECKED,
                            size=19, color=self.palette["btn_primary"] if selected else GLASS_MUTED),
                ], spacing=12),
            ))
        return [
            *self._heading("READY", "Start here.", "Choose what opens next.", size=44),
            *choices,
        ]

    def _scene(self) -> ft.Control:
        accent = self.palette["btn_primary"]
        return ft.Container(
            alignment=ft.Alignment.BOTTOM_RIGHT, padding=ft.Padding.only(bottom=12),
            content=glass_panel(
                padding=ft.Padding.symmetric(horizontal=14, vertical=11), border_radius=8,
                content=ft.Row([
                    ft.Container(width=7, height=7, border_radius=4, bgcolor=accent),
                    ft.Text(self._artwork_label, size=11, color=GLASS_MUTED),
                ], spacing=8, tight=True),
            ), ignore_interactions=True,
        )

    def _render(self, *, animate: bool = True) -> None:
        accent = self.palette["btn_primary"]
        self._steps.controls = [
            ft.Row([
                ft.Container(width=24, height=24, border_radius=6,
                             bgcolor=accent if index == self.step else "#550B0D0A",
                             alignment=ft.Alignment.CENTER,
                             content=ft.Text(str(index + 1), size=11,
                                             color=self.palette["btn_primary_text"] if index == self.step else GLASS_MUTED)),
                ft.Text(label, size=12, color=GLASS_TEXT if index == self.step else GLASS_MUTED),
            ], spacing=7, tight=True) for index, label in enumerate(self.STEPS)
        ]
        self._dots.controls = [ft.Container(width=24 if index == self.step else 7, height=7,
                                           border_radius=4, bgcolor=accent if index == self.step else "#66899582",
                                           animate_size=ft.Animation(200, ft.AnimationCurve.EASE_OUT))
                               for index in range(len(self.STEPS))]
        self._back.visible = self.step > 0
        for control in (self._back, self._skip):
            control.style = ft.ButtonStyle(color=GLASS_MUTED, overlay_color=ft.Colors.with_opacity(0.12, accent))
        self._next.style = self._button_style(primary=True)
        label = "Continue" if self.step < 2 else {
            "home": "Open Wisc", "account_login": "Add account", "new_installation": "Create profile",
        }[self.destination]
        self._next.content = ft.Row([ft.Text(label, size=13, weight=ft.FontWeight.W_600),
                                    ft.Icon(ft.Icons.ARROW_FORWARD, size=18)], tight=True,
                                   spacing=10, alignment=ft.MainAxisAlignment.CENTER)
        controls = (self._welcome, self._themes, self._destinations)[self.step]()
        left = ft.Container(expand=6, content=ft.Column(
            controls, expand=True, spacing=14 if self.step == 0 else 10,
            scroll=ft.ScrollMode.AUTO, alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ))
        right = ft.Container(expand=5, content=self._scene(), alignment=ft.Alignment.CENTER)
        body = ft.Row([left, right], expand=True, spacing=40,
                      vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        if self._mounted:
            self._reveal.show(body, [left, right], animate=animate)
            self.update()
        else:
            self._host.content = body
