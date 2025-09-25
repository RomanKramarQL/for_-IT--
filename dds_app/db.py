"""Database helpers for the cash flow web application."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Iterator, List, Optional

DB_PATH = Path(__file__).resolve().parent / "dds.sqlite3"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL REFERENCES types(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(type_id, name)
);

CREATE TABLE IF NOT EXISTS subcategories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE(category_id, name)
);

CREATE TABLE IF NOT EXISTS cashflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_on DATE NOT NULL,
    status_id INTEGER NOT NULL REFERENCES statuses(id),
    type_id INTEGER NOT NULL REFERENCES types(id),
    category_id INTEGER NOT NULL REFERENCES categories(id),
    subcategory_id INTEGER NOT NULL REFERENCES subcategories(id),
    amount_cents INTEGER NOT NULL,
    comment TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with useful defaults."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_cursor(commit: bool = False) -> Iterator[sqlite3.Cursor]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create database schema if it does not exist."""
    with db_cursor(commit=True) as cur:
        cur.executescript(SCHEMA)
    ensure_initial_data()


DEFAULT_STATUSES = [
    "Бизнес",
    "Личное",
    "Налог",
]

DEFAULT_TYPES = [
    "Пополнение",
    "Списание",
]

DEFAULT_CATEGORIES = [
    ("Инфраструктура", "Списание", ["VPS", "Proxy"]),
    ("Маркетинг", "Списание", ["Farpost", "Avito"]),
    ("Прочее", "Пополнение", ["Инвестиции", "Возврат долга"]),
]


def ensure_initial_data() -> None:
    """Seed the reference tables with basic values."""
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT COUNT(*) FROM statuses")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO statuses(name) VALUES (?)",
                            [(name,) for name in DEFAULT_STATUSES])

        cur.execute("SELECT COUNT(*) FROM types")
        if cur.fetchone()[0] == 0:
            cur.executemany("INSERT INTO types(name) VALUES (?)",
                            [(name,) for name in DEFAULT_TYPES])

        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            for category_name, type_name, subcats in DEFAULT_CATEGORIES:
                cur.execute("SELECT id FROM types WHERE name = ?", (type_name,))
                row = cur.fetchone()
                if not row:
                    continue
                type_id = row[0]
                cur.execute(
                    "INSERT INTO categories(name, type_id) VALUES (?, ?)",
                    (category_name, type_id),
                )
                category_id = cur.lastrowid
                cur.executemany(
                    "INSERT INTO subcategories(name, category_id) VALUES (?, ?)",
                    [(sub, category_id) for sub in subcats],
                )


def fetchall(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
    return [dict(row) for row in rows]


def fetchone(sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    with db_cursor() as cur:
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
    return dict(row) if row else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with db_cursor(commit=True) as cur:
        cur.execute(sql, tuple(params))
        return cur.lastrowid


def executemany(sql: str, params_seq: Iterable[Iterable[Any]]) -> None:
    with db_cursor(commit=True) as cur:
        cur.executemany(sql, [tuple(params) for params in params_seq])


@dataclass
class ReferenceLists:
    statuses: List[Dict[str, Any]]
    types: List[Dict[str, Any]]
    categories: List[Dict[str, Any]]
    subcategories: List[Dict[str, Any]]


def load_reference_lists() -> ReferenceLists:
    statuses = fetchall("SELECT id, name FROM statuses ORDER BY name")
    types = fetchall("SELECT id, name FROM types ORDER BY name")
    categories = fetchall(
        "SELECT categories.id, categories.name, type_id, types.name AS type_name "
        "FROM categories JOIN types ON categories.type_id = types.id "
        "ORDER BY types.name, categories.name"
    )
    subcategories = fetchall(
        "SELECT subcategories.id, subcategories.name, category_id, categories.name AS category_name, categories.type_id "
        "FROM subcategories JOIN categories ON subcategories.category_id = categories.id "
        "ORDER BY categories.name, subcategories.name"
    )
    return ReferenceLists(statuses=statuses, types=types, categories=categories, subcategories=subcategories)


def ensure_database() -> None:
    """Create the SQLite database on first run."""
    if not DB_PATH.exists():
        init_db()
    else:
        # Обеспечиваем применение обновлений схемы при изменении кода.
        with db_cursor(commit=True) as cur:
            cur.executescript(SCHEMA)
        ensure_initial_data()
