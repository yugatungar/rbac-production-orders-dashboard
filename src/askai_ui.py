"""Ask AI box for the Charts tab. Calls answer() and draws the result."""
import calendar
import re

import altair as alt
import pandas as pd
import streamlit as st

from src.agent.agent import answer
from src.agent.llm import LLMError, get_provider
from src.answer_text import summarize

Q_KEY = "ai_question"
RUN_KEY = "ai_run"
RES_KEY = "ai_result"


def _set_question(text: str) -> None:
    st.session_state[Q_KEY] = text
    st.session_state[RUN_KEY] = True


def _draw(res: dict) -> None:
    df, spec, info = res["df"].copy(), res["spec"], res["info"]
    if df.empty:
        st.info("No rows matched your question.")
        return
    x, kind, color = spec["x"], spec["chart"], spec.get("color")
    meas = list(info["measures"])
    xcol = x if x in df.columns else df.columns[0]
    if spec.get("bucket"):
        df[xcol] = pd.to_datetime(df[xcol], errors="coerce")
    is_date = pd.api.types.is_datetime64_any_dtype(df[xcol])
    xenc = f"{xcol}:T" if is_date else f"{xcol}:N"
    axis_kw = {}
    if is_date:
        _b = spec.get("bucket")
        _fmt = {"Day": "%d %b %Y", "Year": "%Y"}.get(_b, "%b %Y")
        if kind == "Bar":
            df[xcol] = df[xcol].dt.strftime(_fmt)
            xenc = f"{xcol}:O"
            axis_kw = {"labelAngle": -45}
        else:
            axis_kw = {"format": _fmt}
            _tick = {"Year": "year", "Day": None}.get(_b, "month")
            if _tick:
                axis_kw["tickCount"] = _tick

    if kind == "Pie":
        chart = alt.Chart(df).mark_arc().encode(
            theta=alt.Theta(f"{meas[0]}:Q"), color=alt.Color(f"{xcol}:N"), tooltip=list(df.columns))
    else:
        if len(meas) > 1:
            ids = [c for c in df.columns if c not in meas]
            df = df.melt(id_vars=ids, value_vars=meas, var_name="measure", value_name="value")
            yenc, cenc = "value:Q", "measure:N"
        else:
            yenc = f"{meas[0]}:Q"
            cenc = f"{color}:N" if color and color in df.columns else alt.value("#4c78a8")
        mark = {"Line": "line", "Area": "area"}.get(kind, "bar")
        base = alt.Chart(df)
        _r = locals().get("res")
        _f = _r.get("focus") if isinstance(_r, dict) else None
        _single = mark == "bar" and len(meas) == 1 and not (color and color in df.columns)
        if _single and isinstance(_f, dict) and _f.get("column") == xcol:
            cenc = alt.condition(alt.datum[xcol] == _f.get("value"),
                                 alt.value("#e45756"), alt.value("#b8c2cc"))
        _lab = _single and len(df) <= 15
        chart = getattr(base, f"mark_{mark}")().encode(
            x=alt.X(xenc, sort=None, axis=alt.Axis(**axis_kw)), y=yenc, color=cenc, tooltip=list(df.columns))
        if _lab:
            chart = chart + alt.Chart(df).mark_text(dy=-8).encode(
                x=alt.X(xenc, sort=None), y=yenc,
                text=alt.Text(f"{meas[0]}:Q", format=",.2~f"))
    st.altair_chart(chart, use_container_width=True)


_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
           "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _scope_warning(res: dict):
    """Compare the months the user named with what was really filtered. Local check, no AI."""
    import pandas as pd
    spec = res["spec"]
    asked = (res.get("asked") or res.get("question") or "").lower()
    found = re.findall(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", asked)
    mentioned = {_MONTHS[m[:3]] for m in found}
    applied = set()
    for f in spec.get("date_filters") or []:
        if f.get("from") or f.get("to"):
            return None
        if f.get("month"):
            applied.add(f["month"])
        applied.update(int(v) for v in (f.get("months") or []))
    missing = sorted(mentioned - applied)
    if not missing:
        return None
    names = ", ".join(calendar.month_abbr[m] for m in missing)
    span, x, df = "", spec.get("x"), res["df"]
    if x in df.columns and len(df):
        d = pd.to_datetime(df[x], errors="coerce").dropna()
        if len(d):
            span = f" The result covers {d.min():%b %Y} to {d.max():%b %Y}."
    return (f"Your question mentions {names}, but this result is NOT limited to "
            f"{'that month' if len(missing) == 1 else 'those months'}.{span} "
            "Either the data has no rows for them, or the request could not express them. "
            "Do not read the chart below as the answer.")


def _coverage(res: dict) -> list:
    """Generic check: every value the request filtered on must appear in the result."""
    df, spec = res["df"], res["spec"]
    out = []
    if df.empty:
        return out
    for f in spec.get("filters") or []:
        c = f["column"]
        if c in df.columns:
            have = {str(v).strip().upper() for v in df[c].dropna()}
            miss = [v for v in f["values"] if str(v).strip().upper() not in have]
            if miss:
                out.append(f"No rows for {', '.join(map(str, miss))} in {c.replace('_', ' ').lower()}.")
    x = spec.get("x")
    for f in spec.get("date_filters") or []:
        ms = list(f.get("months") or ([f["month"]] if f.get("month") else []))
        if ms and x == f["column"] and x in df.columns and spec.get("bucket") in (None, "Month", "Day"):
            have = set(pd.to_datetime(df[x], errors="coerce").dt.month.dropna().astype(int))
            miss = [m for m in ms if m not in have]
            if miss:
                out.append("No data for " + ", ".join(calendar.month_name[m] for m in miss) + ".")
    return out


def _headline(lines: list):
    """First summary line that is an answer, not just the scope sentence."""
    for ln in lines:
        if not ln.startswith("Showing results for"):
            return ln
    return None


def _wants_chart(res: dict) -> bool:
    """A chart only when it helps: not for Table requests and not for a single number."""
    return res["spec"].get("chart") != "Table" and len(res["df"]) >= 2


def render_ai_box(user: dict) -> None:
    import os
    if os.getenv("AGENT_MODE", "json").lower() == "sql":
        from src.askai_sql_ui import render_sql_box
        return render_sql_box(user)
    st.subheader("Ask AI")
    st.caption("Describe the chart you want. The AI only sees your question and the column names "
               "you are allowed to see, never your data.")
    st.text_input("Your question", key=Q_KEY, max_chars=400,
                  placeholder="For example: planned vs built by plant")
    clicked = st.button("Ask AI", key="ai_go")
    if clicked or st.session_state.pop(RUN_KEY, False):
        q = st.session_state.get(Q_KEY, "")
        try:
            provider = get_provider()
        except LLMError as e:
            st.session_state[RES_KEY] = {"status": "error", "message": str(e)}
        else:
            with st.spinner("Thinking..."):
                st.session_state[RES_KEY] = answer(user, q, provider)
            st.session_state[RES_KEY]["asked"] = q

    res = st.session_state.get(RES_KEY)
    if not res:
        return
    status = res["status"]
    if status == "ok":
        st.success(res.get("reasoning") or "Here is your chart.")
        _w = _scope_warning(res)
        if _w:
            st.warning(_w)
        if res.get("clarify"):
            _names = ", ".join(f"'{c['asked']}' ({c['column'].replace('_', ' ').lower()})" for c in res["clarify"])
            st.warning(f"I could not match {_names} to your data, so the result is NOT filtered by it. "
                       "Pick one of the suggestions below to fix that.")
        for _g in _coverage(res):
            st.warning(_g)
        _lines = summarize(res)
        _head = _headline(_lines)
        if _head:
            st.markdown(f"**{_head}**")
        _scope = next((ln for ln in _lines if ln.startswith("Showing results for")), None)
        if _scope:
            st.caption(_scope)
        if _wants_chart(res):
            _draw(res)
        with st.expander("More context"):
            for _line in _lines:
                if _line != _head and _line != _scope:
                    st.markdown(f"- {_line}")
            st.write("Request:", res["spec"])
            st.code(res["sql"], language="sql")
            st.dataframe(res["df"], hide_index=True)
        for c in res.get("clarify") or []:
            st.info(f"There is no {c['column']} called '{c['asked']}'. Did you mean:")
            cols = st.columns(len(c["choices"]))
            for i, ch in enumerate(c["choices"]):
                new_q = re.sub(re.escape(c["asked"]), ch, res.get("asked", ""), flags=re.I)
                cols[i].button(ch, key=f"ai_fix_{c['column']}_{i}", on_click=_set_question, args=(new_q,))
    elif status == "ask":
        st.info(res["question"])
        opts = res.get("options") or []
        if opts:
            cols = st.columns(len(opts))
            for i, o in enumerate(opts):
                new_q = f"{res.get('asked', '')} ({o})"
                cols[i].button(o, key=f"ai_opt_{i}", on_click=_set_question, args=(new_q,))
    elif status == "cannot":
        st.warning(res.get("reason") or "I cannot answer that from the data you can see.")
    else:
        st.error(res.get("message") or "Something went wrong.")

