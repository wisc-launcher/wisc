"""
Skins Management Tab and 3D Model Bridge UI for Wisc.
"""

import asyncio
import io
import os
import webbrowser
from PIL import Image
import flet as ft
from wisc.services import skins
from wisc.ui.skin_viewer import SkinViewer
from wisc.ui.glass import glass_panel
from wisc.ui.controls import launcher_button
from pathlib import Path
import hashlib
from wisc.core.storage import get_active_account
from wisc.core.state import player_name_state, active_page, launcher_log_state
from wisc.ui.components import (
    clickable_mouse_cursor,
    rounded_button_style,
    tooltip,
    create_ambient_gradient_orbs,
    animate_ambient_gradient_orbs,
)

def build_skins_view(page: ft.Page, theme: dict, notify, open_url=None, online_available=True, navigate=None, features=None):
    active_acc = get_active_account()
    is_offline_acc = active_acc.get("type") == "offline"
    offline_account_id = str(active_acc.get("id", ""))

    def current_choice():
        return skins.load_offline_cosmetics(offline_account_id) if is_offline_acc else skins.load_active_skin_choice()

    def is_online():
        return bool(online_available() if callable(online_available) else online_available)

    if open_url is None:
        def open_url(url, msg=""):
            try:
                if hasattr(os, "startfile"):
                    os.startfile(url)
                else:
                    webbrowser.open(url)
            except Exception:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            if msg and notify:
                notify(msg, ft.Icons.OPEN_IN_NEW)

    active_skin_data = current_choice()
    skin_model_state = {"value": active_skin_data.get("model", "classic")}
    skin_view_state = {"value": "3d"}

    status_dot = ft.Container(
        width=8,
        height=8,
        border_radius=4,
        bgcolor=theme["text_secondary"],
    )
    status_text = ft.Text(
        "Default Skin",
        size=12,
        color=theme["text_secondary"],
    )
    player_label = ft.Text(
        player_name_state["value"].strip() or "Offline Player",
        size=18,
        weight=ft.FontWeight.BOLD,
        color=theme["text_primary"],
    )

    cached_skin_im = [None]
    cached_skin_key = [""]

    is_init_classic = skin_model_state["value"] == "classic"
    model_badge_icon = ft.Icon(
        ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
        size=15,
        color=theme["btn_primary"],
    )
    model_badge_text = ft.Text(
        "Classic Model (Steve • 4px arms)" if is_init_classic else "Slim Model (Alex • 3px arms)",
        size=12,
        weight=ft.FontWeight.W_500,
        color=theme["text_primary"],
    )
    model_badge = ft.Container(
        content=ft.Row(
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[model_badge_icon, model_badge_text],
        ),
        padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        bgcolor=ft.Colors.with_opacity(0.08, theme["btn_primary"]),
        border=ft.Border.all(1, color=ft.Colors.with_opacity(0.2, theme["btn_primary"])),
        border_radius=8,
    )

    def get_effective_skin_image() -> Image.Image:
        uname = player_name_state["value"].strip()
        model = skin_model_state["value"]
        choice = current_choice()
        key = f"{uname}_{model}_{choice}"

        if cached_skin_key[0] == key and cached_skin_im[0] is not None:
            return cached_skin_im[0]

        raw = None
        if choice.get('skin_type') == 'custom' and choice.get('custom_path'):
            try:
                raw = Path(choice['custom_path']).read_bytes()
            except OSError:
                pass
        if choice.get('skin_type') == 'ely' and uname:
            cache_file = skins.get_skins_dir() / f"ely_{uname.lower()}.png"
            if cache_file.is_file():
                try:
                    raw = cache_file.read_bytes()
                except OSError:
                    pass

        im = None
        if raw:
            try:
                im = Image.open(io.BytesIO(raw))
            except Exception:
                pass
        if im is None:
            im = skins.get_default_skin(model)

        prepared = skins.ensure_64x64(im)
        cached_skin_im[0] = prepared
        cached_skin_key[0] = key

        # Automatically sync model detection from texture pixels
        if raw and im is not None:
            is_slim = skins.is_slim_skin(prepared)
            detected_model = "slim" if is_slim else "classic"
            if skin_model_state["value"] != detected_model:
                skin_model_state["value"] = detected_model
                model_badge_text.value = (
                    "Classic Model (Steve • 4px arms)"
                    if detected_model == "classic"
                    else "Slim Model (Alex • 3px arms)"
                )
                try:
                    model_badge_text.update()
                except Exception:
                    pass

        return prepared

    def invalidate_skin_cache():
        cached_skin_im[0] = None
        cached_skin_key[0] = ""


    def render_current_character() -> bytes:
        skin_im = get_effective_skin_image()
        cape_path = current_choice().get("cape_path", "")
        key = (id(skin_im), skin_model_state['value'], cape_path)
        if renderer_key[0] != key:
            cape_image = None
            if cape_path:
                try:
                    with Image.open(cape_path) as cape:
                        cape_image = cape.convert("RGBA")
                except (OSError, ValueError):
                    pass
            viewer.set_renderer(skins.SkinRenderer(skin_im, skin_model_state['value'], 'hero', cape=cape_image))
            renderer_key[0] = key
        return viewer.render_still()

    skin_image = ft.Image(
        src=b"",
        fit=ft.BoxFit.CONTAIN,
        width=240,
        height=340,
        filter_quality=ft.FilterQuality.NONE,
        gapless_playback=True,
    )

    viewer = SkinViewer(page, skin_image, lambda: active_page.get('name') == 'skins')
    renderer_key = [None]
    if features:
        features.skin_viewer = viewer

    def update_preview():
        skin_image.src = render_current_character()
        try:
            skin_image.update()
        except Exception:
            pass

    active_pill_style = ft.ButtonStyle(
        bgcolor={
            ft.ControlState.DEFAULT: theme["btn_primary"],
            ft.ControlState.DISABLED: theme["surface"],
        },
        color={
            ft.ControlState.DEFAULT: theme.get("btn_primary_text", "#FFFFFF"),
            ft.ControlState.DISABLED: theme.get("text_muted", theme["text_secondary"]),
        },
        side={
            ft.ControlState.DEFAULT: ft.BorderSide(0, ft.Colors.TRANSPARENT),
            ft.ControlState.DISABLED: ft.BorderSide(1, color=theme["border"]),
        },
        shape=ft.RoundedRectangleBorder(radius=8),
        mouse_cursor=clickable_mouse_cursor,
        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
    )
    inactive_pill_style = ft.ButtonStyle(
        bgcolor={
            ft.ControlState.HOVERED: theme.get("card_hover", theme["card"]),
            ft.ControlState.DEFAULT: theme["card"],
            ft.ControlState.DISABLED: theme["surface"],
        },
        color={
            ft.ControlState.DEFAULT: theme["text_secondary"],
            ft.ControlState.DISABLED: theme.get("text_muted", theme["text_secondary"]),
        },
        side={
            ft.ControlState.HOVERED: ft.BorderSide(1, color=theme["btn_primary"]),
            ft.ControlState.DEFAULT: ft.BorderSide(1, color=theme["border"]),
            ft.ControlState.DISABLED: ft.BorderSide(1, color=theme["border"]),
        },
        shape=ft.RoundedRectangleBorder(radius=8),
        mouse_cursor=clickable_mouse_cursor,
        padding=ft.Padding.symmetric(horizontal=14, vertical=8),
    )

    def highlight_active_view(view_name):
        view_front_btn.style = active_pill_style if view_name == "front" else inactive_pill_style
        view_back_btn.style = active_pill_style if view_name == "back" else inactive_pill_style
        try:
            view_front_btn.update()
            view_back_btn.update()
        except Exception:
            pass



    def handle_pan_start(e):
        viewer.begin_drag()

    def handle_pan_update(e):
        delta = getattr(e, 'local_delta', None) or getattr(e, 'global_delta', None)
        dx = getattr(delta, 'x', 0.0) if delta else getattr(e, 'delta_x', 0.0)
        dy = getattr(delta, 'y', 0.0) if delta else getattr(e, 'delta_y', 0.0)
        skin_view_state['value'] = '3d'
        highlight_active_view('3d')
        viewer.drag(dx or 0.0, dy or 0.0)

    def handle_pan_end(e):
        viewer.end_drag()

    def handle_double_tap(e):
        skin_view_state['value'] = '3d'
        highlight_active_view('3d')
        viewer.turn_to(-25.0, 10.0)

    skin_gesture = ft.GestureDetector(
        content=skin_image,
        mouse_cursor=ft.MouseCursor.GRAB,
        drag_interval=16,
        on_pan_start=handle_pan_start,
        on_pan_update=handle_pan_update,
        on_pan_end=handle_pan_end,
        on_double_tap=handle_double_tap,
    )

    def set_view(view_name):
        skin_view_state['value'] = view_name
        highlight_active_view(view_name)
        yaw, pitch = {'3d': (-25.0, 10.0), 'front': (0.0, 0.0), 'back': (180.0, 0.0)}[view_name]
        viewer.turn_to(yaw, pitch)

    view_front_btn = ft.Button(
        "Front",
        style=inactive_pill_style,
        on_click=lambda e: set_view("front"),
    )
    view_back_btn = ft.Button(
        "Back",
        style=inactive_pill_style,
        on_click=lambda e: set_view("back"),
    )

    def set_model(model_name):
        skin_model_state["value"] = model_name
        is_classic = (model_name == "classic")
        model_badge_text.value = (
            "Classic Model (Steve • 4px arms)"
            if is_classic
            else "Slim Model (Alex • 3px arms)"
        )
        try:
            model_badge_text.update()
        except Exception:
            pass
        choice = current_choice()
        if not is_offline_acc:
            skins.save_active_skin_choice(choice.get('skin_type', 'ely'), model=model_name, custom_path=choice.get('custom_path', ''))
        invalidate_skin_cache()
        update_preview()
        ref_acc = launcher_log_state.get("refresh_account_picture")
        if callable(ref_acc):
            ref_acc()

    async def sync_skin_network(force=False):
        if is_offline_acc:
            choice = current_choice()
            status_dot.bgcolor = theme['btn_primary']
            status_text.value = "Local skin & cape" if choice['custom_path'] and choice['cape_path'] else "Local skin" if choice['custom_path'] else "Local cape" if choice['cape_path'] else "Default skin"
            invalidate_skin_cache()
            update_preview()
            page.update()
            return
        if current_choice().get('skin_type') == 'custom':
            status_dot.bgcolor = theme['btn_primary']
            status_text.value = 'Custom Skin'
            invalidate_skin_cache()
            update_preview()
            page.update()
            return
        uname = player_name_state["value"].strip()
        if not uname:
            status_dot.bgcolor = theme["text_secondary"]
            status_text.value = "Default Skin"
            invalidate_skin_cache()
            update_preview()
            page.update()
            return

        if not is_online() and force:
            notify("Cannot check for updated skin while offline.", ft.Icons.WIFI_OFF)
            return

        if not is_online():
            invalidate_skin_cache()
            raw_check = get_effective_skin_image()
            if raw_check != skins.get_default_skin(skin_model_state["value"]):
                status_dot.bgcolor = ft.Colors.GREEN_400
                status_text.value = "Skin Active (Offline)"
            else:
                status_dot.bgcolor = theme["text_secondary"]
                status_text.value = "Default Skin"
            update_preview()
            try:
                status_dot.update()
                status_text.update()
            except Exception:
                pass
            return

        status_text.value = "Checking skin..."
        status_dot.bgcolor = ft.Colors.AMBER_400
        try:
            status_text.update()
            status_dot.update()
        except Exception:
            pass

        skin_bytes, detected_model = await asyncio.to_thread(
            skins.fetch_ely_skin, uname, force_refresh=force, timeout=6.0
        )
        invalidate_skin_cache()
        if skin_bytes:
            status_dot.bgcolor = ft.Colors.GREEN_400
            status_text.value = "Skin Active"
            set_model(detected_model)
        else:
            status_dot.bgcolor = theme["text_secondary"]
            status_text.value = "Default Skin"
            update_preview()
        try:
            status_dot.update()
            status_text.update()
        except Exception:
            pass
        ref_acc = launcher_log_state.get("refresh_account_picture")
        if callable(ref_acc):
            ref_acc()

    skin_image.src = render_current_character()
    page.run_task(sync_skin_network, False)

    def handle_refresh(e):
        if not is_online():
            notify("Cannot refresh skin while offline.", ft.Icons.WIFI_OFF)
            return
        notify("Checking for updated skin...", ft.Icons.REFRESH)
        page.run_task(sync_skin_network, True)

    file_picker = features.file_picker if features else ft.FilePicker()
    if not features:
        page.services.append(file_picker)

    async def choose_custom_skin(e):
        files = await file_picker.pick_files(allow_multiple=False, allowed_extensions=['png'], file_type=ft.FilePickerFileType.CUSTOM)
        if not files or not files[0].path:
            return
        try:
            if is_offline_acc:
                await upload_offline_cosmetic("skin", files[0].path)
                return
            with Image.open(files[0].path) as image:
                if image.size not in ((64, 64), (64, 32)):
                    raise ValueError('Choose a 64x64 or legacy 64x32 Minecraft skin.')
                prepared = skins.ensure_64x64(image.convert('RGBA'))
                model = 'slim' if skins.is_slim_skin(prepared) else 'classic'
                output = io.BytesIO()
                prepared.save(output, format='PNG')
            path = skins.get_skins_dir() / ('custom_' + hashlib.sha256(output.getvalue()).hexdigest()[:20] + '.png')
            path.write_bytes(output.getvalue())
            if not skins.save_active_skin_choice('custom', model=model, custom_path=str(path)):
                raise OSError('Could not save your selected skin.')
            skin_model_state['value'] = model
            model_badge_text.value = 'Slim Model (Alex \u2022 3px arms)' if model == 'slim' else 'Classic Model (Steve \u2022 4px arms)'
            model_badge_text.update()
            invalidate_skin_cache()
            update_preview()
            status_dot.bgcolor = theme['btn_primary']
            status_text.value = 'Custom Skin'
            status_dot.update()
            status_text.update()
            if callable(launcher_log_state.get('refresh_account_picture')):
                launcher_log_state['refresh_account_picture']()
            notify('Custom skin selected.', ft.Icons.CHECK_CIRCLE)
        except (OSError, ValueError) as error:
            notify(str(error), ft.Icons.ERROR_OUTLINE)

    def use_ely_skin(e):
        if not skins.save_active_skin_choice('ely', model=skin_model_state['value']):
            notify('Could not save your skin choice.', ft.Icons.ERROR_OUTLINE)
            return
        invalidate_skin_cache()
        update_preview()
        page.run_task(sync_skin_network, False)

    cape_status = ft.Text("Cape selected" if active_skin_data.get("cape_path") else "No cape selected",
                          size=12, color=theme["text_secondary"])

    def refresh_offline_cosmetics():
        choice = current_choice()
        skin_model_state["value"] = choice["model"]
        model_badge_text.value = "Slim Model (Alex • 3px arms)" if choice["model"] == "slim" else "Classic Model (Steve • 4px arms)"
        cape_status.value = "Cape selected" if choice["cape_path"] else "No cape selected"
        remove_cape_button.visible = bool(choice["cape_path"])
        invalidate_skin_cache()
        renderer_key[0] = None
        update_preview()
        page.run_task(sync_skin_network, False)
        refresh = launcher_log_state.get("refresh_account_picture")
        if callable(refresh):
            refresh()
        page.update()

    async def upload_offline_cosmetic(kind, path):
        if str(get_active_account().get("id", "")) != offline_account_id:
            raise ValueError("Your active account changed. Choose the file again for that account.")
        await asyncio.to_thread(skins.save_offline_cosmetic, offline_account_id, kind, path)
        refresh_offline_cosmetics()
        notify(f"Offline {kind} selected. Visible only to you on your next launch.", ft.Icons.CHECK_CIRCLE)

    async def choose_offline_cape(e):
        files = await file_picker.pick_files(allow_multiple=False, allowed_extensions=['png'], file_type=ft.FilePickerFileType.CUSTOM)
        if not files or not files[0].path:
            return
        try:
            await upload_offline_cosmetic("cape", files[0].path)
        except (OSError, ValueError) as error:
            notify(str(error), ft.Icons.ERROR_OUTLINE)

    def clear_offline(kind):
        if not skins.clear_offline_cosmetic(offline_account_id, kind):
            notify(f"Could not remove the offline {kind}.", ft.Icons.ERROR_OUTLINE)
            return
        refresh_offline_cosmetics()

    remove_cape_button = launcher_button("Remove cape", lambda e: clear_offline("cape"),
                                        visible=bool(active_skin_data.get("cape_path")))

    custom_skin_controls = ft.Row([
        ft.Button('Choose skin PNG', on_click=choose_custom_skin, disabled=page.web,
                  bgcolor=theme['btn_secondary'], color=theme['text_primary']),
        launcher_button('Reset skin', lambda e: clear_offline("skin")) if is_offline_acc else
        ft.TextButton('Use Ely.by skin', on_click=use_ely_skin)], wrap=True)
    refresh_skin_btn = ft.Button(
        "Refresh",
        icon=ft.Icons.REFRESH,
        style=inactive_pill_style,
        disabled=not is_online(),
        tooltip=tooltip("Internet connection required to refresh") if not is_online() else None,
        on_click=handle_refresh,
    )
    manage_skin_btn = ft.Button(
        "Manage Skin Online",
        icon=ft.Icons.OPEN_IN_NEW,
        style=active_pill_style,
        disabled=not is_online(),
        tooltip=tooltip("Internet connection required") if not is_online() else None,
        on_click=lambda e: open_url("https://ely.by/skins", "Opening skin manager..."),
    )
    launcher_log_state["skin_refresh_button"] = refresh_skin_btn
    launcher_log_state["skin_manage_button"] = manage_skin_btn
    launcher_log_state["skin_sync_task"] = sync_skin_network

    drag_hint = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=6,
        controls=[
            ft.Icon(ft.Icons.ROTATE_RIGHT, size=13, color=theme["text_secondary"]),
            ft.Text("Drag to rotate 360° • Double-click to reset", size=11, color=theme["text_secondary"]),
        ],
    )

    left_preview_card = glass_panel(
        width=330,
        padding=22,
        bgcolor=theme["surface"],
        border=ft.Border.all(1, color=theme["border"]),
        border_radius=16,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=14,
            controls=[
                ft.Container(
                    content=skin_gesture,
                    alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.only(top=5, bottom=5),
                ),
                ft.Row(
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=8,
                    controls=[
                        view_front_btn,
                        view_back_btn,
                    ],
                ),
                drag_hint,
            ],
        ),
    )

    right_settings_card = glass_panel(
        width=460,
        padding=28,
        bgcolor=theme["surface"],
        border=ft.Border.all(1, color=theme["border"]),
        border_radius=16,
        content=ft.Column(
            spacing=22,
            controls=[
                ft.Column(
                    spacing=6,
                    controls=[
                        ft.Text("OFFLINE SKIN & CAPE" if is_offline_acc else "PLAYER", size=11, weight=ft.FontWeight.BOLD, color=theme["text_secondary"]),
                        player_label,
                        ft.Row(
                            spacing=8,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[status_dot, status_text],
                        ),
                        ft.Container(height=6),
                        ft.Row(
                            visible=not is_offline_acc,
                            spacing=10,
                            controls=[
                                refresh_skin_btn,
                                manage_skin_btn,
                            ],
                        ),
                    ],
                ),
                ft.Divider(color=ft.Colors.with_opacity(0.12, theme["border"])),
                ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("CHARACTER MODEL", size=11, weight=ft.FontWeight.BOLD, color=theme["text_secondary"]),
                        model_badge,
                        custom_skin_controls,
                    ],
                ),
                *([ft.Column([
                    ft.Text("OFFLINE CAPE", size=11, weight=ft.FontWeight.BOLD, color=theme["text_secondary"]),
                    ft.Text("Upload a 64×32 cape PNG, or the same layout at a larger size.", size=12, color=theme["text_secondary"]),
                    cape_status,
                    ft.Row([
                        launcher_button("Choose cape PNG", choose_offline_cape, disabled=page.web),
                        remove_cape_button,
                    ], spacing=8, wrap=True),
                ], spacing=8)] if is_offline_acc else []),
            ],
        ),
    )

    footer_credit = ft.Container(
        content=ft.Text(
            "Visible only in your own game client. Other players see your normal appearance." if is_offline_acc else "Skin network powered by Ely.by",
            size=11,
            color=ft.Colors.with_opacity(0.5, theme["text_secondary"]),
            text_align=ft.TextAlign.CENTER,
        ),
        alignment=ft.Alignment.CENTER,
        padding=ft.Padding.only(top=14),
    )

    skins_orb1, skins_orb2 = create_ambient_gradient_orbs(theme)
    page.run_task(
        animate_ambient_gradient_orbs,
        skins_orb1,
        skins_orb2,
        lambda: active_page.get("name") == "skins",
    )

    main_skins_content = ft.Row(
        alignment=ft.MainAxisAlignment.CENTER,
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=24,
        controls=[left_preview_card, right_settings_card],
    )

    return ft.Stack(
        expand=True,
        alignment=ft.Alignment.CENTER,
        controls=[
            skins_orb1,
            skins_orb2,
            ft.Container(
                alignment=ft.Alignment.CENTER,
                padding=ft.Padding.symmetric(horizontal=20, vertical=16),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    scroll=ft.ScrollMode.AUTO,
                    controls=[
                        main_skins_content,
                        footer_credit,
                    ],
                ),
            ),
        ],
    )
