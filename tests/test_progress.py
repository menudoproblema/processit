# tests/test_processit.py
from __future__ import annotations

import asyncio
import io
import time

from typing import TYPE_CHECKING

import pytest

from processit.progress import Progress, progress, track_as_completed


if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator


# -----------------------------
# Helpers
# -----------------------------


def _strip_ansi(s: str) -> str:
    # El progreso usa \r y \x1b[2K; limpiamos para aserciones más simples
    s = s.replace('\r', '')
    return s.replace('\x1b[2K', '')


def _last_nonempty_line(buf: str) -> str:
    for line in reversed(buf.splitlines()):
        if line.strip():
            return line
    return ''


# -----------------------------
# Synchronous iterable cases
# -----------------------------


@pytest.mark.asyncio
async def test_sync_iterable_basic_summary_only_once():
    stream = io.StringIO()

    def numbers() -> Iterator[int]:
        for i in range(5):
            time.sleep(0.01)
            yield i

    # Consumo como async for (la clase cede el loop con await asyncio.sleep(0))
    async for _ in progress(
        numbers(),
        desc='Numbers',
        total=5,
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    # Debe haber un único resumen final
    assert out.count('Numbers: 5 it in ') == 1
    assert 'it/s' in out


@pytest.mark.asyncio
async def test_sync_iterable_infers_total_from_len():
    stream = io.StringIO()
    data = list(range(4))  # tiene __len__
    async for _ in progress(
        data,
        desc='Len inf',
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)
    out = stream.getvalue()
    # En algún render debe aparecer (4/4)
    assert '(4/4)' in out


# -----------------------------
# Async iterable cases
# -----------------------------


@pytest.mark.asyncio
async def test_async_iterable_basic():
    stream = io.StringIO()

    async def agen() -> AsyncIterator[int]:
        for i in range(6):
            await asyncio.sleep(0.01)
            yield i

    async for _ in progress(
        agen(),
        total=6,
        desc='Agen',
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert out.count('Agen: 6 it in ') == 1
    assert 'it/s' in out


@pytest.mark.asyncio
async def test_async_iterable_without_total():
    stream = io.StringIO()

    async def agen() -> AsyncIterator[int]:
        for i in range(3):
            await asyncio.sleep(0.005)
            yield i

    # Sin total explícito; el resumen siempre debe estar
    async for _ in progress(
        agen(),
        desc='No total',
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    assert 'No total: 3 it in ' in out
    # No forzamos presencia de '%' porque sin total no hay porcentaje en barra


# -----------------------------
# Context manager + write()
# -----------------------------


@pytest.mark.asyncio
async def test_async_with_and_write_no_extra_bar_at_end():
    stream = io.StringIO()

    def numbers() -> Iterator[int]:
        for i in range(5):
            time.sleep(0.01)
            yield i

    async with progress(
        numbers(),
        total=5,
        desc='With',
        stream=stream,
        refresh_interval=1.0,
    ) as p:
        async for n in p:
            p.write(f'value: {n}')
            await asyncio.sleep(0)

    out = _strip_ansi(stream.getvalue())
    # El último renglón no debe ser una barra, sino el resumen
    last = _last_nonempty_line(out)
    assert last.startswith('With: 5 it in ')
    # Y que no haya texto de barra después del resumen
    assert 'With [' not in last


# -----------------------------
# track_as_completed cases
# -----------------------------


@pytest.mark.asyncio
async def test_track_as_completed_varied_durations():
    stream = io.StringIO()

    async def work(n: int) -> int:
        # Duraciones variadas: 0.01..0.06
        await asyncio.sleep(0.01 * (n % 6 + 1))
        return n

    tasks = [work(i) for i in range(10)]

    # Itera devolviendo futuros; hacemos await dentro del bucle
    async for fut in track_as_completed(
        tasks,
        desc='Parallel',
        stream=stream,
        refresh_interval=0.02,
    ):
        _ = await fut  # procesar resultado

    out = _strip_ansi(stream.getvalue())
    assert 'Parallel: 10 it in ' in out


@pytest.mark.asyncio
async def test_track_as_completed_equal_durations_still_counts():
    stream = io.StringIO()

    async def work(n: int) -> int:
        await asyncio.sleep(0.02)  # todas igual
        return n

    tasks = [work(i) for i in range(8)]
    async for fut in track_as_completed(
        tasks,
        desc='Equal',
        stream=stream,
        refresh_interval=0.02,
    ):
        _ = await fut

    out = _strip_ansi(stream.getvalue())
    assert 'Equal: 8 it in ' in out


# -----------------------------
# show_summary flag
# -----------------------------


@pytest.mark.asyncio
async def test_show_summary_false():
    stream = io.StringIO()
    data = [1, 2, 3]
    async for _ in progress(
        data,
        desc='NoSum',
        show_summary=False,
        stream=stream,
        refresh_interval=1.0,
    ):
        await asyncio.sleep(0)
    out = _strip_ansi(stream.getvalue())
    # No debe haber resumen
    assert 'NoSum: 3 it in ' not in out


# -----------------------------
# stream wiring & basic type use
# -----------------------------


@pytest.mark.asyncio
async def test_progress_stream_stdout_like():
    # Simulamos sys.stdout con StringIO
    stream = io.StringIO()

    async def agen():
        for i in range(2):
            await asyncio.sleep(0.005)
            yield i

    async for _ in progress(
        agen(),
        total=2,
        desc='Stdout',
        stream=stream,
        refresh_interval=1.0,
    ):
        pass
    out = _strip_ansi(stream.getvalue())
    assert 'Stdout: 2 it in ' in out


# -----------------------------
# smoke test: Progress usable directamente
# -----------------------------


@pytest.mark.asyncio
async def test_progress_class_direct_use():
    stream = io.StringIO()

    async def agen():
        for i in range(3):
            await asyncio.sleep(0.003)
            yield i

    p = Progress(
        agen(),
        total=3,
        desc='Class',
        stream=stream,
        refresh_interval=1.0,
    )
    async with p:
        async for _ in p:
            await asyncio.sleep(0)
    out = _strip_ansi(stream.getvalue())
    assert 'Class: 3 it in ' in out


# -----------------------------
# ETA presence only when total is known (heurística simple)
# -----------------------------


@pytest.mark.asyncio
async def test_eta_only_when_total_known():
    stream1 = io.StringIO()
    stream2 = io.StringIO()

    async def agen():
        for i in range(3):
            await asyncio.sleep(0.005)
            yield i

    # Con total -> debería haber "ETA"
    async for _ in progress(
        agen(),
        total=3,
        desc='HasTotal',
        stream=stream1,
        refresh_interval=1.0,
    ):
        pass

    # Sin total -> preferimos que no aparezca "ETA" en la salida
    async for _ in progress(
        agen(),
        desc='NoTotal',
        stream=stream2,
        refresh_interval=1.0,
    ):
        pass

    out1 = stream1.getvalue()
    out2 = stream2.getvalue()
    assert 'ETA' in out1
    assert 'ETA' not in out2
