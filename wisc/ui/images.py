"""Shared bounded artwork loading, without importing content services at startup."""

from __future__ import annotations

from collections import OrderedDict, deque
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import local
from time import monotonic
from weakref import WeakSet

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QImageReader, QPixmap

from wisc.core.paths import ASSETS_DIR
from wisc.ui.components import asset_icon
from wisc.ui.tasks import ServiceRunner

_image_sessions = local()


def _read_image(source: str | bytes, limit: int) -> QImage:
    """Fetch and decode on a worker; bound both transfer and decoded artwork."""
    if isinstance(source, bytes):
        if len(source) > 8 * 1024 * 1024:
            raise ValueError("Artwork is too large.")
        payload = source
    elif QUrl(source).scheme() in {"http", "https"}:
        import requests
        session = getattr(_image_sessions, "session", None)
        if session is None:
            session = _image_sessions.session = requests.Session()
        with session.get(source, stream=True, timeout=(4, 12)) as response:
            response.raise_for_status()
            chunks = bytearray()
            for chunk in response.iter_content(64 * 1024):
                chunks.extend(chunk)
                if len(chunks) > 8 * 1024 * 1024:
                    raise ValueError("Artwork is too large.")
            payload = bytes(chunks)
    else:
        path = Path(source)
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("Artwork is too large.")
        reader = QImageReader(str(path))
        size = reader.size()
        if size.width() * size.height() > 32_000_000:
            raise ValueError("Artwork is too large.")
        if size.isValid() and max(size.width(), size.height()) > limit:
            reader.setScaledSize(size.scaled(limit, limit, Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise ValueError("Artwork could not be decoded.")
        return image
    from PIL import Image
    with Image.open(BytesIO(payload)) as image:
        if image.width * image.height > 32_000_000:
            raise ValueError("Artwork is too large.")
        image.thumbnail((limit, limit))
        rgba = image.convert("RGBA")
        return QImage(rgba.tobytes(), rgba.width, rgba.height,
                      QImage.Format.Format_RGBA8888).copy()


class ImageStore(QObject):
    """One application cache and two decode slots shared by all page consumers."""

    ready = pyqtSignal(str)
    MAX_BYTES = 24 * 1024 * 1024

    def __init__(self, runner: ServiceRunner):
        super().__init__(runner)
        self.runner = runner
        self.cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.failed: OrderedDict[str, float] = OrderedDict()
        self.requests: dict[str, tuple] = {}
        self.queue: deque[str] = deque()
        self.active = 0
        self.bytes = 0
        self.fallback = asset_icon(ASSETS_DIR / 'tab-icons' / 'mods.svg').pixmap(QSize(128, 128))
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._pump)

    def request(self, client: ContentImages, key: str, source: str | bytes, limit: int, blur: bool) -> None:
        if key in self.requests:
            self.requests[key][3].add(client)
            client._pending.add(key)
        elif len(self.requests) < 64:
            self.requests[key] = (source, limit, blur, WeakSet((client,)))
            self.queue.append(key)
            client._pending.add(key)
            self._timer.start(0)

    def suspend(self, client: ContentImages) -> None:
        for key in tuple(self.queue):
            request = self.requests.get(key)
            if request is not None:
                request[3].discard(client)
                client._pending.discard(key)
                if not request[3]:
                    self.requests.pop(key)
                    self.queue.remove(key)

    def _pump(self) -> None:
        if self.runner._closed:
            self.queue.clear()
            self.requests.clear()
            return
        while self.active < 2 and self.queue:
            key = self.queue.popleft()
            source, limit, blur, clients = self.requests[key]
            if not clients:
                self.requests.pop(key)
                continue
            self.active += 1
            self.runner.submit(
                lambda value=source, size=limit, soften=blur:
                    _read_blurred_image(value, size) if soften else _read_image(value, size),
                lambda image, identity=key: self._finished(identity, image),
                lambda error, identity=key: self._finished(identity, None),
            )

    def _finished(self, key: str, image: QImage | None) -> None:
        self.active -= 1
        self.requests.pop(key, None)
        if image is None or image.isNull():
            self.failed[key] = monotonic() + 30
            while len(self.failed) > 128:
                self.failed.popitem(last=False)
        else:
            pixmap = QPixmap.fromImage(image)
            old = self.cache.pop(key, None)
            if old is not None:
                self.bytes -= old.width() * old.height() * 4
            self.cache[key] = pixmap
            self.bytes += pixmap.width() * pixmap.height() * 4
            while self.bytes > self.MAX_BYTES or len(self.cache) > 96:
                _, old = self.cache.popitem(last=False)
                self.bytes -= old.width() * old.height() * 4
        self.ready.emit(key)
        self._timer.start(0)


def _read_blurred_image(source: str | bytes, limit: int) -> QImage:
    from PIL import Image, ImageFilter
    from wisc.ui.theme import ARTWORK_BLUR_LIMIT, ARTWORK_BLUR_RADIUS
    image = _read_image(source, min(limit, ARTWORK_BLUR_LIMIT)).convertToFormat(QImage.Format.Format_RGBA8888)
    if image.isNull():
        return image
    pixels = image.constBits().asstring(image.sizeInBytes())
    rgba = Image.frombytes('RGBA', (image.width(), image.height()), pixels)
    rgba = rgba.filter(ImageFilter.GaussianBlur(ARTWORK_BLUR_RADIUS / 2))
    return QImage(rgba.tobytes(), rgba.width, rgba.height,
                  QImage.Format.Format_RGBA8888).copy()


class ContentImages(QObject):
    """Visibility-scoped access to the application's bounded shared image store."""

    ready = pyqtSignal(str)

    def __init__(self, runner: ServiceRunner, parent: QObject | None = None):
        super().__init__(parent)
        self._runner = runner
        store = getattr(runner, '_image_store', None)
        if store is None:
            store = runner._image_store = ImageStore(runner)
        self._store = store
        self._cache = store.cache
        self._pending: set[str] = set()
        self._deferred: set[str] = set()
        self._visible = False
        store.ready.connect(self._finished)
        self.fallback = store.fallback

    @staticmethod
    def key(source: str | bytes, limit: int = 128, *, blur: bool = False) -> str:
        # Do not retain potentially large byte payloads in a memoized function.
        identity = sha256(source).hexdigest() if isinstance(source, bytes) else source
        return f'{limit}:{identity}' + (':blur' if blur else '')

    @property
    def _active(self) -> int:
        return self._store.active

    @property
    def _queued(self) -> tuple[str, ...]:
        return tuple(key for key in self._store.queue if key in self._pending)

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        if visible:
            deferred, self._deferred = self._deferred, set()
            for key in deferred:
                self.ready.emit(key)
        else:
            self._store.suspend(self)

    def has_failed(self, key: str) -> bool:
        return self._store.failed.get(key, 0) > monotonic()

    def get(self, source: str | bytes | None, limit: int = 128, *, blur: bool = False) -> QPixmap | None:
        if not source:
            return None
        key = self.key(source, limit, blur=blur)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        if self._visible and key not in self._pending and not self.has_failed(key):
            self._store.request(self, key, source, limit, blur)
        return None

    def _finished(self, key: str) -> None:
        if key not in self._pending:
            return
        self._pending.discard(key)
        if self._visible:
            self.ready.emit(key)
        else:
            self._deferred.add(key)
