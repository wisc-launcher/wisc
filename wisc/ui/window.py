"""Native resize gestures for the launcher's undecorated Linux window."""

import flet as ft


def build_window_resize_handles(page: ft.Page) -> list[ft.GestureDetector]:
    """Leave window sizing to Linux's window manager after an edge drag."""
    if page.web or page.platform != ft.PagePlatform.LINUX:
        return []

    edge_width = 6
    corner_size = 12

    def handle(edge: ft.WindowResizeEdge, cursor: ft.MouseCursor,
               **bounds: float) -> ft.GestureDetector:
        async def start_resize(event: ft.DragStartEvent) -> None:
            window = page.window
            if window.resizable and not window.maximized and not window.full_screen:
                await window.start_resizing(edge)

        return ft.GestureDetector(
            content=ft.Container(bgcolor=ft.Colors.TRANSPARENT),
            mouse_cursor=cursor,
            on_pan_start=start_resize,
            exclude_from_semantics=True,
            **bounds,
        )

    return [
        handle(ft.WindowResizeEdge.TOP, ft.MouseCursor.RESIZE_UP_DOWN,
               left=corner_size, top=0, right=corner_size, height=edge_width),
        handle(ft.WindowResizeEdge.BOTTOM, ft.MouseCursor.RESIZE_UP_DOWN,
               left=corner_size, bottom=0, right=corner_size, height=edge_width),
        handle(ft.WindowResizeEdge.LEFT, ft.MouseCursor.RESIZE_LEFT_RIGHT,
               left=0, top=corner_size, bottom=corner_size, width=edge_width),
        handle(ft.WindowResizeEdge.RIGHT, ft.MouseCursor.RESIZE_LEFT_RIGHT,
               right=0, top=corner_size, bottom=corner_size, width=edge_width),
        handle(ft.WindowResizeEdge.TOP_LEFT, ft.MouseCursor.RESIZE_UP_LEFT_DOWN_RIGHT,
               left=0, top=0, width=corner_size, height=corner_size),
        handle(ft.WindowResizeEdge.TOP_RIGHT, ft.MouseCursor.RESIZE_UP_RIGHT_DOWN_LEFT,
               right=0, top=0, width=corner_size, height=corner_size),
        handle(ft.WindowResizeEdge.BOTTOM_LEFT, ft.MouseCursor.RESIZE_UP_RIGHT_DOWN_LEFT,
               left=0, bottom=0, width=corner_size, height=corner_size),
        handle(ft.WindowResizeEdge.BOTTOM_RIGHT, ft.MouseCursor.RESIZE_UP_LEFT_DOWN_RIGHT,
               right=0, bottom=0, width=corner_size, height=corner_size),
    ]
