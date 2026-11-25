# Repository Guidelines

## Project Structure & Module Organization

`main.py` is the launch entry point; `wisc/app.py` owns Flet page orchestration. Application modules live in four packages:

| Folder | Start here for |
| --- | --- |
| `wisc/ui/` | Pages, controls, dialogs, profiles, themes, motion, progress, and notifications |
| `wisc/services/` | Minecraft launch/install, instance discovery, profile creation, authentication, skins, artwork, Discord, and updates |
| `wisc/mods/` | Mod providers, compatibility, downloads, metadata, and modpacks |
| `wisc/core/` | Shared state, settings/profiles, native credentials, palette definitions, and resource paths |

Bundled artwork/fonts live in `.assets/`, local tests/scratch work in ignored `temp/`, build/release utilities and the Java skin bridge in `tools/`, installer configuration in `packaging/`, documentation in `docs/`, and the website in `web/` with deployment API functions in `api/`.

## Agent Navigation

- Use [docs/architecture.md](docs/architecture.md) for the module map and resource/entry-point rules. Search the relevant package first, for example `rg -n 'ProfileList' wisc/ui` or `rg --files wisc tools`.
- Avoid whole-workspace scans of generated files or local tests unless the task needs them. Old source copies belong outside the repository; do not recreate `REF/` or `new_ui/` backups.
- Use absolute `wisc.*` imports. Keep package `__init__.py` files lightweight and avoid compatibility copies at the repository root.
- Put new scratch output in `temp/<task>/` and remove it when finished. Retain useful local regression tests; release tools must run without `temp/`.

## Build, Test, and Development Commands

Run from the repository root in a virtual environment. Source supports Python 3.10+; Windows packaging uses x64 Python 3.14.

- `py -3 -m venv .venv`, then `.\.venv\Scripts\Activate.ps1`: set up PowerShell development.
- `python -m pip install -r requirements.txt`: install runtime dependencies.
- `python main.py`: launch; Minecraft needs compatible Java.
- `python -m pip install -r requirements-build.txt`: install pinned build/test dependencies.
- `python tools/build_windows.py --portable-only`: create a ZIP in `dist/`. Omit the flag for an Inno Setup installer; see `docs/releasing.md`.

## Launcher Design Language

Follow `design_theme.txt` and the restored classic components:

- **Palette:** selectable Minecraft themes in `wisc/core/themes.py`, defaulting to Earth 2, supply action, selection, and focus accents. Chrome and page elements use the fixed dark translucent palette in `wisc/ui/glass.py`, including retained features through `wisc.ui.theme.apply_legacy_theme`.
- **Typography/assets:** use the supplied Wisc logo and bundled Pixelify Sans for branding and pixel text. Keep existing Minecraft artwork and all bundled font licenses, including the legacy notices in `.assets/font/`. Use system fonts for dense details.
- **Shape:** preserve rounded library cards, compact profile rows, and options cards. Page cards and shared surfaces use frosted glass with rounded corners and no resting outlines; the fixed title bar spans the full width. Keep selection and focus feedback visible, and keep Home's launch panel transparent.
- **Borders and focus:** buttons use subtle fill or opacity feedback, including keyboard focus, without added outlines. Mod and content rows are action rows and must not show a selected border or selection tint. Use clean pill switches for enabling and disabling mods.
- **Qt surfaces:** use the custom title bar's shared dark glass color, blur, and opacity for secondary controls and page surfaces. Primary and selected buttons use opaque theme colors with matching text; avoid translucent accent-colored button fills.
- **Dropdowns:** use `AcrylicSelector`, or the `LegacySelector` adapter for classic forms. Menus stay anchored to the field width, with 48px closed fields, 5px corners, light labels and chevrons, and theme accents for selected items. Use one control per filter.
- **Layout:** retain the original top navigation, custom window controls, Home launch panel, and library shelf. Keep selected version artwork across every page and do not restore a separate Home banner. Keep Mods & Modpacks and Options > Updates accessible. Check 1100x650 and larger windows; keep content scrollable and window controls usable.
- **Motion/feedback:** keep the classic tab transitions and reuse `StaggeredReveal`, `ProfileDialogHost`, `ProfileList`, `ProgressHost`, and `ToastHost` for retained features. Keep transitions interruptible, restore state after navigation/canceled drags, and provide concise loading/error feedback.

## Reuse Existing Components

- Before adding a component, helper, or workflow anywhere in the repository, check the relevant package for an existing implementation and reuse or extend it.
- Build new UI features by composing the existing page layouts, controls, surfaces, selectors, dialogs, progress, and notifications. Use the Mods area as the reference for discovery lists, toolbars, rows, and installation flows.
- Use `card_surface` and `ModList` for discovery rows, keeping the Mods area's 8px row gaps, padding, typography, and stable row keys. Do not rebuild equivalent rows or dropdowns separately for each content type.
- Keep shared behavior and styling in shared helpers. Add a new implementation only when existing components cannot support the feature, and preserve the established design and lifecycle patterns.

## Coding Style & Naming Conventions

Use four spaces in new modules; preserve existing indentation, including legacy tabs. Use `snake_case`, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Type-hint helpers. No formatter/linter is configured.

## Testing Guidelines

Use `unittest` (`IsolatedAsyncioTestCase` for async UI), `test_*.py` files, and `test_*` methods. No coverage threshold is configured.

- All tests, UI/browser validation scripts, and scratch output stay local in the ignored `temp/` directory, including maintained regression tests.
- Do not add `.gitignore` exceptions for these files or force-add, stage, commit, or push them unless the user explicitly asks to publish tests.
- GitHub build/release workflows must work from a clean checkout without `temp/` or any local test files. Do not add CI steps that depend on them. Keep the actual build, release, and screenshot utilities in `tools/` versioned.
- Document test commands as local-only; their scripts are not included in a clone.

When the local test files are present, run them from the repository root after installing build dependencies:

```powershell
python -B -m unittest temp.test_release_plan temp.test_release_tag temp.test_publish_screenshot temp.test_ui_toasts
```

## Commit & Pull Request Guidelines

Use focused, descriptive subjects like `Add remote tag validation`. PRs should explain changes, link issues, report validation, and include UI screenshots. New `VERSION` values pushed to `main` trigger publication.

## Release Notes for AI Agents

- For every completed task that adds, changes, fixes, removes, or secures user-facing behavior, create or update one descriptive Markdown fragment in `docs/changes/unreleased/` alongside the code. Follow [docs/changes/README.md](docs/changes/README.md).
- Use `### Added`, `### Changed`, `### Fixed`, `### Removed`, or `### Security` headings and concise bullets explaining the effect for users. Record completed functionality, not plans or implementation logs.
- Use a separate file for each independent task; preserve other agents' fragments. Update the same task's fragment when refining it, and avoid duplicate entries.
- Documentation-only edits, validation-only changes, and internal refactors without visible behavior do not need fragments.
- Before finishing, check that the fragment accurately describes the final change. Do not clear fragments or archive notes when changing `VERSION`; the release workflow archives and clears only successfully published, unchanged fragments.
- Do not bump `VERSION`, stage/commit/push changes, or publish a release merely to maintain notes unless the user requested those actions.

## Security & Configuration Tips

Runtime data lives in Minecraft's `wisc/`; migrate existing `gr8launcher/` folders through `wisc.core.paths.launcher_data_dir`, preserving files and rebasing absolute data paths. Preserve native credential storage/redaction and legacy credential aliases, including aliases scoped to the old accounts path. Exclude tokens, personal game data, and generated `build/`/`dist/` artifacts.
