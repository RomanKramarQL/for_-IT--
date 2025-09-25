"""High level database queries for the cash flow application."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import db


def list_cashflows(filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    conditions = []
    params: List[Any] = []

    if filters.get("date_from"):
        conditions.append("recorded_on >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        conditions.append("recorded_on <= ?")
        params.append(filters["date_to"])
    if filters.get("status_id"):
        conditions.append("status_id = ?")
        params.append(filters["status_id"])
    if filters.get("type_id"):
        conditions.append("type_id = ?")
        params.append(filters["type_id"])
    if filters.get("category_id"):
        conditions.append("category_id = ?")
        params.append(filters["category_id"])
    if filters.get("subcategory_id"):
        conditions.append("subcategory_id = ?")
        params.append(filters["subcategory_id"])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sql = (
        "SELECT cashflows.id, recorded_on, amount_cents, comment, "
        "statuses.name AS status_name, types.name AS type_name, "
        "categories.name AS category_name, subcategories.name AS subcategory_name, "
        "cashflows.status_id, cashflows.type_id, cashflows.category_id, cashflows.subcategory_id "
        "FROM cashflows "
        "JOIN statuses ON cashflows.status_id = statuses.id "
        "JOIN types ON cashflows.type_id = types.id "
        "JOIN categories ON cashflows.category_id = categories.id "
        "JOIN subcategories ON cashflows.subcategory_id = subcategories.id "
        f"{where_clause} "
        "ORDER BY recorded_on DESC, cashflows.id DESC"
    )
    return db.fetchall(sql, params)


def get_cashflow(entry_id: int) -> Optional[Dict[str, Any]]:
    sql = (
        "SELECT id, recorded_on, status_id, type_id, category_id, subcategory_id, "
        "amount_cents, comment FROM cashflows WHERE id = ?"
    )
    return db.fetchone(sql, (entry_id,))


def create_cashflow(payload: Dict[str, Any]) -> int:
    sql = (
        "INSERT INTO cashflows(recorded_on, status_id, type_id, category_id, subcategory_id, amount_cents, comment) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    params = (
        payload["recorded_on"],
        payload["status_id"],
        payload["type_id"],
        payload["category_id"],
        payload["subcategory_id"],
        payload["amount_cents"],
        payload.get("comment"),
    )
    return db.execute(sql, params)


def update_cashflow(entry_id: int, payload: Dict[str, Any]) -> None:
    sql = (
        "UPDATE cashflows SET recorded_on = ?, status_id = ?, type_id = ?, category_id = ?, "
        "subcategory_id = ?, amount_cents = ?, comment = ? WHERE id = ?"
    )
    params = (
        payload["recorded_on"],
        payload["status_id"],
        payload["type_id"],
        payload["category_id"],
        payload["subcategory_id"],
        payload["amount_cents"],
        payload.get("comment"),
        entry_id,
    )
    db.execute(sql, params)


def delete_cashflow(entry_id: int) -> None:
    db.execute("DELETE FROM cashflows WHERE id = ?", (entry_id,))


def create_status(name: str) -> int:
    return db.execute("INSERT INTO statuses(name) VALUES (?)", (name,))


def update_status(status_id: int, name: str) -> None:
    db.execute("UPDATE statuses SET name = ? WHERE id = ?", (name, status_id))


def delete_status(status_id: int) -> None:
    db.execute("DELETE FROM statuses WHERE id = ?", (status_id,))


def create_type(name: str) -> int:
    return db.execute("INSERT INTO types(name) VALUES (?)", (name,))


def update_type(type_id: int, name: str) -> None:
    db.execute("UPDATE types SET name = ? WHERE id = ?", (name, type_id))


def delete_type(type_id: int) -> None:
    db.execute("DELETE FROM types WHERE id = ?", (type_id,))


def create_category(name: str, type_id: int) -> int:
    return db.execute(
        "INSERT INTO categories(name, type_id) VALUES (?, ?)",
        (name, type_id),
    )


def update_category(category_id: int, name: str, type_id: int) -> None:
    db.execute(
        "UPDATE categories SET name = ?, type_id = ? WHERE id = ?",
        (name, type_id, category_id),
    )


def delete_category(category_id: int) -> None:
    db.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def create_subcategory(name: str, category_id: int) -> int:
    return db.execute(
        "INSERT INTO subcategories(name, category_id) VALUES (?, ?)",
        (name, category_id),
    )


def update_subcategory(subcategory_id: int, name: str, category_id: int) -> None:
    db.execute(
        "UPDATE subcategories SET name = ?, category_id = ? WHERE id = ?",
        (name, category_id, subcategory_id),
    )


def delete_subcategory(subcategory_id: int) -> None:
    db.execute("DELETE FROM subcategories WHERE id = ?", (subcategory_id,))


def get_status(status_id: int) -> Optional[Dict[str, Any]]:
    return db.fetchone("SELECT id, name FROM statuses WHERE id = ?", (status_id,))


def get_type(type_id: int) -> Optional[Dict[str, Any]]:
    return db.fetchone("SELECT id, name FROM types WHERE id = ?", (type_id,))


def get_category(category_id: int) -> Optional[Dict[str, Any]]:
    return db.fetchone(
        "SELECT id, name, type_id FROM categories WHERE id = ?",
        (category_id,),
    )


def get_subcategory(subcategory_id: int) -> Optional[Dict[str, Any]]:
    return db.fetchone(
        "SELECT subcategories.id, subcategories.name, category_id, categories.type_id "
        "FROM subcategories JOIN categories ON subcategories.category_id = categories.id "
        "WHERE subcategories.id = ?",
        (subcategory_id,),
    )


def count_dependencies(table: str, column: str, value: int) -> int:
    query = f"SELECT COUNT(*) AS cnt FROM {table} WHERE {column} = ?"
    row = db.fetchone(query, (value,))
    return int(row["cnt"]) if row else 0
