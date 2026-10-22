import pandas as pd
import streamlit as st

from src.datasets import viewable_columns
from src.db import run_query


@st.cache_data(ttl=30, show_spinner=False)
def _load(table_name: str) -> pd.DataFrame:
    return run_query(
        "SELECT METRIC_ID, LABEL, KIND, COL_A, COL_B, VALUE_FORMAT "
        "FROM METRICS WHERE TABLE_NAME = %(t)s ORDER BY LABEL",
        {"t": table_name},
    )


def metrics_for(role: str, table_name: str) -> list[dict]:
    """Metrics whose source columns this role is allowed to view."""
    allowed = set(viewable_columns(role, table_name))
    out = []
    for r in _load(table_name).itertuples(index=False):
        if r.COL_A in allowed and r.COL_B in allowed:
            out.append({
                "id": r.METRIC_ID, "label": r.LABEL, "kind": r.KIND,
                "col_a": r.COL_A, "col_b": r.COL_B, "format": r.VALUE_FORMAT,
            })
    return out
