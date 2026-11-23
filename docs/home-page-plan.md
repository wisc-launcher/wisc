# Home page redesign plan

Status: implemented in `wisc/ui/home.py`, with the shared artwork and glass shell in `wisc/ui/shell.py`.

## Reference and direction

Use the [OneClient / OneLauncher reference](https://github.com/Polyfrost/OneLauncher/tree/dd085b25853750a38dfff757cb6a2caa281d6784). Its home page is composed of an active-profile hero and a recent-profile shelf: the selected profile gets a large title, a short version/loader subtitle, and a launch button directly underneath. Artwork cards select that profile; a final tile opens the rest of the library.

Source references:

- [index.rs](https://github.com/Polyfrost/OneLauncher/blob/dd085b25853750a38dfff757cb6a2caa281d6784/packages/oneclient_app/src/view/app/home/index.rs)
- [active_cluster_panel.rs](https://github.com/Polyfrost/OneLauncher/blob/dd085b25853750a38dfff757cb6a2caa281d6784/packages/oneclient_app/src/components/active_cluster_panel.rs)
- [recents_row.rs](https://github.com/Polyfrost/OneLauncher/blob/dd085b25853750a38dfff757cb6a2caa281d6784/packages/oneclient_app/src/components/recents_row.rs)
- [dynamic_art.rs](https://github.com/Polyfrost/OneLauncher/blob/dd085b25853750a38dfff757cb6a2caa281d6784/packages/oneclient_app/src/components/dynamic_art.rs)

Adapt the hierarchy and artwork treatment to Wisc. Use our bundled artwork, Wisc logo, Pixelify Sans branding, selected theme, existing top navigation, and rounded library cards. Keep the current account, launch, profile, and log behavior connected to their existing services.

## Layout

1. **Compact welcome row.** A short welcome message on the left and the active account's face/name on the right. The account chip opens Accounts.
2. **Large selected-profile banner.** Let the hero take the flexible middle space. Put the profile name, Minecraft version, loader, instance badge, and readiness status on the left. Place a clear Play button below the profile details, alongside Edit and Folder. Keep the right side mostly artwork, with a theme-colored gradient protecting text contrast.
3. **Single library shelf.** Show three artwork cards at 1100px and four at 1366px when available. Keep the selected card visibly outlined. Add a compact New Profile tile and a Manage all link. Retain the existing saved profile order and selected profile; “recent” sorting needs separate last-played data and is outside this first change.
4. **Quiet footer.** Keep Logs accessible. Reuse the existing shared progress host and floating log window. When opening logs, retain the selected profile and keep the window controls usable.

The concept demonstrates profile selection, three theme choices, and launch-state labels. Its sample accounts/profiles and controls are illustrative; it does not launch Minecraft or alter launcher settings.

## Dimensions and behavior

| Element | 1100 × 650 | 1366 × 768 |
| --- | --- | --- |
| Shell | Existing top navigation and window controls | Same shell |
| Content inset | 28px horizontally, 20px at the top | Same inset |
| Hero | Flexible height, approximately 230–280px, including active progress | Approximately 340–380px |
| Profile title | 36–42px system font, with truncation | Up to 48px |
| Shelf cards | Three profiles plus New Profile; approximately 130px tall | Four profiles plus New Profile; approximately 150px tall |
| Actions | Play, Edit, Folder visible inside the hero | Same actions |

Below the supported minimum, allow the body to scroll without clipping the title bar. Use tighter hero spacing in shorter windows so launch controls remain visible when progress is active. Overflow profiles remain accessible through Manage all. Use the existing 12px cards, 8px buttons/artwork corners, and theme borders; retain the established banner rounding. Keep Mojangles for the launcher title and the banner's Minecraft branding, with system fonts for profile names and details.

Selecting a shelf card changes the hero and launch target together. Load cached artwork first, then crossfade the selected profile's artwork only if that selection remains current. Reuse `StaggeredReveal` for a brief, interruptible entrance. Preserve selection across navigation and theme changes.

## Required states

- **Ready:** Play launches the selected profile; profile actions remain accessible.
- **Not installed:** Show the existing install-on-launch behavior clearly. Keep the launch target's pinned Minecraft and loader versions.
- **Downloading:** Reuse the existing progress/status/ETA and Cancel behavior. Keep profile selection locked while the operation is active.
- **Starting or running:** Show the current launch state and prevent duplicate launches; retain the configured keep/hide/close launcher behavior.
- **Offline:** Use cached/local artwork and preserve launch availability for supported installed profiles. Explain unavailable online actions concisely.
- **Sign-in required:** Lead to the new Login screen for the selected Ely.by account.
- **Empty or unavailable profile:** Show a useful New Profile action and keep Latest Release available whenever its version is known. Handle a removed selection with the existing fallback behavior.
- **Missing artwork or long names:** Use bundled fallback art, truncate dense labels, and expose full names through tooltips.

## Implementation and performance

- `wisc/ui/home.py` keeps the existing account, launch, cancellation, and floating-log callbacks. `wisc/app.py` uses the shared `StaggeredReveal` for Home navigation.
- Build only the first three or four shelf cards, keeping their saved order. Reuse those controls when resizing, and retain all other profiles through Manage all.
- Check local artwork once per displayed profile and selected profile. Show bundled fallback artwork immediately when the cache is empty.
- Start one artwork worker after the page mounts. Prioritize the selected profile, resolve each missing profile's artwork at most once per Home visit, and skip network requests while offline.
- Stop the worker and clear queued work when the page unmounts. An HTTP request already running in a background thread may finish caching its result, but it cannot update a detached page or a newer selection.
- Update the selected profile and launch target together. Only patch the changed cards, hero, or action state; resizing updates controls only when their size or visible slot count changes.
- Use a single theme-colored gradient over the hero artwork, replacing the former blur layers. Keep the shared progress host and floating logs.

## Focused validation

Review the implemented page at 1100 × 650 and 1366 × 768 using the existing isolated screenshot utility. Check ready, downloading, running, empty, and missing-artwork layouts, plus one alternate theme. Reuse the relevant local home/launch regressions and add small regressions only for meaningful changed behavior: selecting a card changes the launched profile, interrupted artwork updates cannot overwrite the current selection, and cancel/progress state remains consistent.

All additional tests and browser-check scripts stay in ignored `temp/`. Builds and CI must remain independent of these local files.
