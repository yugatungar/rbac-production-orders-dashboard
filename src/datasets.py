import pandas as pd
import streamlit as st

from src.config import MAX_ROWS
from src.db import run_query


@st.cache_data(ttl=30, show_spinner=False)
def list_datasets() -> pd.DataFrame:
    return run_query("SELECT TABLE_NAME, DISPLAY_NAME, OWNER_COLUMN FROM DATASETS ORDER BY DISPLAY_NAME")


def get_dataset(table_name: str):
    ds = list_datasets()
    row = ds[ds["TABLE_NAME"] == table_name]
    if row.empty:
        raise ValueError("Unknown dataset")
    return row.iloc[0]


@st.cache_data(ttl=60, show_spinner=False)
def _actual_columns(table_name: str) -> list[str]:
    get_dataset(table_name)  # only registered tables are ever queried
    return list(run_query(f"SELECT * FROM {table_name} LIMIT 0").columns)


@st.cache_data(ttl=30, show_spinner=False)
def _rules(role: str, table_name: str) -> pd.DataFrame:
    return run_query(
        "SELECT COLUMN_NAME, CAN_VIEW, CAN_EDIT FROM ROLE_COLUMN_ACCESS "
        "WHERE ROLE_NAME = %(r)s AND TABLE_NAME = %(t)s",
        {"r": role, "t": table_name},
    )

@st.cache_data(ttl=30, show_spinner=False)
def datasets_for_role(role: str) -> list[str]:
    df = run_query(
        "SELECT TABLE_NAME FROM ROLE_DATASET_ACCESS WHERE ROLE_NAME = %(r)s",
        {"r": role},
    )
    return list(df["TABLE_NAME"])

def viewable_columns(role: str, table_name: str) -> list[str]:
    if table_name not in datasets_for_role(role):
        return []
    allowed = set(_rules(role, table_name).query("CAN_VIEW")["COLUMN_NAME"])
    return [c for c in _actual_columns(table_name) if c in allowed]


def fetch_table(user: dict, table_name: str, columns: list[str] | None = None) -> pd.DataFrame:
    ds = get_dataset(table_name)
    allowed = viewable_columns(user["role"], table_name)
    cols = allowed if columns is None else [c for c in columns if c in allowed]
    if not cols:
        return pd.DataFrame()

    select_list = ", ".join(f'"{c}"' for c in cols)
    sql = f"SELECT {select_list} FROM {table_name}"
    params = {}

    if user["row_scope"] == "OWN":
        owner_col = ds["OWNER_COLUMN"]
        if not owner_col or owner_col not in _actual_columns(table_name):
            return pd.DataFrame()  # no way to scope rows, so show nothing
        sql += f' WHERE "{owner_col}" = %(owner)s'
        params["owner"] = user["username"]

    sql += f" LIMIT {int(MAX_ROWS)}"
    return run_query(sql, params)
