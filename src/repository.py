import pandas as pd

from src.access import viewable_columns
from src.config import MAX_ROWS, ORDERS_TABLE
from src.db import run_query


def fetch_orders(user: dict) -> pd.DataFrame:
    columns = viewable_columns(user["role"])
    if not columns:
        return pd.DataFrame()

    select_list = ", ".join(f'"{c}"' for c in columns)
    sql = f"SELECT {select_list} FROM {ORDERS_TABLE}"
    params = {}

    if user["row_scope"] == "OWN":
        sql += ' WHERE "OWNER" = %(owner)s'
        params["owner"] = user["username"]

    sql += f" ORDER BY 1 LIMIT {int(MAX_ROWS)}"
    return run_query(sql, params)
