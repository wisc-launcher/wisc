"""Application-owned service loop with results delivered on the Qt GUI thread."""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from itertools import count
from threading import Event, Lock, Thread
from typing import Any, Callable

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal


class ServiceRunner(QObject):
    _delivered = pyqtSignal(int, object, object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._loop = asyncio.new_event_loop()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="Wisc worker")
        self._loop.set_default_executor(self._executor)
        self._ids = count(1)
        self._callbacks: dict[int, tuple[Callable, Callable]] = {}
        self._futures: dict[int, Future] = {}
        self._closed = False
        self._delivered.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self._thread = Thread(target=self._serve, name="Wisc services", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
            self._executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, operation: Callable[[], Any], success: Callable[[Any], None],
               failure: Callable[[Exception], None]) -> int:
        if self._closed:
            raise RuntimeError("The launcher is closing.")
        token = next(self._ids)
        self._callbacks[token] = (success, failure)

        async def invoke() -> None:
            try:
                result = await asyncio.to_thread(operation)
            except asyncio.CancelledError:
                return
            except Exception as error:
                if not self._closed:
                    self._delivered.emit(token, None, error)
            else:
                if not self._closed:
                    self._delivered.emit(token, result, None)

        self._futures[token] = asyncio.run_coroutine_threadsafe(invoke(), self._loop)
        return token

    def _deliver(self, token: int, result: Any, error: Exception | None) -> None:
        callbacks = self._callbacks.pop(token, None)
        self._futures.pop(token, None)
        if callbacks is not None and not self._closed:
            success, failure = callbacks
            failure(error) if error is not None else success(result)

    def cancel(self, token: int | None) -> None:
        self._callbacks.pop(token, None)
        future = self._futures.pop(token, None)
        if future is not None:
            future.cancel()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for token in tuple(self._futures):
            self.cancel(token)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=0.2)


class LatestServiceTask:
    """Coalesce changing requests without piling up uncancelable worker threads.

    One operation runs at a time. Its replacement waits in a single slot, and
    only the latest request can deliver a result. All methods run on the GUI thread.
    """

    def __init__(self, runner: ServiceRunner):
        self._runner = runner
        self._generation = 0
        self._pending: tuple | None = None
        self._token: int | None = None

    def submit(self, operation: Callable[[], Any], success: Callable[[Any], None],
               failure: Callable[[Exception], None]) -> None:
        self._generation += 1
        self._pending = (self._generation, operation, success, failure)
        self._start_pending()

    def invalidate(self) -> None:
        self._generation += 1
        self._pending = None

    def _start_pending(self) -> None:
        if self._token is not None or self._pending is None:
            return
        generation, operation, success, failure = self._pending
        self._pending = None

        def complete(value: Any, error: Exception | None = None) -> None:
            self._token = None
            try:
                if generation == self._generation:
                    failure(error) if error is not None else success(value)
            finally:
                self._start_pending()

        self._token = self._runner.submit(operation, complete, lambda error: complete(None, error))

    def close(self) -> None:
        self.invalidate()
        self._runner.cancel(self._token)
        self._token = None


class OperationCancelled(Exception):
    """A user canceled a service operation before its commit."""


class ServiceProgress(QObject):
    """Poll worker progress at 20 Hz instead of queuing every download chunk."""

    changed = pyqtSignal(str, object, object)

    def __init__(self, message: str, parent: QObject | None = None):
        super().__init__(parent)
        self.cancel_event = Event()
        self._lock = Lock()
        self._committing = False
        self._value = (message, 0, None)
        self._last: tuple | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._flush)
        self._timer.start()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise OperationCancelled("Operation canceled. Your installed files were kept.")

    @property
    def cancelable(self) -> bool:
        with self._lock:
            return not self._committing and not self.cancel_event.is_set()

    def cancel(self) -> bool:
        with self._lock:
            if self._committing:
                return False
            self.cancel_event.set()
            return True

    def seal_commit(self) -> None:
        """Finish a short atomic commit once it has passed its final guard."""
        with self._lock:
            if self.cancel_event.is_set():
                raise OperationCancelled("Operation canceled. Your installed files were kept.")
            self._committing = True
            self._value = ("Finishing installation…", self._value[1], self._value[2])

    def __call__(self, message: str) -> None:
        self.check_cancelled()
        with self._lock:
            self._value = (str(message), self._value[1], self._value[2])

    def on_bytes(self, current: int, total: int | None) -> None:
        self.check_cancelled()
        with self._lock:
            self._value = (self._value[0], current, total)

    def _flush(self) -> None:
        with self._lock:
            value = self._value
        if value != self._last:
            self._last = value
            self.changed.emit(*value)

    def finish(self) -> None:
        self._flush()
        self._timer.stop()
