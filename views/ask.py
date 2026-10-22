"""Ask your data: plain-English questions, plus the data and context to check answers against."""
import streamlit as st

from src.agent.schema import build_schema, schema_for_prompt
from src.askai_ui import RES_KEY, _set_question, render_ai_box
from src.auth import require_login
from src.config import MAX_ROWS
from src.datasets import datasets_for_role, fetch_table, list_datasets

user = require_login()
HIST = "ai_history"

st.header("Ask your data")
st.caption("Ask in plain English. You get a written answer, a table and, when it helps, a chart. "
           "Only the tables, columns and rows your role may see are used.")

render_ai_box(user)

# remember this session's questions (question text and outcome only, never the data)
res = st.session_state.get(RES_KEY)
hist = st.session_state.setdefault(HIST, [])
if res and res.get("asked") and not res.get("_logged"):
    res["_logged"] = True
    hist.append((res["asked"], res["status"]))

st.divider()
tab_data, tab_can, tab_hist = st.tabs(["Your data", "What you can ask about", "Recent questions"])

with tab_data:
    allowed = datasets_for_role(user["role"])
    ds = list_datasets()
    ds = ds[ds["TABLE_NAME"].isin(allowed)]
    if ds.empty:
        st.info("No tables are assigned to your role.")
    else:
        names = dict(zip(ds["TABLE_NAME"], ds["DISPLAY_NAME"]))
        table = st.selectbox("Table", list(names), format_func=names.get, key="ask_preview_table")
        df = fetch_table(user, table)
        if df.empty:
            st.info("No data available for your role in this table.")
        else:
            st.caption(f"{len(df):,} rows and {len(df.columns)} columns available to you. "
                       "Use this to check the answers above.")
            if len(df) >= MAX_ROWS:
                st.warning(f"Only the first {MAX_ROWS:,} rows are shown here. Answers above use all your rows.")
            st.dataframe(df, hide_index=True)

with tab_can:
    st.caption("This is everything the AI is told about your data: table names, column names and "
               "descriptions. It never sees the rows or the answers.")
    try:
        st.code(schema_for_prompt(build_schema(user)), language=None)
    except Exception as e:
        st.warning(f"Could not load the list: {e}")

with tab_hist:
    if not hist:
        st.caption("Questions you ask in this session will appear here.")
    labels = {"ok": "answered", "ask": "needed a choice", "cannot": "not possible", "error": "failed"}
    for i, (q, status) in enumerate(reversed(hist[-10:])):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"{q}  \n*{labels.get(status, status)}*")
        c2.button("Ask again", key=f"ai_hist_{i}", on_click=_set_question, args=(q,))
