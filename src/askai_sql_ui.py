"""Ask AI box for SQL mode: headline first, chart if it helps, everything else under More context."""
import time

import streamlit as st

from src.agent import presenter
from src.agent.llm import LLMError, get_provider
from src.agent.schema import build_schema
from src.agent.sql_agents import answer_sql

Q, RUN, RES, SCH = "sql_q", "sql_run", "sql_res", "sql_schema"


def _set(text: str) -> None:
    st.session_state[Q] = text
    st.session_state[RUN] = True


def _schema(user: dict) -> dict:
    key = (user["username"], user["role"])
    c = st.session_state.get(SCH)
    if c and c["key"] == key and time.time() - c["t"] < 300:
        return c["schema"]
    s = build_schema(user)
    st.session_state[SCH] = {"key": key, "t": time.time(), "schema": s}
    return s


def render_sql_box(user: dict) -> None:
    st.subheader("Ask AI")
    st.caption("Ask in plain English. The AI writes a read-only query, which is checked against what your role "
               "may see before it runs. The AI never sees your data.")
    st.text_input("Your question", key=Q, max_chars=400, placeholder="For example: which plant has the lowest defect rate")
    clicked = st.button("Ask AI", key="sql_go")
    if clicked or st.session_state.pop(RUN, False):
        q = st.session_state.get(Q, "")
        try:
            provider = get_provider()
        except LLMError as e:
            st.session_state[RES] = {"status": "error", "message": str(e)}
        else:
            with st.spinner("Thinking..."):
                st.session_state[RES] = answer_sql(user, q, provider, schema=_schema(user))
            st.session_state[RES]["asked"] = q
    res = st.session_state.get(RES)
    if not res:
        return
    status = res["status"]
    if status == "ok":
        df = res["df"]
        dims, meas = presenter.shape(df)
        for n in res.get("notes") or []:
            st.caption(n)
        st.markdown(f"**{presenter.headline(df, dims, meas, res.get('asked', ''))}**")
        chart = presenter.make_chart(df, dims, meas, highlight=presenter.is_ranking(res.get("asked", "")))
        if chart is not None:
            st.altair_chart(chart, use_container_width=True)
        if not meas and len(df):
            st.dataframe(df, hide_index=True)
        with st.expander("More context"):
            if meas and len(df):
                st.dataframe(df, hide_index=True)
            st.code(res["sql"], language="sql")
            st.caption(f"AI calls used: {res.get('attempts', 1)}")
        rc = res.get("receipt")
        if rc:
            with st.expander("Safety receipt"):
                names = ", ".join(rc["columns_used"]) or "none"
                st.markdown("- **Statements:** 1 (read-only SELECT)")
                st.markdown("- **Tables used:** " + (", ".join(rc["tables"]) or "none"))
                st.markdown(f"- **Columns used:** {len(rc['columns_used'])} of {rc['columns_allowed']} allowed for your role ({names})")
                if rc["row_filter"]:
                    st.markdown("- **Row filter:** applied, you only see your own rows")
                else:
                    st.markdown("- **Row filter:** not needed, your role can see all rows")
                if rc["limit_added"]:
                    st.markdown("- **Row cap:** limit of 500 added")
                else:
                    st.markdown("- **Row cap:** query already had a limit within 500")
                st.markdown("- **Value fixes:** " + ("; ".join(rc["fixes"]) if rc["fixes"] else "none needed"))
                rej = rc.get("rejected") or []
                if rej:
                    st.markdown(f"- **Rejected before this passed:** {len(rej)}")
                    for r in rej:
                        st.caption(r)
                else:
                    st.markdown("- **Rejected before this passed:** 0")
                st.caption("The query that ran is the guard's rebuilt version, not the AI's original text. "
                           "Other tables, hidden columns, unknown functions and non-SELECT statements are blocked before running.")
    elif status == "ask":
        st.info(res["question"])
        opts = res.get("options") or []
        if opts:
            cols = st.columns(len(opts))
            for i, o in enumerate(opts):
                cols[i].button(o, key=f"sql_opt_{i}", on_click=_set, args=(o,))
    elif status == "cannot":
        st.warning(res.get("reason") or "I cannot answer that from the data you can see.")
    else:
        st.error(res.get("message") or "Something went wrong.")
        for e in res.get("errors") or []:
            st.caption("Reason: " + str(e))
