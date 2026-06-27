from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from app.core.config import settings

T = TypeVar("T")
_MISSING = object()


def clean_data_fingerprint(filenames: Iterable[str]) -> tuple[object, ...]:
    fingerprint: list[object] = [str(settings.data_dir)]
    for filename in filenames:
        path = settings.clean_dir / filename
        try:
            stat = path.stat()
        except OSError:
            fingerprint.extend([str(path), None, None])
            continue
        fingerprint.extend([str(path), stat.st_mtime_ns, stat.st_size])
    return tuple(fingerprint)


class FingerprintCache:
    def __init__(self, max_items: int = 64) -> None:
        self.max_items = max_items
        self._values: OrderedDict[tuple[object, ...], Any] = OrderedDict()

    def get(self, key: tuple[object, ...]) -> Any | None:
        value = self._values.get(key, _MISSING)
        if value is _MISSING:
            return None
        self._values.move_to_end(key)
        return value

    def set(self, key: tuple[object, ...], value: Any) -> Any:
        self._values[key] = value
        self._values.move_to_end(key)
        while len(self._values) > self.max_items:
            self._values.popitem(last=False)
        return value

    def get_or_create(self, key: tuple[object, ...], factory: Callable[[], T]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached
        return self.set(key, factory())

    def clear(self) -> None:
        self._values.clear()
