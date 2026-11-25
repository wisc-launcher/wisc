# Qt performance

The Qt preview constructs Home and the shell first. Library code warms in the
background after the initial paint; Library, Skins, Mods, and content details
are constructed when needed. First-use preparation shows a loading surface and
does not block navigation. All widget creation and pixmap conversion remain on
the GUI thread.

Home creates only its visible shelf cards. Library reuses the content model/view
and the same card painters, with a 4 MiB surface cache instead of a widget and
menu for every profile. Its selection, filters, sorting, scroll position, and
profile actions remain available across navigation.

`wisc/ui/qt_images.py` shares a 32 MiB decoded-image cache and four decode slots
across pages. Local images decode through `QImageReader` on workers, sized for
their use; remote images retain transfer/dimension limits. Custom background
blur runs on a worker. Background frames retain only the current size and DPR.
Hidden consumers remove queued requests, and images already being decoded can
finish into the shared cache.

The service executor has four workers. Skin rendering uses one running request
and one replaceable pending pose, including across hide/show cycles. Canceling a
Python future cannot stop an already-running worker; canceled requests discard
callbacks, and installation workers retain their cooperative cancellation and
atomic commit guards. Dialogs dispose of their tasks when closed, and manager
caches retain the eight most recently used contexts in each category. Navigation
icons and fonts have bounded caches; profile menus use painted dots to avoid a
first-use fallback font lookup.

## Local measurements

Measured on Windows with Python 3.14, PyQt6 6.11, bundled sample profiles, and an
1100x650 window. Each probe starts a fresh process, renders a noninteractive
transparent native window, and includes Qt/native memory in the process counters.
These are local samples, not cold-boot or packaged-build guarantees.

| Measurement | Before | After |
| --- | ---: | ---: |
| Import time | 300 ms | 109 ms |
| First Home frame | 1,042 ms | 468 ms |
| Settled Home working set | 136.38 MiB | 94.85 MiB |
| Settled Home private memory | 93.90 MiB | 60.67 MiB |
| Widgets constructed at startup | 304 | 51 |
| First Library opening after Home preparation | 180 ms | 23 ms |
| Working set after 200 Home/Library cycles | 192.34 MiB | 96.35 MiB |
| Private memory after 200 cycles | 124.56 MiB | 61.12 MiB |

The optimized process stayed between 96.31 and 96.60 MiB across 500 navigation
cycles, with stable widget counts and no remaining service callbacks. This checks
Home/Library stability; it does not establish that every workflow is leak-free.
Home artwork loads asynchronously after the initial frame. The optimized sample
finished artwork and Library preparation within about 780 ms.

An offscreen 500-profile check reduced initial widgets from 2,288 to 51; opening
Library adds a fixed set of view controls instead of widgets per profile.

The maintained regression/profiling scripts are local-only in ignored `temp/`
and are not included in a clone. When present, run from the repository root:

```powershell
python -B temp/profile_qt.py --cycles 500
python -B temp/profile_qt.py --offscreen --profiles 500 --cycles 30
python -B -m unittest temp.test_qt_performance temp.test_qt_library_first_open temp.test_qt_mods temp.test_qt_skins temp.test_qt_resize
```

The regressions cover stale page preparation, large-library selection and actions,
shared image delivery, bounded workers, canceled queues, skin pose replacement,
dialog disposal, content installation/commit guards, themes, and window resizing.
