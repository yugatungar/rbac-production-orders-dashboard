import streamlit as st

from src.config import ORDER_COLUMNS
from src.db import run_query


@st.cache_data(ttl=30, show_spinner=False)
def _load_rules(role: str):
    return run_query(
        "SELECT COLUMN_NAME, CAN_VIEW, CAN_EDIT FROM ROLE_COLUMN_ACCESS WHERE ROLE_NAME = %(r)s AND TABLE_NAME = 'PRODUCTION_ORDERS'",
        {"r": role},
    )


def viewable_columns(role: str) -> list[str]:
    rules = _load_rules(role)
    allowed = set(rules.loc[rules["CAN_VIEW"], "COLUMN_NAME"])
    return [c for c in ORDER_COLUMNS if c in allowed]


def editable_columns(role: str) -> list[str]:
    rules = _load_rules(role)
    allowed = set(rules.loc[rules["CAN_EDIT"], "COLUMN_NAME"])
    return [c for c in ORDER_COLUMNS if c in allowed]
