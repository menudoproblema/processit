from __future__ import annotations

import asyncio
import contextlib
import sys
import time

from typing import TYPE_CHECKING, TextIO, cast


if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterable,
        AsyncIterator,
        Awaitable,
        Iterable,
    )


class Progress[T]:
    __slots__ = (
        '_is_tty',
        '_last_line_len',
        '_last_refresh',
        '_next_render_at',
        '_prefix',
        '_refresh_task',
        '_stopped',
        '_summary_printed',
        'count',
        'desc',
        'iterable',
        'refresh_interval',
        'show_summary',
        'start_time',
        'stream',
        'total',
        'width',
    )

    def __init__(  # noqa: PLR0913
        self,
        iterable: Iterable[T] | AsyncIterable[T],
        total: int | None = None,
        *,
        desc: str = 'Processing',
        width: int = 30,
        stream: TextIO | None = None,
        refresh_interval: float = 0.1,
        show_summary: bool = True,
    ) -> None:
        self.iterable = iterable
        self.total = total
        self.desc = desc
        self.width = width
        self.stream = stream or sys.stderr
        self.refresh_interval = refresh_interval
        self.show_summary = show_summary

        self.count = 0
        self.start_time = time.perf_counter()
        self._last_refresh = 0.0
        self._next_render_at = 0.0  # render inmediato al inicio
        self._refresh_task: asyncio.Task[None] | None = None
        self._summary_printed = False
        self._last_line_len = 0
        self._stopped = False
        self._is_tty = bool(getattr(self.stream, 'isatty', lambda: False)())
        self._prefix = f'{self.desc} '

    def write(self, msg: str = '') -> None:
        """Print a message below the bar and re-render it (TTY-safe)."""
        if self._stopped:
            return
        self._clear_line()
        if msg:
            if not msg.endswith('\n'):
                msg += '\n'
            self.stream.write(msg)
            self.stream.flush()
        self._render(force=True)

    def _format_elapsed(self, seconds: float) -> str:
        """Return hh:mm:ss, mm:ss or ss.s depending on duration."""
        if seconds < 60:  # noqa: PLR2004
            return f'{seconds:04.1f}s'
        minutes, secs = divmod(int(seconds), 60)
        if minutes < 60:  # noqa: PLR2004
            return f'{minutes:02d}:{secs:02d}'
        hours, minutes = divmod(minutes, 60)
        return f'{hours:02d}:{minutes:02d}:{secs:02d}'

    def _write_line(self, text: str) -> None:
        if self._is_tty:
            # \r = return, \x1b[2K = clear whole line (ANSI)
            self.stream.write('\r\x1b[2K' + text)
            self.stream.flush()
            self._last_line_len = len(text)
        else:
            # non-TTY (StringIO/logs): one line per render for deterministic
            # tests/logs
            self.stream.write(text + '\n')
            self.stream.flush()
            self._last_line_len = 0

    def _clear_line(self) -> None:
        if self._is_tty:
            self.stream.write('\r\x1b[2K')
            self.stream.flush()
            self._last_line_len = 0
        else:
            # non-TTY: renders are on separate lines; nothing to clear
            pass

    def _should_render(self, now: float) -> bool:
        # Permite render al inicio (_next_render_at=0) o si ha
        # pasado refresh_interval
        return now >= self._next_render_at or self._last_line_len == 0

    def _render(self, *, force: bool = False) -> None:
        if self._stopped:
            return

        now = time.perf_counter()
        if not force and not self._should_render(now):
            return

        elapsed = now - self.start_time
        rate = self.count / elapsed if elapsed > 0 else 0.0
        elapsed_str = self._format_elapsed(elapsed)

        eta_str = ''
        if self.total is not None and self.count > 0 and rate > 0:
            remaining = max(self.total - self.count, 0)
            eta = remaining / rate
            eta_str = f' ETA {self._format_elapsed(eta)}'

        if self.total:
            frac = min(self.count / self.total, 1.0)
            filled = int(self.width * frac)
            bar = f'[{"#" * filled}{"." * (self.width - filled)}]'
            percent = f'{frac * 100:6.2f}%'
            line = (
                f'{self._prefix}{bar} {percent} '
                f'({self.count}/{self.total}) {rate:.2f} it/s '
                f'{elapsed_str}{eta_str}'
            )
        else:
            line = (
                f'{self._prefix}{self.count} it '
                f'({rate:.2f} it/s {elapsed_str})'
            )

        self._write_line(line)
        self._last_refresh = now
        self._next_render_at = now + self.refresh_interval

    def _print_summary_if_needed(self) -> None:
        if self.show_summary and not self._summary_printed:
            self._stopped = True
            self._clear_line()

            elapsed = time.perf_counter() - self.start_time
            rate = self.count / elapsed if elapsed > 0 else 0.0
            elapsed_str = self._format_elapsed(elapsed)

            self.stream.write(
                f'{self.desc}: {self.count} it in {elapsed_str} '
                f'({rate:.2f} it/s)\n',
            )
            self.stream.flush()
            self._summary_printed = True

    async def _refresh_periodically(self) -> None:
        while not self._stopped:
            await asyncio.sleep(self.refresh_interval)
            if self._stopped:
                break
            self._render()

    async def __aenter__(self) -> Progress[T]:
        self._stopped = False
        self._render(force=True)  # feedback inmediato
        self._refresh_task = asyncio.create_task(self._refresh_periodically())
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._refresh_task
            self._refresh_task = None
        self._print_summary_if_needed()

    async def __aiter__(self) -> AsyncIterator[T]:
        started_here = False

        if self._refresh_task is None:
            self._stopped = False
            self._render(
                force=True,
            )  # feedback inmediato fuera de context manager
            self._refresh_task = asyncio.create_task(
                self._refresh_periodically(),
            )
            started_here = True

        try:
            if hasattr(self.iterable, '__aiter__'):
                async for item in cast('AsyncIterable[T]', self.iterable):
                    self.count += 1
                    self._render()
                    yield item
            else:
                for item in cast('Iterable[T]', self.iterable):
                    self.count += 1
                    self._render()
                    yield item
                    # cede el loop para no bloquear el refresco
                    await asyncio.sleep(0)
        finally:
            if started_here and self._refresh_task is not None:  # type: ignore
                self._refresh_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._refresh_task
                self._refresh_task = None
            self._print_summary_if_needed()


def progress[T](  # noqa: PLR0913
    iterable: Iterable[T] | AsyncIterable[T],
    total: int | None = None,
    *,
    desc: str = 'Processing',
    width: int = 30,
    refresh_interval: float = 0.1,
    show_summary: bool = True,
    stream: TextIO | None = None,
) -> Progress[T]:
    """Wrap an iterable or async iterable with a progress bar.

    Parameters
    ----------
    iterable: Iterable[T] | AsyncIterable[T]
        The iterable or async iterable to iterate over.
    total: int | None, optional
        Total number of elements. If not provided and `iterable` has
        `__len__`, it will be inferred automatically. Otherwise, ETA
        will not be displayed.
    desc: str, optional
        A short description displayed before the progress bar.
    width: int, optional
        The width (in characters) of the progress bar (default: 30).
    refresh_interval: float, optional
        Minimum time interval in seconds between display refreshes.
    show_summary: bool, optional
        Whether to print a final summary line showing total iterations,
        total time, and iteration rate (default: True).
    stream: TextIO | None, optional
        Output stream to render the bar (default: sys.stderr).

    Yields:
    ------
    T
        Each element from the iterable or async iterable, in order.
    """
    # Infer total if possible
    if total is None and hasattr(iterable, '__len__'):
        try:
            total = len(iterable)  # type: ignore[arg-type]
        except Exception:
            total = None

    return Progress(
        iterable,
        total,
        desc=desc,
        width=width,
        refresh_interval=refresh_interval,
        show_summary=show_summary,
        stream=stream,
    )


def track_as_completed[T](  # noqa: PLR0913
    tasks: Iterable[Awaitable[T]],
    *,
    total: int | None = None,
    desc: str = 'Processing',
    width: int = 30,
    refresh_interval: float = 0.1,
    show_summary: bool = True,
    stream: TextIO | None = None,
) -> Progress[asyncio.Future[T]]:
    """Iterate results as tasks complete, with a progress bar.

    Parameters
    ----------
    tasks: Iterable[Awaitable[T]]
        Awaitables or tasks to run/track.
    total: int | None, optional
        Total number of tasks. If not provided and `tasks` has `__len__`,
        it will be inferred. Otherwise, ETA will not be shown.
    desc: str
        Short description prefix for the bar.
    width: int
        Progress bar width (characters).
    refresh_interval: float
        Seconds between refreshes.
    show_summary: bool
        Whether to print a final summary line.
    stream: TextIO | None, optional
        Output stream to render the bar (default: sys.stderr).

    Returns:
    -------
    Progress[Future[T]]
        An async-iterable of **futures** (await them in the loop).

    Notes:
    -----
    We *avoid* passing the synchronous iterator from
    `asyncio.as_completed(...)` directly to `Progress`, since its `next()` can
    block the event loop. Instead, we drive completion asynchronously using
    `asyncio.wait(FIRST_COMPLETED)`.
    """
    # Infer total if possible
    if total is None and hasattr(tasks, '__len__'):
        try:
            total = len(tasks)  # type: ignore[arg-type]
        except Exception:
            total = None

    async def _as_completed_async() -> AsyncIterable[asyncio.Future[T]]:
        pending: set[asyncio.Future[T]] = {
            asyncio.ensure_future(t)
            for t in tasks  # type: ignore[arg-type]
        }
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for fut in done:
                    yield fut
        finally:
            # No cancelamos 'pending' por defecto (el consumidor decide su
            # ciclo de vida).
            pass

    return progress(
        _as_completed_async(),
        total=total,
        desc=desc,
        width=width,
        refresh_interval=refresh_interval,
        show_summary=show_summary,
        stream=stream,
    )
