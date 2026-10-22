import re

import pandas as pd

from src.db import run_query

ADMIN_ROLE = "ADMIN"
PROTECTED_TABLE = "PRODUCTION_ORDERS"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")


def valid_identifier(name: str) -> bool:
    return bool(_IDENT.match(name or ""))


def normalise(name: str) -> str:
    return (name or "").strip().upper()


def registered_tables() -> pd.DataFrame:
    return run_query("SELECT TABLE_NAME, DISPLAY_NAME, OWNER_COLUMN FROM DATASETS ORDER BY DISPLAY_NAME")


def known_roles() -> list[str]:
    df = run_query(
        "SELECT ROLE_NAME FROM ROLE_COLUMN_ACCESS UNION SELECT ROLE_NAME FROM ROLE_DATASET_ACCESS ORDER BY 1"
    )
    roles = [r for r in df["ROLE_NAME"] if r != ADMIN_ROLE]
    return [ADMIN_ROLE] + sorted(roles)


def table_columns(table: str) -> list[str]:
    if not valid_identifier(table):
        raise ValueError("That is not a valid table name. Use letters, numbers and underscores, e.g. APP_DB.PUBLIC.MY_TABLE.")
    return list(run_query(f"SELECT * FROM {table} LIMIT 0").columns)


def browse_schema(schema: str) -> list[str]:
    if not valid_identifier(schema) or schema.count(".") != 1:
        raise ValueError("Use DATABASE.SCHEMA, for example APP_DB.PUBLIC.")
    return list(run_query(f"SHOW TABLES IN SCHEMA {schema}")["name"])


def current_rules(table: str) -> dict:
    df = run_query(
        "SELECT ROLE_NAME, COLUMN_NAME, CAN_VIEW, CAN_EDIT FROM ROLE_COLUMN_ACCESS WHERE TABLE_NAME = %(t)s",
        {"t": table},
    )
    return {(r.COLUMN_NAME, r.ROLE_NAME): (bool(r.CAN_VIEW), bool(r.CAN_EDIT)) for r in df.itertuples(index=False)}


def open_roles(table: str) -> list[str]:
    df = run_query("SELECT ROLE_NAME FROM ROLE_DATASET_ACCESS WHERE TABLE_NAME = %(t)s", {"t": table})
    return list(df["ROLE_NAME"])


def recent_changes(limit: int = 50) -> pd.DataFrame:
    return run_query(
        f"SELECT CHANGED_AT, ADMIN_USER, ACTION, TABLE_NAME, DETAILS FROM ADMIN_CHANGE_LOG "
        f"ORDER BY CHANGED_AT DESC LIMIT {int(limit)}"
    )


def log_change(admin: str, action: str, table: str, details: str = "") -> None:
    run_query(
        "INSERT INTO ADMIN_CHANGE_LOG (ADMIN_USER, ACTION, TABLE_NAME, DETAILS) "
        "VALUES (%(a)s, %(x)s, %(t)s, %(d)s)",
        {"a": admin, "x": action, "t": table, "d": details[:900]},
    )


def _rules_insert(table, columns, roles, view, edit):
    rows, params, n = [], {"t": table}, 0
    for c in columns:
        for r in roles:
            v = True if r == ADMIN_ROLE else bool(view.get((c, r), False))
            e = bool(edit.get((c, r), False)) and v
            rows.append(f"(%(r{n})s, %(c{n})s, %(v{n})s, %(e{n})s, %(t)s)")
            params.update({f"r{n}": r, f"c{n}": c, f"v{n}": v, f"e{n}": e})
            n += 1
    sql = ("INSERT INTO ROLE_COLUMN_ACCESS (ROLE_NAME, COLUMN_NAME, CAN_VIEW, CAN_EDIT, TABLE_NAME) VALUES "
           + ", ".join(rows))
    return sql, params


def _access_insert(table, roles):
    roles = sorted(set(roles) | {ADMIN_ROLE})
    rows = ", ".join(f"(%(r{i})s, %(t)s)" for i in range(len(roles)))
    params = {"t": table, **{f"r{i}": r for i, r in enumerate(roles)}}
    return f"INSERT INTO ROLE_DATASET_ACCESS (ROLE_NAME, TABLE_NAME) VALUES {rows}", params


def describe_changes(old: dict, columns, roles, view, edit, old_open, new_open) -> str:
    out = []
    for c in columns:
        for r in roles:
            ov, oe = old.get((c, r), (False, False))
            nv = True if r == ADMIN_ROLE else bool(view.get((c, r), False))
            ne = bool(edit.get((c, r), False)) and nv
            if ov != nv:
                out.append(f"{r} view {c} {'on' if nv else 'off'}")
            if oe != ne:
                out.append(f"{r} edit {c} {'on' if ne else 'off'}")
    for r in sorted(set(new_open) - set(old_open)):
        out.append(f"{r} can open table")
    for r in sorted(set(old_open) - set(new_open) - {ADMIN_ROLE}):
        out.append(f"{r} cannot open table")
    return f"{len(out)} change(s): " + "; ".join(out) if out else "no access changes"


def register_table(admin: str, table: str, display: str, owner: str | None, columns: list[str], roles: list[str]) -> None:
    """New tables start visible to ADMIN only (fail closed). Open them up afterwards."""
    if not valid_identifier(table):
        raise ValueError("Invalid table name.")
    run_query(
        "INSERT INTO DATASETS (TABLE_NAME, DISPLAY_NAME, OWNER_COLUMN) "
        "SELECT %(t)s, %(d)s, %(o)s WHERE NOT EXISTS (SELECT 1 FROM DATASETS WHERE TABLE_NAME = %(t)s)",
        {"t": table, "d": display, "o": owner},
    )
    run_query("DELETE FROM ROLE_COLUMN_ACCESS WHERE TABLE_NAME = %(t)s", {"t": table})
    sql, params = _rules_insert(table, columns, roles, {}, {})
    run_query(sql, params)
    run_query("DELETE FROM ROLE_DATASET_ACCESS WHERE TABLE_NAME = %(t)s", {"t": table})
    sql, params = _access_insert(table, [ADMIN_ROLE])
    run_query(sql, params)
    log_change(admin, "REGISTER_TABLE", table, f"display name '{display}', owner column {owner or 'none'}, admin-only to start")


def save_access(admin, table, display, owner, columns, roles, view, edit, open_pick) -> str:
    old = current_rules(table)
    old_open = open_roles(table)
    summary = describe_changes(old, columns, roles, view, edit, old_open, open_pick)
    run_query("UPDATE DATASETS SET DISPLAY_NAME = %(d)s, OWNER_COLUMN = %(o)s WHERE TABLE_NAME = %(t)s",
              {"d": display, "o": owner, "t": table})
    # delete then insert: if anything fails in between, the table is closed to everyone, never open
    run_query("DELETE FROM ROLE_COLUMN_ACCESS WHERE TABLE_NAME = %(t)s", {"t": table})
    sql, params = _rules_insert(table, columns, roles, view, edit)
    run_query(sql, params)
    run_query("DELETE FROM ROLE_DATASET_ACCESS WHERE TABLE_NAME = %(t)s", {"t": table})
    sql, params = _access_insert(table, open_pick)
    run_query(sql, params)
    log_change(admin, "SAVE_ACCESS", table, summary)
    return summary


def unregister_table(admin: str, table: str) -> None:
    if table == PROTECTED_TABLE:
        raise ValueError("This table is used by the Data and Executive pages and cannot be removed.")
    for sql in ("DELETE FROM ROLE_DATASET_ACCESS WHERE TABLE_NAME = %(t)s",
                "DELETE FROM ROLE_COLUMN_ACCESS WHERE TABLE_NAME = %(t)s",
                "DELETE FROM METRICS WHERE TABLE_NAME = %(t)s",
                "DELETE FROM DATASETS WHERE TABLE_NAME = %(t)s"):
        run_query(sql, {"t": table})
    log_change(admin, "UNREGISTER_TABLE", table, "table removed from the app (the Snowflake table itself is untouched)")


def column_descriptions(table: str) -> dict:
    df = run_query("SELECT COLUMN_NAME, DESCRIPTION FROM COLUMN_DESCRIPTIONS WHERE TABLE_NAME = %(t)s", {"t": table})
    return dict(zip(df["COLUMN_NAME"], df["DESCRIPTION"]))


def save_descriptions(admin: str, table: str, columns: list[str], descs: dict) -> int:
    old = column_descriptions(table)
    changed = [c for c in columns if (old.get(c) or "") != descs.get(c, "")]
    run_query("DELETE FROM COLUMN_DESCRIPTIONS WHERE TABLE_NAME = %(t)s", {"t": table})
    keep = [(c, descs[c][:300]) for c in columns if descs.get(c)]
    if keep:
        rows, params = [], {"t": table}
        for i, (c, d) in enumerate(keep):
            rows.append(f"(%(t)s, %(c{i})s, %(d{i})s)")
            params[f"c{i}"] = c
            params[f"d{i}"] = d
        run_query("INSERT INTO COLUMN_DESCRIPTIONS (TABLE_NAME, COLUMN_NAME, DESCRIPTION) VALUES " + ", ".join(rows), params)
    log_change(admin, "SAVE_DESCRIPTIONS", table,
               f"{len(changed)} description(s) changed: " + ", ".join(changed) if changed else "no description changes")
    return len(changed)
