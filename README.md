# processit

A lightweight progress utility for Python --- built for both synchronous
and asynchronous iteration.

`processit` provides a simple, dependency-free progress bar for loops
that may be either regular iterables or async iterables.

---

## Installation

```bash
pip install processit
```

---

## Quick Example

### progress (sequential iteration)

```python
import asyncio
import time

from processit import progress

def numbers():
    for i in range(10):
        time.sleep(0.3)
        yield i

async def main():
    async for _ in progress(numbers(), total=10, desc="Numbers"):
        await asyncio.sleep(0)

asyncio.run(main())
```

> ⚠️ `progress` does **not** create concurrency.\
> It simply instruments iteration and renders a progress bar.

---

### Using `progress` with context manager

```python
import asyncio
import time

from processit import progress

def numbers():
    for i in range(10):
        time.sleep(0.3)
        yield i

async def main():
    async with progress(numbers(), total=10, desc='Numbers') as p:
        async for n in p:
            p.write(f'value: {n}')
            await asyncio.sleep(0.5)

asyncio.run(main())
```

---

## Concurrency & Parallelism

`progress(...)` does **not** parallelize work.

If you want true concurrency (e.g., HTTP calls, async DB operations,
async file IO), you must create tasks yourself and use
`track_as_completed(...)`.

---

### track_as_completed (parallel tasks)

```python
import asyncio
import random

from processit import track_as_completed

async def work(n: int) -> int:
    await asyncio.sleep(1.5 + random.random())
    return n * 2

async def main():
    tasks = [asyncio.create_task(work(i)) for i in range(10)]

    async for task in track_as_completed(tasks, total=len(tasks), desc="Parallel work"):
        result = await task
        print(result)

asyncio.run(main())
```

---

### Limiting concurrency with a semaphore

```python
import asyncio
from processit import track_as_completed

async def fetch(i: int) -> int:
    await asyncio.sleep(1)
    return i * 2

async def main():
    sem = asyncio.Semaphore(5)

    async def bounded(i: int):
        async with sem:
            return await fetch(i)

    tasks = [asyncio.create_task(bounded(i)) for i in range(20)]

    async for task in track_as_completed(tasks, total=len(tasks), desc="HTTP"):
        result = await task
        # process result

asyncio.run(main())
```

---

## Important Notes

### 1. Blocking code

If your iterable performs blocking operations (e.g. `time.sleep`,
synchronous file writes, synchronous DB access), the event loop will
still be blocked.

To avoid blocking:

- Use async libraries (`aiohttp`, async DB drivers, `aiofiles`, etc.)
- Or move blocking work to a thread:

```python
await asyncio.to_thread(blocking_function, arg1, arg2)
```

---

### 2. When to use each utility

Use case Recommended utility

---

Sequential iteration `progress(...)`
Parallel async tasks `track_as_completed(...)`
Need concurrency limit `Semaphore` + `track_as_completed(...)`

---

## More Examples

### Asynchronous iteration over a data source

```python
import asyncio
from processit import progress

async def fetch_items():
    for i in range(20):
        await asyncio.sleep(0.05)
        yield f"item-{i}"

async def main():
    async for item in progress(fetch_items(), total=20, desc="Fetching"):
        await asyncio.sleep(0.02)

asyncio.run(main())
```

---

### Processing without a defined total

```python
import asyncio
from processit import progress

items = [x ** 2 for x in range(100)]

async def main():
    async for value in progress(items, desc="Squaring"):
        await asyncio.sleep(0.01)

asyncio.run(main())
```

---

## Features

- Works with both **async** and **sync** iterables
- Displays **elapsed time**, **rate**, and **ETA** (when total is
  known)
- Automatically cleans up and prints a **final summary**
- No dependencies --- pure Python, fully type-hinted
- Easy to use drop-in function: `progress(iterable, ...)`

---

## API

### progress(iterable, total=None, \*, desc='Processing', width=30, refresh_interval=0.1, show_summary=True)

Creates and returns a `Progress` instance.

Name Type Description

---

`iterable` `Iterable[T] \| AsyncIterable[T]` Iterable to track
`total` `int \| None` Total number of iterations
`desc` `str` Text prefix shown before the bar
`width` `int` Width of the progress bar
`refresh_interval` `float` Time between updates
`show_summary` `bool` Whether to print final summary

---

### track_as_completed(tasks, total=None, \*, desc='Processing', width=30, refresh_interval=0.1, show_summary=True)

Tracks a collection of awaitables or tasks as they complete.

Name Type Description

---

`tasks` `Iterable[Awaitable[T]]` Tasks or coroutines to monitor
`total` `int \| None` Total number of tasks
`desc` `str` Text prefix shown before the bar
`width` `int` Width of the progress bar
`refresh_interval` `float` Time between updates
`show_summary` `bool` Whether to print final summary

---

## Design Philosophy

`processit` is intentionally minimal:

- No external dependencies\
- No hidden concurrency\
- Clear separation between instrumentation (`progress`) and
  concurrency (`track_as_completed`)

It focuses purely on progress rendering while leaving execution strategy
under your control.
