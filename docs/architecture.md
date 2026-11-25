# Code map

Run `python main.py` from the repository root. The entry point runs the Windows
updater guard before importing the UI, then calls `wisc.app.run()`.
`wisc/app.py` owns navigation, page wiring, launch actions, and background
tasks. All application imports use the `wisc` package.

| Area | Modules |
| --- | --- |
| Home, onboarding, and library | `ui/home.py`, `ui/onboarding.py`, `ui/library.py`, `ui/profiles.py` |
| Accounts and profile editing | `ui/accounts.py`, `ui/installations.py`, `ui/profile_assets.py` |
| Options and skins | `ui/options.py`, `ui/skins.py`, `ui/skin_viewer.py` |
| Mods, modpacks, shaders, and texture packs | `ui/mods.py`, `ui/modpacks.py`, `ui/content_packs.py`, `ui/mod_details.py`, `ui/mod_install.py`, `ui/mod_list.py` |
| Shared UI and window artwork | `ui/glass.py`, `ui/shell.py`, `ui/components.py`, `ui/controls.py`, `ui/dialogs.py`, `ui/theme.py`, `ui/scroll_views.py`, `ui/motion.py` |
| Feature lifecycle and feedback | `ui/features.py`, `ui/progress.py`, `ui/toasts.py`, `ui/updates.py` |
| Minecraft install and launch | `services/launcher.py` |
| Local discovery, connectivity, game logs, and profile operations | `services/instances.py`, `services/profiles.py` |
| Accounts, skins, artwork, and Discord | `services/auth.py`, `services/skins.py`, `services/artwork.py`, `services/banners.py`, `services/discord_presence.py` |
| Launcher update discovery and handoff | `services/updates.py`, `tools/updater/Program.cs` |
| Mod and content management and providers | `mods/manager.py`, `mods/content.py`, `mods/platform.py`, `mods/curseforge.py` |
| Compatibility, descriptions, and modpacks | `mods/compatibility.py`, `mods/markdown.py`, `mods/modpacks.py` |
| Settings, profiles, and secrets | `core/storage.py`, `core/credentials.py` |
| Shared runtime state and palettes | `core/state.py`, `core/themes.py` |

Python paths in the table are relative to `wisc/`; `tools/` paths start at
the repository root. Keep Flet controls in `ui/`
and application wiring in `app.py`; core, mod, and service code works without
initializing a UI. Package initializers do not import their child modules.
Some launch/profile/modpack operations use local imports to avoid circular
dependencies; preserve that initialization order when moving code.

## Qt migration preview

The standalone PyQt6 Home, Library, Skins, and content UI runs with `python -m wisc.qt_app`. Install its
dependency with `python -m pip install -r requirements-qt.txt` if needed.
`wisc/qt_app.py` owns the preview window; `ui/qt_home.py`, `ui/qt_components.py`,
and `ui/qt_theme.py` provide Home, shared artwork/glass controls, and styling.
Keep Qt colors, fonts, border radii, painter appearance tokens, and stylesheet
rules in `ui/qt_theme.py`; widget modules own layout and interaction.
The window constructs Home first, warms Library's Python modules after the first
paint, and creates secondary pages on demand. Page preparation runs on the
service worker; Qt widgets are always constructed on the GUI thread.
`ui/qt_library.py` uses the shared content model/view grid and profile-card painters
to display only visible cards, with search, loader filters, and sorting.
Home retains only the three or four visible shelf cards.
`ui/qt_skins.py` loads the active launcher account on opening Skins and reuses
the existing skin cache and Ely.by services. Skin changes happen on Ely.by;
refreshing updates the preview and uses the model provided by Ely.by. `ui/qt_skin_viewer.py`
publishes software-rendered frames with drag/keyboard rotation and view presets.
`ui/qt_tasks.py` owns the background service loop and queued delivery to Qt;
its executor has four workers. Hidden skin previews stop scheduling frames,
retain at most one running render, and replace pending poses with the latest one.
`ui/qt_mods.py` loads saved profiles on opening Mods and connects the existing
mod, modpack, shader, and texture pack services. `ui/qt_content.py` provides
native list models/delegates, local filtering,
pagination, and Markdown. `ui/qt_content_details.py` and `ui/qt_content_install.py`
share details and nonblocking reviews across those content types. Searches
coalesce into one running request and one pending replacement. `ui/qt_progress.py`
owns one persistent bottom progress bar for Home operations, content downloads,
skin refreshes, and page loading. Active operations retain their progress and
cancellation across navigation; the status row hides when idle. Higher-priority
operations stay visible while background work finishes. Artwork gradients fade
from the sides and bottom across Qt tabs, including their glass controls. Home
retains full-strength shading; secondary pages use the same selected artwork
with blur and gradients at 60% of Home's strength.
Content details are constructed on first use. `ui/qt_images.py` supplies a shared
32 MiB decoded-image cache and four decode slots across Home, Library, backgrounds,
and content views. Image consumers suspend queued requests while hidden. Backgrounds
decode for the current window size/DPR, and the Library's rendered-card cache is
limited to 4 MiB. Confirmed installs keep their existing cancellation and commit guards.
`LauncherComboBox` in `ui/qt_components.py` supplies the shared glass dropdown,
with content-based widths, configurable field heights, and rounded menus bounded
to the launcher window.
`ui/qt_window.py` owns the custom title bar and shared Qt window actions.
`ui/qt_geometry.py` uses Qt system move/resize with a manual geometry fallback;
`ui/qt_native.py` is loaded only by the optional Windows integration.
The preview uses bundled sample profiles, shares selection between Home and Library,
supports theme changes, and exposes signals for service actions. Skins reads
the active launcher account and synchronizes Ely.by skins with its existing
storage; Home and Library still use sample profiles. Mods uses actual saved profiles,
and modpack installs publish separate instances through the existing transaction service.
Minecraft launching and the
remaining pages are not connected yet. The Qt frontend does not load Flet;
`python main.py` continues to run the existing launcher.
See the [Qt Home screenshot](screenshots/wisc-qt-home.png),
[Library screenshot](screenshots/wisc-qt-library.png),
[Skins screenshot](screenshots/wisc-qt-skins.png), and
[Mods screenshot](screenshots/wisc-qt-mods.png) for their current appearance.
These captures use sample or local fixture data.

## Flet shell

`ui/shell.py` retains the selected artwork outside the navigation host and
shares its pre-blurred cover with the fixed glass chrome and the full-window
feature-page backdrop. Page content and dialogs stay in their existing host.
`ui/glass.py` defines the dark translucent surface palette and rounded backdrop
filters for page cards, selectors, and feedback. Inputs and secondary actions
use matching translucent fills. `ui/theme.py` applies these surfaces to retained
features while keeping the selected theme's accents.
`services/artwork.py`
maps Minecraft versions to bundled `.assets/version-art/` covers without
network requests, preserving custom profile artwork. Home's artwork worker
updates library thumbnails only; it never owns the window background.

## Files and resources

`core/paths.py` resolves bundled resources relative to the package, including
PyInstaller's `_internal` directory. Use its `ASSETS_DIR` and `RESOURCE_ROOT`
instead of deriving repository paths from a moved module's `__file__` or the
current working directory. `application_root()` resolves the executable's
directory in packaged runs and the repository root in source runs.

Use `core.paths.launcher_data_dir()` for runtime data. New installations use
Minecraft's `wisc/`; existing `gr8launcher/` folders migrate to `wisc/`, rebasing
absolute artwork paths and modpack journals while keeping old credential scopes
available as native vault aliases. Legacy `.data`
migration still starts at the resource root. Native credential stores read old
service aliases and migrate only after a verified native save. Existing aliases
stay synchronized for rollback; sign-out clears both names. Fonts, artwork,
and licenses stay in `.assets/`; branding uses `.assets/fonts/PixelifySans.ttf`;
the Java skin bridge stays in `tools/wisc-skin-bridge/`.

`tools/build_windows.py` packages the `main.py` entry point and follows its
package imports. `tools/capture_screenshot.py` copies the application package
and assets into an isolated preview folder. Build and release workflows must
work from a clean checkout without local tests or reference copies.

The website is independent: source files live in `web/`, Node build/serve tools
in `tools/`, and deployment API functions in `api/`.

## Local checks and scratch work

Local regression tests live in ignored `temp/test_*.py` files and are not shipped
in a clone. Choose tests for the affected area; for example:

```powershell
python -B -m unittest temp.test_legacy_ui temp.test_ui_theme
python -B -m unittest temp.test_launcher_artwork temp.test_home_layout
python -B -m unittest temp.test_mod_services temp.test_modpack_services
python -B -m unittest temp.test_qt_mods
python -B -m unittest temp.test_launcher_updates temp.test_release_plan temp.test_release_tag
python -B temp/run_wisc_checks.py temp.test_wisc_rename temp.test_wisc_branding
```

Use `temp/<task>/` for temporary captures and experiments, then remove those
outputs. Keep useful regression tests and their small fixtures. Source backups,
downloaded reference projects, bytecode, and old build output add search noise
and should not live alongside active code.
