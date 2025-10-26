# processit

A lightweight progress utility for Python — built for both synchronous and asynchronous iteration.

`processit` provides a simple, dependency-free progress bar for loops that may be either regular iterables or async iterables.

---

## Installation

```bash
pip install processit
```

---

## Quick Example

### progress

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

```
Numbers [#############.................]  50.00% (5/10) 4.92 it/s 02.1s ETA 02.1s
Numbers: 10 it in 04.1s (2.43 it/s)
```

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

### track_as_completed

```python
import asyncio
import random

from processit import track_as_completed

async def work(n: int) -> int:
    await asyncio.sleep(1.5 + random.random())
    return n * 2

async def main():
    tasks = [work(i) for i in range(10)]
    async for fut in track_as_completed(tasks, desc="Parallel work"):
        await fut

asyncio.run(main())
```

```
Parallel work [#####################.........]  70.00% (7/10) 68.68 it/s 00.1s ETA 00.0s14
Parallel work: 10 it in 00.1s (98.01 it/s)
```

```python
import asyncio

from processit import track_as_completed

async def work(i: int) -> int:
    await asyncio.sleep(2)
    return i * 2

async def main():
    tasks = [work(i) for i in range(10)]
    async with track_as_completed(tasks, desc="Parallel work") as p:
        async for task in p:       # itera mientras re-renderiza
            result = await task
            p.write(f"done: {result}")  # en vez de print(result)
            await asyncio.sleep(2)

asyncio.run(main())
```

## More examples

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

### Processing a list without a defined total

```python
import asyncio

from processit import progress

items = [x ** 2 for x in range(100)]

async def main():
    async for value in progress(items, desc="Squaring"):
        await asyncio.sleep(0.01)

asyncio.run(main())
```

### Using an async with context

```python
import asyncio

from processit import progress

async def numbers():
    for i in range(8):
        await asyncio.sleep(0.1)
        yield i

async def main():
    async with progress(numbers(), total=8, desc="Context mode") as p:
        async for n in p:
            await asyncio.sleep(0.05)

asyncio.run(main())
```

### Synchronous iterator in an asynchronous environment

```python
import asyncio
import time

from processit import progress

def blocking_iter():
    for i in range(5):
        time.sleep(0.4)
        yield i

async def main():
    async for n in progress(blocking_iter(), total=5, desc="Blocking loop"):
        await asyncio.sleep(0)

asyncio.run(main())
```

---

## Features

✅ Works with both **async** and **sync** iterables
✅ Displays **elapsed time**, **rate**, and **ETA** (when total is known)
✅ Automatically cleans up and prints a **final summary**
✅ **No dependencies** — pure Python, fully type-hinted
✅ Easy to use drop-in function: `progress(iterable, ...)`

---

## API

### `progress(iterable, total=None, *, desc='Processing', width=30, refresh_interval=0.1, show_summary=True)`

Creates and returns a `Progress` instance.

#### Parameters
| Name | Type | Description |
|------|------|-------------|
| `iterable` | `Iterable[T] | AsyncIterable[T]` | The iterable or async iterable to track. |
| `total` | `int | None` | Total number of iterations (optional). |
| `desc` | `str` | A short description shown before the bar. |
| `width` | `int` | Width of the progress bar (default: 30). |
| `refresh_interval` | `float` | Time in seconds between updates. |
| `show_summary` | `bool` | Whether to show a final summary line (default: `True`). |

---

## Usage with Regular Iterables

```python
from processit import progress
import time

def numbers():
    for i in range(5):
        time.sleep(0.3)
        yield i

async def main():
    async for n in progress(numbers(), total=5, desc="Sync loop"):
        await asyncio.sleep(0)

import asyncio
asyncio.run(main())
```
