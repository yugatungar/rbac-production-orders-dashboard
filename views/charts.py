import streamlit as st

from src.askchart import apply_filters, example_questions, parse_question
from src.auth import require_login
from src.chartkit import AGGS, CHART_TYPES, COUNT_ROWS, build_chart, column_kinds
from src.chartnotes import describe_chart, explain_chart
from src.config import MAX_ROWS
from src.datasets import datasets_for_role, fetch_table, list_datasets
from src.insights import generate_insights
from src.metrics import metrics_for

user = require_login()

st.header("Chart builder")
st.caption("You can only chart the tables, columns and rows your role is allowed to see.")

allowed = datasets_for_role(user["role"])
ds = list_datasets()
ds = ds[ds["TABLE_NAME"].isin(allowed)]
if ds.empty:
    st.warning("No tables are assigned to your role.")
    st.stop()

names = dict(zip(ds["TABLE_NAME"], ds["DISPLAY_NAME"]))
table = st.selectbox("Table", list(names), format_func=names.get)

df = fetch_table(user, table)
if df.empty:
    st.info("No data available for your role in this table.")
    st.stop()

try:
    metrics = metrics_for(user["role"], table)
except Exception:
    metrics = []
    st.caption("Metrics are not set up yet for this table.")
metric_by_name = {f"Metric: {m['label']}": m for m in metrics}

kinds = column_kinds(df)
numeric = [c for c, k in kinds.items() if k == "number"]
texty = [c for c, k in kinds.items() if k == "text"]
st.caption(f"{len(df):,} rows and {len(df.columns)} columns available to you.")
if len(df) >= MAX_ROWS:
    st.warning(f"Only the first {MAX_ROWS:,} rows were loaded, so totals may be incomplete.")


# ---------- Ask in plain English ----------
ask_key = f"ask_{table}"
done_key = f"ask_done_{table}"
msg_key = f"ask_msg_{table}"
filters_key = f"filters_{table}"


def _use_example(key, text):
    st.session_state[key] = text


def _clear_filters(key):
    st.session_state[key] = {}


examples = example_questions(df, metrics)
question = st.text_input(
    "Ask for a chart in plain English",
    key=ask_key,
    placeholder=f"For example: {examples[0]}" if examples else "For example: total sales by region",
)
if examples:
    ex_cols = st.columns(len(examples))
    for i, ex in enumerate(examples):
        ex_cols[i].button(ex, key=f"ex_{table}_{i}", on_click=_use_example, args=(ask_key, ex))

if question.strip() and question != st.session_state.get(done_key):
    st.session_state[done_key] = question
    res = parse_question(question, df, metrics)
    if res["ok"]:
        s = res["spec"]
        st.session_state[f"type_{table}"] = s["chart_type"]
        st.session_state[f"x_{table}"] = s["x"]
        st.session_state[f"y_{table}"] = f"Metric: {s['metric']['label']}" if s["metric"] else s["y"]
        if s["agg"]:
            st.session_state[f"agg_{table}"] = s["agg"]
        st.session_state[f"color_{table}"] = s["color"] if s["color"] else "(none)"
        if s["bucket"]:
            st.session_state[f"bucket_{table}"] = s["bucket"]
        st.session_state[f"extra_{table}"] = list(s["extra"])
        st.session_state[filters_key] = res["filters"]
        st.session_state[msg_key] = ("ok", res["summary"], res["notes"])
    else:
        st.session_state[msg_key] = ("error", res["message"], [])

msg = st.session_state.get(msg_key)
if msg:
    if msg[0] == "ok":
        st.success(f"From your question: {msg[1]}. You can fine-tune it with the controls below.")
        for n in msg[2]:
            st.caption(n)
    else:
        st.warning(msg[1])

fdict = st.session_state.get(filters_key, {})
dfc = apply_filters(df, fdict)
if fdict:
    st.info("Filter from your question: " + "; ".join(
        f"{c.replace('_', ' ').lower()} = {', '.join(str(v) for v in vals)}" for c, vals in fdict.items()))
    st.button("Clear filter", key=f"clearf_{table}", on_click=_clear_filters, args=(filters_key,))
if dfc.empty:
    st.warning("No rows match that filter.")
    st.stop()

st.divider()

# ---------- Controls ----------
c1, c2, c3 = st.columns(3)
chart_type = c1.selectbox("Chart type", CHART_TYPES, key=f"type_{table}")
x = c2.selectbox("X axis", list(df.columns), key=f"x_{table}")
y_choice = c3.selectbox("Y axis", [COUNT_ROWS] + numeric + list(metric_by_name), key=f"y_{table}")
metric = metric_by_name.get(y_choice)
y = metric["label"] if metric else y_choice
plain_y = metric is None and y != COUNT_ROWS

c4, c5, c6 = st.columns(3)
agg = None
if chart_type != "Scatter" and plain_y:
    agg = c4.selectbox("Aggregation", list(AGGS), key=f"agg_{table}")
color = None
if chart_type != "Pie":
    pick = c5.selectbox("Split by (optional)", ["(none)"] + texty, key=f"color_{table}")
    color = None if pick == "(none)" else pick
bucket = None
if kinds[x] == "date" and chart_type != "Scatter":
    bucket = c6.selectbox("Group dates by", ["Month", "Day", "Year"], key=f"bucket_{table}")

if chart_type in ("Line", "Area") and kinds[x] != "date":
    st.caption("Tip: line and area charts work best with a date or ordered X axis. Use Bar to compare categories.")

extra = []
if chart_type in ("Bar", "Line", "Area") and plain_y:
    extra = st.multiselect(
        "Compare with other measures (optional)",
        [c for c in numeric if c != y],
        key=f"extra_{table}",
    )

spec = {"chart_type": chart_type, "x": x, "y": y, "agg": agg, "color": color,
        "bucket": bucket, "extra": extra, "metric": metric}

try:
    st.altair_chart(build_chart(dfc, spec))
    _note = describe_chart(dfc, spec)
    if _note:
        st.caption(_note)
    _ex = explain_chart(dfc, spec, user["row_scope"])
    if _ex["read"]:
        with st.expander("Explain this chart in simple words"):
            st.markdown("**How to read it**")
            st.write(_ex["read"])
            if _ex["takeaways"]:
                st.markdown("**What it tells you**")
                for _t in _ex["takeaways"]:
                    st.markdown(f"- {_t}")
            if _ex["cautions"]:
                st.markdown("**Keep in mind**")
                for _c in _ex["cautions"]:
                    st.markdown(f"- {_c}")
except Exception as e:
    st.error(f"Could not draw this chart: {e}")

with st.expander("Insights for this table", expanded=True):
    _found = generate_insights(df, metrics)
    if _found:
        for _t in _found:
            st.markdown(f"- {_t}")
    else:
        st.caption("No notable patterns in the data you can see.")

with st.expander("Data you are charting"):
    st.dataframe(dfc, hide_index=True)

