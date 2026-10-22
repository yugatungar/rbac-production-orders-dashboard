"""Builds the list of tables and columns the signed-in role may use.

This is the ONLY information the AI will ever receive about the database: names, kinds
and approved descriptions of columns this role can already view. No rows, no values.
"""
import datetime as dt
import decimal
import re

import pandas as pd
import streamlit as st

from src.datasets import datasets_for_role, list_datasets, viewable_columns
from src.db import run_query

SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_NUMBER_TYPES = ("NUMBER", "DECIMAL", "NUMERIC", "INT", "BIGINT", "SMALLINT", "TINYINT",
                 "BYTEINT", "FLOAT", "DOUBLE", "REAL")


def _kind_from_values(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "text"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    vals = s.dropna()
    if vals.empty:
        return "text"
    if all(isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool) for v in vals):
        return "number"
    if all(isinstance(v, (dt.date, dt.datetime)) for v in vals):
        return "date"
    return "text"


@st.cache_data(ttl=60, show_spinner=False)
def column_kinds(table: str) -> dict:
    """Column name -> 'number' | 'date' | 'text', from Snowflake's own type information."""
    try:
        d = run_query(f"DESCRIBE TABLE {table}")
        out = {}
        for name, typ in zip(d["name"], d["type"]):
            t = str(typ).upper()
            if t.startswith(_NUMBER_TYPES):
                out[name] = "number"
            elif t.startswith(("DATE", "TIMESTAMP")):
                out[name] = "date"
            else:
                out[name] = "text"
        return out
    except Exception:
        sample = run_query(f"SELECT * FROM {table} LIMIT 200")
        return {c: _kind_from_values(sample[c]) for c in sample.columns}


def approved_descriptions(table: str) -> dict:
    """Only descriptions marked APPROVED reach the AI."""
    try:
        df = run_query(
            "SELECT COLUMN_NAME, DESCRIPTION FROM COLUMN_DESCRIPTIONS "
            "WHERE TABLE_NAME = %(t)s AND COALESCE(STATUS, 'APPROVED') = 'APPROVED'",
            {"t": table},
        )
    except Exception:
        return {}
    return {r.COLUMN_NAME: (r.DESCRIPTION or "").strip()[:300] for r in df.itertuples(index=False)}


def build_schema(user: dict) -> dict:
    """{table: {'title', 'owner_column', 'columns': {col: {'kind', 'description'}}}} for this role."""
    allowed = set(datasets_for_role(user["role"]))
    ds = list_datasets()
    schema = {}
    for row in ds.itertuples(index=False):
        table = row.TABLE_NAME
        if table not in allowed:
            continue
        cols = [c for c in viewable_columns(user["role"], table) if SAFE_NAME.match(c)]
        if not cols:
            continue
        kinds = column_kinds(table)
        descs = approved_descriptions(table)
        schema[table] = {
            "title": row.DISPLAY_NAME or table,
            "owner_column": row.OWNER_COLUMN,
            "columns": {c: {"kind": kinds.get(c, "text"), "description": descs.get(c, "")} for c in cols},
        }
    return schema


def schema_for_prompt(schema: dict) -> str:
    """The exact text the AI would be given about the database. Owner columns are not mentioned."""
    lines = []
    for table, t in schema.items():
        lines.append(f"TABLE {table} ({t['title']})")
        for c, info in t["columns"].items():
            desc = f": {info['description']}" if info["description"] else ""
            lines.append(f"  - {c} ({info['kind']}){desc}")
        lines.append("")
    return "\n".join(lines).strip()
