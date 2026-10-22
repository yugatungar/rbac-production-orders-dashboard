import streamlit as st

from src.auth import require_login
from src.config import ORDER_COLUMNS
from src.repository import fetch_orders

user = require_login()

st.header("Production orders")

df = fetch_orders(user)
visible = list(df.columns)
hidden = [c for c in ORDER_COLUMNS if c not in visible]

scope_text = "all orders" if user["row_scope"] == "ALL" else "only your own orders"
st.caption(f"Role {user['role']}: showing {scope_text}.")

if df.empty and not visible:
    st.warning("Your role has no column access configured.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Orders shown", f"{len(df):,}")
if {"QTY_PLANNED", "QTY_BUILT"} <= set(visible) and df["QTY_PLANNED"].sum() > 0:
    c2.metric("Built vs planned", f"{df['QTY_BUILT'].sum() / df['QTY_PLANNED'].sum():.0%}")
c3.metric("Columns visible", f"{len(visible)} of {len(ORDER_COLUMNS)}")

st.dataframe(df, hide_index=True)

if hidden:
    st.caption("Hidden for your role: " + ", ".join(hidden))
