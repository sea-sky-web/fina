from collections.abc import Iterator
from contextlib import contextmanager

import duckdb

from app.core.config import settings


@contextmanager
def duckdb_connection() -> Iterator[duckdb.DuckDBPyConnection]:
    settings.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(settings.duckdb_path))
    try:
        yield connection
    finally:
        connection.close()
