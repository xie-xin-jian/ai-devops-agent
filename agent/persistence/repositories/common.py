"""Shared helpers for persistence repositories."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from sqlalchemy import inspect as sql_inspect
from sqlalchemy import or_
from sqlalchemy import update as sql_update


def record_to_dict(record: Any) -> dict:
    """Accept a mapping or any object exposing ``to_dict()``."""
    if isinstance(record, Mapping):
        return dict(record)
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    raise TypeError("record must be a mapping or expose to_dict()")


def _column_keys(model) -> dict[str, str]:
    """Map both ORM attribute names and column keys to the column key.

    ``TaskRecord.task_metadata`` is mapped to the column ``metadata``, so
    SQL statements that bypass the ORM (``set_`` clauses, Core updates) must
    translate the attribute name themselves.
    """
    keys: dict[str, str] = {}
    for attribute in sql_inspect(model).column_attrs:
        column_key = attribute.columns[0].key
        keys[attribute.key] = column_key
        keys[column_key] = column_key
    return keys


def upsert_row(
    session,
    model,
    values: dict,
    *,
    conflict_columns: Sequence[str],
    update_columns: Sequence[str],
    force: bool = False,
) -> None:
    """Insert a row, or update it when the conflict target already exists.

    ``version`` is bumped by the database on every real change, which gives
    the future PG-native read path a revision counter. The update is skipped
    when no mirrored column differs, so replaying an unchanged record does
    not inflate the revision; ``force`` writes anyway.

    Dialects without an upsert construct fall back to a read-modify-write,
    which is enough for the local SQLite path used by unit tests.
    """
    dialect = session.get_bind().dialect.name
    statement = build_upsert_statement(
        model,
        values,
        dialect=dialect,
        conflict_columns=conflict_columns,
        update_columns=update_columns,
        force=force,
    )
    if statement is None:
        _merge_row(session, model, values)
        return
    session.execute(statement)


def build_upsert_statement(
    model,
    values: dict,
    *,
    dialect: str,
    conflict_columns: Sequence[str],
    update_columns: Sequence[str],
    force: bool = False,
):
    """Build the dialect upsert statement, or ``None`` when unsupported."""
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:
        return None

    table = model.__table__
    keys = _column_keys(model)
    statement = dialect_insert(model).values(**values)
    # The SET clause must reference ``excluded`` (the row proposed by this
    # execution) instead of embedding literal values: with executemany the
    # literals would be bound once and every row would be updated with the
    # same payload.
    set_values = {
        keys[name]: statement.excluded[keys[name]]
        for name in update_columns
        if name in keys
    }
    if not set_values:
        raise ValueError(
            f"no updatable columns for {model.__tablename__}: {update_columns}"
        )
    if "version" in table.c:
        set_values["version"] = table.c.version + 1

    # "Changed" means any mirrored column differs. A single timestamp column
    # is not enough: the memory access counters, for example, change without
    # touching updated_at, and a marker-based check silently skipped them.
    where = None
    if not force:
        predicates = [
            table.c[keys[name]].is_distinct_from(statement.excluded[keys[name]])
            for name in update_columns
            if name in keys
        ]
        if predicates:
            where = or_(*predicates)

    return statement.on_conflict_do_update(
        index_elements=list(conflict_columns),
        set_=set_values,
        where=where,
    )


def update_row_if_version(
    session,
    model,
    record_id: str,
    expected_version: int,
    values: dict,
) -> bool:
    """Conditional update used to detect concurrent writers.

    Returns ``False`` when the row is gone or its version moved on, so the
    caller can retry or report a conflict instead of silently overwriting
    another writer's change.
    """
    table = model.__table__
    keys = _column_keys(model)
    payload = {
        keys[key]: value
        for key, value in values.items()
        if key != "version" and key in keys
    }
    result = session.execute(
        sql_update(table)
        .where(
            table.c.id == record_id,
            table.c.version == expected_version,
        )
        .values(**payload, version=expected_version + 1)
    )
    return bool(result.rowcount)


def _merge_row(session, model, values: dict) -> None:
    primary_key = [column.name for column in sql_inspect(model).primary_key]
    identity = tuple(values.get(name) for name in primary_key)
    if not primary_key or any(value is None for value in identity):
        session.add(model(**values))
        return
    existing = session.get(
        model,
        identity[0] if len(identity) == 1 else identity,
    )
    if existing is None:
        session.add(model(**values))
        return
    for key, value in values.items():
        setattr(existing, key, value)


__all__ = [
    "build_upsert_statement",
    "record_to_dict",
    "update_row_if_version",
    "upsert_row",
]
