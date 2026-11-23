"""Compact account rows and the classic two-pane account sign-in screen."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Callable
import uuid

import flet as ft

from wisc.core.credentials import redact_credentials
from wisc.core.paths import ASSETS_DIR
from wisc.services import auth as ely_auth
from wisc.services import skins
from wisc.core import storage
from wisc.ui.controls import (
    SimpleInput, launcher_back_button, launcher_button, launcher_icon_button,
    launcher_tab, select_tab,
)
from wisc.ui.scroll_views import ScrollColumn
from wisc.ui.glass import glass_panel


def account_avatar(account: dict, *, size: int = 40) -> ft.Control:
    return ft.Container(
        width=size, height=size, border_radius=8,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        content=ft.Image(src=skins.get_account_head_avatar_bytes(account, scale=4),
                         width=size, height=size, fit=ft.BoxFit.CONTAIN,
                         filter_quality=ft.FilterQuality.NONE),
    )


def build_accounts_view(
    *, theme: dict, accounts: list[dict], active_account: dict,
    on_add: Callable, on_login: Callable, on_switch: Callable,
    on_logout: Callable, on_sync: Callable, on_edit_offline: Callable,
    on_back: Callable,
) -> ft.Container:
    rows = []
    for account in accounts:
        name = account.get("username", "Player")
        is_ely = account.get("type") == "ely"
        is_active = account.get("id") == active_account.get("id")
        status = storage.get_account_storage_status(account)
        needs_login = is_ely and status == "missing"
        actions = []
        if needs_login:
            actions.append(launcher_button("Sign in", lambda e, a=account: on_login(a)))
        elif is_active:
            actions.append(ft.Row(
                [ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, size=16, color=theme["btn_primary"]),
                 ft.Text("Active", size=12, color=theme["btn_primary"])], spacing=6,
            ))
        else:
            actions.append(launcher_button("Select", lambda e, a=account: on_switch(a)))
        if is_ely:
            actions.extend([
                launcher_icon_button(icon=ft.Icons.REFRESH, tooltip="Sync skin from Ely.by",
                                     on_click=lambda e, a=account: on_sync(a)),
                launcher_icon_button(icon=ft.Icons.LOGOUT, tooltip="Log out of this Ely.by account",
                                     on_click=lambda e, a=account: on_logout(a)),
            ])
        elif is_active:
            actions.append(launcher_icon_button(
                icon=ft.Icons.EDIT_OUTLINED, tooltip="Edit offline username",
                on_click=lambda e: on_edit_offline(),
            ))
        detail = "Ely.by account" if is_ely else "Offline account"
        if needs_login:
            detail += " · Sign in again to play"
        elif status == "session":
            detail += " · Signed in for this session"
        rows.append(glass_panel(
            key=ft.ValueKey(f"account-{account['id']}"),
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            border_radius=12,
            bgcolor=theme["card"] if is_active else theme["surface"],
            border=ft.Border.all(1, theme["btn_primary"] if is_active else theme["border"]),
            content=ft.Row(
                [account_avatar(account),
                 ft.Column([
                     ft.Text(name, size=14, weight=ft.FontWeight.W_600,
                             color=theme["text_primary"], max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS),
                     ft.Text(detail, size=12, color=theme["text_secondary"], max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS),
                 ], spacing=3, expand=True),
                 ft.Row(actions, spacing=6)],
                spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ))
    view = ft.Container(
        expand=True, padding=ft.Padding.only(left=28, top=20, right=28, bottom=20),
        content=ft.Column([
            ft.Row([
                ft.Text("Accounts", size=24, weight=ft.FontWeight.BOLD,
                        color=theme["text_primary"], expand=True),
                launcher_back_button(lambda e: on_back(), label="Options"),
                launcher_button("Add Account", lambda e: on_add(), primary=True, height=40),
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                ft.Text("Manage Accounts", size=14, color=theme["text_secondary"]),
                ft.Text(f"{len(accounts)} saved", size=12, color=theme["text_secondary"]),
            ], spacing=12),
            ScrollColumn(rows, expand=True, scroll=ft.ScrollMode.AUTO, spacing=10,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )
    view.data = {"reveal_controls": rows[:5]}
    return view


def build_account_login(
    *, page: ft.Page, theme: dict, navigate: Callable, notify: Callable,
    open_url: Callable, on_account_changed: Callable, account: dict | None = None,
    features=None,
) -> ft.Container:
    alive = True
    mode = "ely"
    username = SimpleInput(
        label="Username or email", autofocus=True,
        value=(account.get("email") or account.get("username", "")) if account else "",
        hint_text="Your Ely.by username or email", fill_color=theme["card"],
    )
    password = SimpleInput(label="Password", password=True, can_reveal_password=True,
                           fill_color=theme["card"])
    totp = SimpleInput(label="2FA authenticator code", hint_text="6-digit code",
                       max_length=6, visible=False, fill_color=theme["card"])
    error = ft.Text(size=12, color="#ef5350", visible=False)
    busy = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False,
                           color=theme["btn_primary_text"])
    description = ft.Text("Use your Ely.by account for skins and Ely.by multiplayer.",
                          size=13, color=theme["text_secondary"])

    def cancel() -> None:
        nonlocal alive
        alive = False
        password.value = ""
        totp.value = ""

    def go_back(e=None) -> None:
        cancel()
        navigate("options_accounts")

    def set_error(message: str, *, two_factor: bool = False) -> None:
        error.value = redact_credentials(message)
        error.color = "#ffb74d" if two_factor else "#ef5350"
        error.visible = True

    def choose_mode(value: str) -> None:
        nonlocal mode
        if submit.disabled:
            return
        mode = value
        password.visible = mode == "ely"
        password.value = ""
        totp.value = ""
        totp.visible = False
        error.visible = False
        register.visible = mode == "ely"
        username.label = "Username or email" if mode == "ely" else "Player username"
        username.hint_text = "Your Ely.by username or email" if mode == "ely" else "1–16 letters, numbers, or _"
        username.max_length = None if mode == "ely" else 16
        description.value = ("Use your Ely.by account for skins and Ely.by multiplayer."
                             if mode == "ely" else "Create an offline account with a player name. Add a local skin and cape in Skins; only you will see them.")
        submit_label.value = "Log In" if mode == "ely" else "Add Account"
        select_tab(ely_tab, mode == "ely")
        select_tab(offline_tab, mode == "offline")
        page.update()

    async def revoke(auth_data: dict) -> None:
        try:
            await asyncio.to_thread(ely_auth.invalidate_token, auth_data["access_token"], auth_data["client_token"])
        except Exception:
            pass

    async def on_submit(e=None) -> None:
        if not alive or submit.disabled:
            return
        login = (username.value or "").strip()
        password_value = password.value or ""
        code = (totp.value or "").strip() if totp.visible else None
        if not login or (mode == "ely" and not password_value):
            set_error("Please enter both username/email and password." if mode == "ely" else "Username cannot be empty.")
            page.update()
            return
        if mode == "offline" and not re.fullmatch(r"[A-Za-z0-9_]{1,16}", login):
            set_error("Use 1–16 letters, numbers, or underscores.")
            page.update()
            return
        if mode == "ely" and totp.visible and not re.fullmatch(r"[0-9]{6}", code or ""):
            set_error("Please enter your 6-digit authenticator code.")
            page.update()
            return
        for control in (submit, ely_tab, offline_tab, username, password, totp):
            control.disabled = True
        busy.visible = True
        submit_label.value = "Authenticating..." if mode == "ely" else "Saving..."
        error.visible = False
        page.update()
        auth_data = None
        try:
            if mode == "ely":
                auth_data = await asyncio.to_thread(ely_auth.authenticate, login, password_value, code)
                if not alive:
                    await revoke(auth_data)
                    return
                new_account = {
                    "id": f"ely_{auth_data['uuid']}", "type": "ely", "username": auth_data["username"],
                    "email": login if "@" in login else "", "uuid": auth_data["uuid"],
                    "access_token": auth_data["access_token"], "client_token": auth_data["client_token"],
                    "created_at": time.time(),
                }
            else:
                existing = next((a for a in storage.load_accounts()["accounts"]
                                 if a.get("type") == "offline" and a.get("username", "").casefold() == login.casefold()), {})
                new_account = {**existing, "id": existing.get("id") or f"offline_{uuid.uuid4().hex}",
                               "type": "offline", "username": login, "created_at": existing.get("created_at", time.time())}
            if not storage.add_or_update_account(new_account, set_as_active=True):
                if auth_data:
                    await revoke(auth_data)
                raise RuntimeError("Could not save the account securely. Please try again.")
            password.value = ""
            totp.value = ""
            on_account_changed()
            navigate("options_accounts", force=True)
            if auth_data:
                page.run_task(cache_skin, new_account["username"])
            if storage.get_account_storage_status(storage.get_active_account()) == "session":
                notify("Signed in for this session. Sign in again after closing the launcher.", "warning", "Session sign-in")
            else:
                notify(f"{new_account['username']} is now your active account.", "success")
        except ely_auth.Ely2FARequiredError as exc:
            if alive:
                totp.visible = True
                set_error(str(exc), two_factor=True)
        except Exception as exc:
            if alive:
                set_error(str(exc))
        finally:
            if alive:
                for control in (submit, ely_tab, offline_tab, username, password, totp):
                    control.disabled = False
                busy.visible = False
                submit_label.value = ("Submit 2FA Code" if totp.visible else "Log In") if mode == "ely" else "Add Account"
                page.update()

    async def cache_skin(name: str) -> None:
        try:
            await asyncio.to_thread(skins.fetch_ely_skin, name, force_refresh=True)
            on_account_changed()
        except Exception:
            pass

    ely_tab = launcher_tab("Ely.by", lambda e: choose_mode("ely"))
    offline_tab = launcher_tab("Offline", lambda e: choose_mode("offline"))
    offline_tab.visible = account is None
    select_tab(ely_tab, True)
    submit_label = ft.Text("Log In", size=13, weight=ft.FontWeight.W_600)
    submit = launcher_button("Log In", on_submit, primary=True, height=40)
    submit.content = ft.Row([busy, submit_label], spacing=8, tight=True,
                            alignment=ft.MainAxisAlignment.CENTER)
    for field in (username, password, totp):
        field.on_submit = on_submit
    register = ft.TextButton(
        "Create an Ely.by account", icon=ft.Icons.OPEN_IN_NEW,
        style=ft.ButtonStyle(color=theme["btn_primary"],
                             shape=ft.RoundedRectangleBorder(radius=8)),
        on_click=lambda e: open_url("https://account.ely.by/register", "Opening Ely.by registration..."),
        tooltip="Open Ely.by registration",
    )
    form_card = glass_panel(
        expand=6, padding=24, bgcolor=theme["surface"], border_radius=12,
        border=ft.Border.all(1, theme["border"]),
        content=ft.Column([
            ScrollColumn([
                ft.Row([ely_tab, offline_tab], spacing=8), description,
                username, password, totp, error, register,
            ], expand=True, scroll=ft.ScrollMode.AUTO, spacing=16,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            ft.Row([launcher_button("Cancel", go_back, height=40), submit],
                   alignment=ft.MainAxisAlignment.END, spacing=8),
        ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )
    artwork = ASSETS_DIR / "banners" / "portal.png"
    branding_card = glass_panel(
        expand=5, padding=24, bgcolor=theme["surface"], border_radius=12,
        border=ft.Border.all(1, theme["border"]),
        content=ScrollColumn([
            ft.Container(height=180, border_radius=8, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                         content=ft.Stack([
                             ft.Image(src=artwork.read_bytes(), fit=ft.BoxFit.COVER,
                                      left=0, top=0, right=0, bottom=0),
                         ], height=180)),
            ft.Text("Your next adventure", size=20, weight=ft.FontWeight.W_600, color=theme["text_primary"]),
            ft.Text("Choose an account, then jump into your Minecraft worlds.", size=13, color=theme["text_secondary"]),
            ft.Divider(height=1, color=theme["border"]),
            ft.Text("Ely.by", size=14, weight=ft.FontWeight.W_600, color=theme["text_primary"]),
            ft.Text("Sign in to use your Ely.by skin and supported multiplayer servers.", size=13, color=theme["text_secondary"]),
            ft.Text("Offline", size=14, weight=ft.FontWeight.W_600, color=theme["text_primary"]),
            ft.Text("Save a player name for offline play. No password needed.", size=13, color=theme["text_secondary"]),
        ], expand=True, scroll=ft.ScrollMode.AUTO, spacing=14,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )
    view = ft.Container(
        expand=True, padding=ft.Padding.only(left=28, top=20, right=28, bottom=20),
        content=ft.Column([
            ft.Row([
                ft.Text("Login" if account else "Add Account", size=24, weight=ft.FontWeight.BOLD,
                        color=theme["text_primary"], expand=True),
                launcher_back_button(go_back, label="Accounts"),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([form_card, branding_card], expand=True, spacing=20,
                   vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        ], spacing=20, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )
    view.data = {"reveal_controls": [form_card, branding_card], "cancel": cancel}
    if features is not None:
        features.account_login_cancel = cancel
    return view
