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
python -B -m unittest temp.test_launcher_updates temp.test_release_plan temp.test_release_tag
python -B temp/run_wisc_checks.py temp.test_wisc_rename temp.test_wisc_branding
```

Use `temp/<task>/` for temporary captures and experiments, then remove those
outputs. Keep useful regression tests and their small fixtures. Source backups,
downloaded reference projects, bytecode, and old build output add search noise
and should not live alongside active code.
