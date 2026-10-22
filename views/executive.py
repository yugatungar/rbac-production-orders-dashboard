import pandas as pd
import streamlit as st

from src.auth import require_login
from src.repository import fetch_orders

user = require_login()

st.header("Executive overview")

df = fetch_orders(user)
if df.empty:
    st.warning("No data available for your role.")
    st.stop()

cols = set(df.columns)

# ---------- Key insights ----------
from src.insights import generate_insights
from src.metrics import metrics_for

try:
    _metrics = metrics_for(user["role"], "PRODUCTION_ORDERS")
except Exception:
    _metrics = []
_found = generate_insights(df, _metrics)
if _found:
    st.subheader("Key insights")
    for _t in _found:
        st.markdown(f"- {_t}")
    st.divider()
# ---------- KPI tiles ----------
k1, k2, k3, k4 = st.columns(4)
k1.metric("Total orders", f"{len(df):,}")

if {"QTY_PLANNED", "QTY_BUILT"} <= cols:
    planned = df["QTY_PLANNED"].sum()
    built = df["QTY_BUILT"].sum()
    k2.metric("Built vs planned", f"{built / planned:.0%}" if planned else "n/a")
    k3.metric("Units built", f"{int(built):,}")

if {"DEFECT_COUNT", "QTY_BUILT"} <= cols and df["QTY_BUILT"].sum() > 0:
    rate = df["DEFECT_COUNT"].sum() / df["QTY_BUILT"].sum()
    k4.metric("Defect rate", f"{rate:.1%}")

st.divider()

# ---------- Charts ----------
left, right = st.columns(2)

with left:
    if {"PLANT", "QTY_PLANNED", "QTY_BUILT"} <= cols:
        st.subheader("Planned vs built by plant")
        by_plant = df.groupby("PLANT")[["QTY_PLANNED", "QTY_BUILT"]].sum()
        st.bar_chart(by_plant)

with right:
    if "STATUS" in cols:
        st.subheader("Orders by status")
        st.bar_chart(df["STATUS"].value_counts())

left2, right2 = st.columns(2)

with left2:
    if {"ENGINE_MODEL", "DEFECT_COUNT"} <= cols:
        st.subheader("Defects by engine model")
        st.bar_chart(df.groupby("ENGINE_MODEL")["DEFECT_COUNT"].sum().sort_values(ascending=False))

with right2:
    if "TARGET_DATE" in cols:
        st.subheader("Orders due per month")
        dates = pd.to_datetime(df["TARGET_DATE"])
        monthly = dates.dt.to_period("M").dt.to_timestamp().value_counts().sort_index()
        st.line_chart(monthly)

