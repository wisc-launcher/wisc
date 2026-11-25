### Fixed

- Keep mouse clicks on Qt buttons borderless while retaining visible keyboard focus.
- Use shared Qt window actions and system move/resize on desktop platforms, with a geometry fallback when native dragging is unavailable.
- Restore native Windows window transitions and synchronize maximize/restore controls with the actual window state, preserving monitor work-area bounds.
