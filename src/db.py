import pandas as pd
import snowflake.connector
import streamlit as st

from src.config import load_settings


@st.cache_resource(show_spinner="Connecting to Snowflake...")
def _connect():
    s = load_settings()
    missing = s.missing()
    if missing:
        raise RuntimeError(f"Missing values in .env: {', '.join(missing)}")

    params = dict(
        account=s.account,
        user=s.user,
        warehouse=s.warehouse,
        authenticator=s.authenticator,
        client_session_keep_alive=True,
    )
    if s.authenticator.lower() == "snowflake":
        params["password"] = s.password
    for key in ("role", "database", "schema"):
        value = getattr(s, key)
        if value:
            params[key] = value
    return snowflake.connector.connect(**params)


def get_connection():
    conn = _connect()
    if conn.is_closed():
        _connect.clear()
        conn = _connect()
    return conn


def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    cur = get_connection().cursor()
    try:
        cur.execute(sql, params or {})
        columns = [c[0] for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)
    finally:
        cur.close()