"""
State management module for Wisc.
Holds shared runtime state to avoid closure-nesting and prevent control de-synchronization.
"""

from typing import Any, Dict
from wisc.core.themes import DEFAULT_THEME

# Central launch and logging state
launcher_log_state: Dict[str, Any] = {
    "lines": [],
    "list": None,
    "open": False,
    "running": False,
    "downloading": False,
    "game_started": False,
    "cancelling": False,
    "cancel_event": None,
    "play_button": None,
    "refresh_play_button": None,
    "target_version_id": None,
    "target_profile_id": None,
    "status": None,
    "progress": 0,
    "eta": "",
    "floating_logs_window": None,
    "bottom_log_toggle_button": None,
}

# Navigation and page state
active_page: Dict[str, Any] = {
    "name": "home",
    "profile_id": None,
}

navigation_state: Dict[str, Any] = {
    "navigate": None,
}

selected_theme: Dict[str, Any] = {
    "name": DEFAULT_THEME,
}

refresh_state: Dict[str, Any] = {
    "running": False,
}

connectivity_known: Dict[str, Any] = {
    "value": False,
}

intro_state: Dict[str, Any] = {
    "pending": True,
    "running": False,
    "targets": [],
}

options_background_state: Dict[str, Any] = {
    "animation_running": False,
}

danger_zone_state: Dict[str, Any] = {
    "expanded": False,
}

player_name_state: Dict[str, Any] = {
    "value": "Player",
}

profile_picture_state: Dict[str, Any] = {
    "path": "",
}

launch_selection: Dict[str, Any] = {
    "key": None,
}
