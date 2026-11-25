# PyQt6 migration plan

Analysis date: 24 November 2026. Source target: Windows, Linux, and macOS;
Windows x64 packaging first. Direction: a
feature-complete Qt migration with a refreshed Wisc presentation. The user's
latest instruction allows different layouts and animations; exact visual
recreation is no longer a requirement. This document tracks the staged migration.

Current progress: Home, Library, Skins, and the content workspace are available through `python -m wisc.qt_app`,
with shared sample-profile selection, library filters/sorting, theme switching,
a classic title bar, and frosted surfaces. Window controls use a shared Qt path;
Windows enhancements are isolated. Native Linux/macOS smoke checks remain needed.
Skins uses the active launcher account and existing persistence, with Ely.by sync,
the account's skin model, and an interactive software-rendered preview.
A shared background service loop delivers results to Qt and suspends hidden previews.
Mods reads saved profiles independently of Home's sample selection. Mods, Modpacks,
Shaders, and Texture Packs share native model/view discovery, details, version history,
and bounded artwork loading. Existing services handle dependency reviews, local JARs,
manual CurseForge verification, saved update checks, batch updates, and isolated pack
instances. Searches coalesce stale requests; confirmed downloads retain progress and
cancellation across tabs. Launch services and the other Qt pages remain to be connected.

Use **Qt Widgets, styled standard controls, and the existing services**. Keep
Wisc's identity and every current workflow while simplifying presentation and
toolkit-specific coordination.

## Scope and time target

The initial Flet inventory has roughly 14,700 lines of UI/application wiring
and 11,700 lines of largely reusable core, service, and mod code. The latter
modules have no Flet imports. Some state still stores widget references and
callbacks, so import independence does not eliminate the coordination work.
PyQt6 6.11.0 / Qt 6.11.0 already imports under the local Python 3.14.3.

Target **12-20 working days, approximately 100-160 engineering hours**, for one
experienced developer to complete the Windows migration and release preparation.
This is roughly 3-4 full-time weeks, with a first working Qt build in 2-3 days.
It assumes the design decisions below, reuse of existing services, and no new
features. Re-estimate after the first end-to-end launch and packaged smoke check.

| Phase | Working days | Deliverable |
| --- | ---: | --- |
| Foundation and first end-to-end launch | 1-2 | Qt window, common styling, navigation, service runner, selected-profile launch, and an early frozen-app/resource smoke check. |
| Main launcher workflows | 3-5 | Home, library, profiles, accounts, skins, onboarding, and settings connected to existing services. |
| Shared content workspace | 4-6 | Mods, modpacks, shaders, texture packs, details, reviews, manual files, and mutations. |
| Release integration | 2-4 | Full portable/installer packaging, updater handoff, screenshot replacement, and dependency cleanup. |
| Final integration and visual correction | 2-3 | Focused regression checks, Windows resizing/scaling, consistent presentation, and outstanding fixes. |

The phase ranges total 12-20 days. Validate features during their phase; the
last phase resolves integration issues and consistency. A feature-complete beta
can precede the release candidate, but beta status does not mean the task is done.

## Implementation defaults

| Area | Choice for the migration |
| --- | --- |
| UI toolkit | Qt Widgets throughout. |
| Window | Custom 52px Wisc title bar with shared Qt controls/system move and resize. Optional Windows integration adds native system commands, compositor transitions, and Snap support. |
| Background and surfaces | Selected-profile artwork and shared frosted surfaces using cached blurred covers; foreground text remains sharp on all desktop platforms. |
| Inputs and menus | Styled `QLineEdit`, `QComboBox`, checkboxes, spin boxes, sliders, and `QMenu`. |
| Dialogs | Shared styled `QDialog` forms and ordinary Qt file dialogs. |
| Navigation | `QStackedWidget` with explicit page activation/deactivation and retained view state. |
| Lists | Qt list models/views, checkable items, context/toolbar actions, and native drag/drop. |
| Feedback | One application-owned progress model/view and a small notification host. |
| Motion | Immediate page changes, standard hover/focus feedback, progress animation, and simple skin interaction. |
| Async work | One managed asyncio service loop with queued Qt signals; widgets remain on the GUI thread. |
| Skin preview | Reuse the current software renderer and publish its images to Qt. |

Exact animation timing, layered page reveals, animated drag ghosts, and custom
Snap hover behavior are optional later visual work. Reuse shared glass painting
for controls and captions. Retain operation priorities, cancellation, focus,
readable status/error feedback, and state restoration even when their appearance changes.

## Small design contract

Use [design_theme.txt](../design_theme.txt) and the existing assets as character
references. Settle a compact Home, discovery list, and form treatment in the
foundation phase and reuse it throughout.

- Keep the supplied Wisc logo, Minecraft artwork, Pixelify Sans branding,
  selected-profile background, and theme accents.
- Use restrained near-black surfaces, consistent spacing and typography,
  compact controls, and clear selected/focused/disabled states.
- Keep the top navigation, Home launch actions, library, and all content and
  settings destinations easy to find.
- Let Qt layouts handle resizing. Check 1100x650 and a larger window, with long
  pages scrollable and primary actions accessible.

A small semantic palette and one shared style sheet should define ordinary
controls. Custom paint only the artwork/card pieces that establish Wisc's
character. Reuse a cached blurred background instead of reproducing every
backdrop filter. Use the actual branding and icon family consistently.

Review each page for hierarchy, contrast, alignment, and usable states. Exact
pixel comparisons and animation timing comparisons are outside this scope.

## Code structure and implementation order

Keep the existing `wisc/core`, `wisc/services`, and `wisc/mods` boundaries. Put Qt
views, list models, and presentation controllers in `wisc/ui`. Keep
`wisc/app.py` focused on startup and wiring. `main.py` must still run
`updates.startup_guard()` before importing the UI.

Keep application state as data: selected IDs, current page, theme, queries,
filters, scroll anchors, and operation status. Controllers own widget references
and delivery of results. Introduce typed state only where it clarifies ownership;
there is no need to remodel every existing service payload.

Build a small shared set of controls: artwork card/background, section surface,
styled actions/fields, result list, details panel, dialog, progress view, and
notification. Compose pages from these instead of styling every page separately.

Use one discovery layout for search, provider/filter controls, results, paging,
and details. Share presentation between Mods, Modpacks, Shaders, and Texture
Packs. Keep feature-specific install controllers: mod dependency planning,
modpack instance creation, and content-file handling have different contracts.
Reuse existing provider, compatibility, and transaction code.

Implement complete workflows in this order:

1. Window, theme, resource loading, workers, and one installed-profile launch.
2. Home and library, selection persistence, logs, repair, and launch cancellation.
3. Profile editing/import/reordering, settings, accounts, onboarding, and skins.
4. Shared discovery and details, then each content type's installation flow.
5. Release integration, removal of Flet, and final consistency checks.

Use direct feature controllers and Qt signals rather than a general event bus,
plugin framework, or Flet compatibility layer. Reuse existing helpers and
service contracts. Avoid unrelated backend refactors during this migration.

## Lifecycle and functional correctness

Each long-running operation must have an owner, cancellation state, and a
finished state. Keep ongoing downloads/game operations alive across navigation;
release transient search activity when leaving its page. Invalidated searches,
artwork, skin frames, and progress handles must ignore late results.

Blocking HTTP work cannot be stopped merely by canceling an asyncio future.
Retain the services' cooperative cancellation and commit checks. Deliver data
through queued Qt signals, coalesce progress/log updates, and stop unused timers
and rendering when pages are hidden or the application shuts down.

Preserve the following complete workflows:

| Area | Required behavior |
| --- | --- |
| Launch | Latest Release and saved profiles; installed/offline launch; install-on-play; repair; logs/progress/cancel; duplicate-launch prevention; keep/hide/close settings. |
| Profiles | Discovery/import, create/edit, version and loader pins, artwork/icons, saved ordering, folder actions, and existing removal safeguards. |
| Accounts/skins | Offline and Ely.by accounts, login/relogin/two-factor handling, active-account changes, native credential storage/redaction, sign-out, skins/capes, and usable preview controls. |
| Settings/setup | Existing settings, presets/custom accents, Java/RAM/game options, onboarding, and Updates access. |
| Mods/content | Providers and credentials, search/filter/paging, installed/discovery views, details/versions, dependencies, manual files, import, enable/disable/remove, and updates. |
| Modpacks | Review/optional files, exact pins, separate-instance creation, cancellation/rollback, and pack-managed mod rules. |
| Updates | Source/mock guards, verified download, portable/installed handoff, interrupted recovery, and upgrade from a Flet package to a Qt package. |

Keep existing storage formats, runtime directories, native credential aliases,
and legacy data migrations. Retain the C# updater and Java skin bridge. The
website and deployment API are outside the frontend migration.

## Packaging and validation

Work in an isolated migration branch/check-out, preserving the current local
changes and usable Flet version. Avoid duplicate source backups in the
repository. Bring up a small frozen Qt build early to check the platform plugin,
resource paths, fonts, and image loading before all pages are implemented.

Replace Flet packing with direct PyInstaller packaging in
`tools/build_windows.py`. Retain names, asset/bridge/updater inclusion, inventory
generation, checksums, installer identity, and release command contracts. Package
only the chosen Qt binding; both PyQt6 and PySide6 are currently installed locally.

Replace the Flet web/Chromium path in `tools/capture_screenshot.py` with a
deterministic Qt capture using isolated sample data. Keep its CLI/output contract
so release CI and screenshot publication continue to work from a clean checkout.

Reuse existing focused service tests. Add/adapt small local regressions for
selection versus launched profile, canceled/stale work, failed order saves,
state retention, and updater handoff where needed. Keep tests/scratch output in
ignored `temp/`; release tooling must not depend on them.

Check each completed workflow, then exercise integration around launch, one
mod dependency install, one modpack install, accounts/settings persistence, and
the packaged updater paths. Complete required release checks. Review Home,
discovery, details, forms, and active progress at the supported window sizes;
check Windows scaling and native window behavior.

Measure startup, idle memory, and scrolling only to resolve a concern or support
a performance claim. Toolkit choice alone is not evidence of an improvement.

At completion, all existing workflows must be reachable, data must remain
compatible, long tasks must stay responsive, and the app must build and capture
screenshots without Flet. Update architecture/releasing documentation and add
release fragments for completed user-facing changes. This planning task does not
change the application or publish a release.
