"""Turns a validated chart request into a Snowflake query and runs it.

The AI never writes SQL. Table and column names come from the allowed schema and are
checked again here; values always go through parameters; the role's row rule is added here.
"""
from datetime import date, timedelta

import pandas as pd

from src.agent.schema import SAFE_NAME
from src.agent.validator import AGGS, BUCKETS
from src.datasets import _actual_columns
from src.db import run_query

MAX_GROUPS = 1000
_FUNCS = {"Sum": "SUM", "Average": "AVG", "Min": "MIN", "Max": "MAX", "Count": "COUNT"}


def _need(schema: dict, table: str, column: str) -> str:
    """Return a safely quotable column name, or raise if it is not allowed for this role."""
    if table not in schema or column not in schema[table]["columns"] or not SAFE_NAME.match(column):
        raise ValueError(f"Column {column} is not available.")
    return f'"{column}"'


def _scope(user: dict, table: str, schema: dict):
    """Row rule. Anything other than ALL is treated as own-rows-only (fail closed)."""
    if user.get("row_scope") == "ALL":
        return None, {}
    owner = schema[table]["owner_column"]
    if not owner or not SAFE_NAME.match(owner) or owner not in _actual_columns(table):
        raise ValueError("Your role can only see its own rows, and this table has no owner column.")
    return f'"{owner}" = %(owner)s', {"owner": user["username"]}


def alias_of(measure: dict) -> str:
    return "ROW_COUNT" if measure["column"] is None else f'{measure["agg"].upper()}_{measure["column"]}'


def _date_clauses(col: str, f: dict, i: int):
    """WHERE parts for one date filter. Dates go through parameters as ISO text."""
    y, m = f.get("year"), f.get("month")
    lo = f.get("from")
    hi = (date.fromisoformat(f["to"]) + timedelta(days=1)).isoformat() if f.get("to") else None
    if y and m:
        s, e = date(y, m, 1), date(y + (m == 12), m % 12 + 1, 1)
    elif y:
        s, e = date(y, 1, 1), date(y + 1, 1, 1)
    else:
        s = e = None
    if s:
        lo = max(lo, s.isoformat()) if lo else s.isoformat()
        hi = min(hi, e.isoformat()) if hi else e.isoformat()
    parts, params = [], {}
    if lo:
        parts.append(f"{col} >= %(d{i}_lo)s")
        params[f"d{i}_lo"] = lo
    if hi:
        parts.append(f"{col} < %(d{i}_hi)s")
        params[f"d{i}_hi"] = hi
    if m and not y:
        parts.append(f"MONTH({col}) = %(d{i}_m)s")
        params[f"d{i}_m"] = int(m)
    ms = f.get("months")
    if ms:
        ms = sorted({int(v) for v in ms})
        if ms[0] < 1 or ms[-1] > 12:
            raise ValueError("Bad month list.")
        names = []
        for j, v in enumerate(ms):
            params[f"d{i}_ms{j}"] = v
            names.append(f"%(d{i}_ms{j})s")
        parts.append(f"MONTH({col}) IN ({', '.join(names)})")
    return parts, params


def compile_spec(user: dict, spec: dict, schema: dict):
    """Returns (sql, params, info). info names the result columns for the chart step."""
    table = spec["table"]
    if table not in schema:
        raise ValueError("Table is not available.")
    cols = schema[table]["columns"]
    if spec.get("chart") == "Table":
        dim_names = list(spec.get("group_by") or [])
    else:
        dim_names = [spec["x"]] + ([spec["color"]] if spec.get("color") else [])
    bucket = spec.get("bucket")
    if bucket and bucket not in BUCKETS:
        raise ValueError("Bad date grouping.")

    select, date_dims = [], []
    for name in dim_names:
        c = _need(schema, table, name)
        if bucket and cols[name]["kind"] == "date":
            select.append(f"DATE_TRUNC('{bucket.upper()}', {c}) AS \"{name}\"")
            date_dims.append(name)
        else:
            select.append(f'{c} AS "{name}"')
    dims = len(select)

    aliases = []
    for m in spec["measures"]:
        if m["agg"] not in AGGS:
            raise ValueError("Bad aggregation.")
        inner = "*" if m["column"] is None else _need(schema, table, m["column"])
        if inner == "*" and m["agg"] != "Count":
            raise ValueError("Only Count may use all rows.")
        a = alias_of(m)
        aliases.append(a)
        select.append(f'{_FUNCS[m["agg"]]}({inner}) AS "{a}"')

    where, params = [], {}
    clause, p = _scope(user, table, schema)
    if clause:
        where.append(clause)
        params.update(p)
    for i, f in enumerate(spec.get("filters") or []):
        col = _need(schema, table, f["column"])
        names = []
        for j, v in enumerate(f["values"]):
            key = f"f{i}_{j}"
            params[key] = v
            names.append(f"%({key})s")
        where.append(f"{col} IN ({', '.join(names)})")
    for i, f in enumerate(spec.get("date_filters") or []):
        parts, p = _date_clauses(_need(schema, table, f["column"]), f, i)
        where.extend(parts)
        params.update(p)

    sql = f"SELECT {', '.join(select)} FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    if dims:
        sql += " GROUP BY " + ", ".join(str(i) for i in range(1, dims + 1))
        if date_dims:
            sql += " ORDER BY " + ", ".join(str(i) for i in range(1, dims + 1))
        else:
            sql += f" ORDER BY {dims + 1} DESC"
    sql += f" LIMIT {int(MAX_GROUPS)}"
    return sql, params, {"x": spec.get("x"), "color": spec.get("color"), "measures": aliases,
                         "dims": dim_names, "date_dims": date_dims}


def run_spec(user: dict, spec: dict, schema: dict):
    sql, params, info = compile_spec(user, spec, schema)
    return run_query(sql, params), info


def distinct_values(user: dict, table: str, column: str, schema: dict) -> list:
    """Real values of one text column, limited to the rows this user may see (max 51)."""
    col = _need(schema, table, column)
    clause, params = _scope(user, table, schema)
    sql = f"SELECT DISTINCT {col} AS V FROM {table}"
    if clause:
        sql += " WHERE " + clause
    sql += " LIMIT 51"
    df = run_query(sql, params)
    return [v for v in df["V"].tolist() if v is not None]


def distinct_years(user: dict, table: str, column: str, schema: dict, month: int | None = None) -> list:
    """Years present in one date column, for the rows this user may see. Used locally only."""
    col = _need(schema, table, column)
    clause, params = _scope(user, table, schema)
    where = [clause] if clause else []
    if month:
        where.append(f"MONTH({col}) = %(m)s")
        params = {**params, "m": int(month)}
    sql = f"SELECT DISTINCT YEAR({col}) AS Y FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT 51"
    df = run_query(sql, params)
    return sorted(int(v) for v in df["Y"].tolist() if v is not None)
