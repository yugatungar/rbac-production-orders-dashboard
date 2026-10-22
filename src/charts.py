"""Plotly figure builders and KPI calculations (pure functions on a DataFrame)."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

RED = "#D6001C"
DARK = "#1F2933"
GREY = "#9AA5B1"
STATUS_COLORS = {
    "PLANNED": "#9AA5B1",
    "IN_PROGRESS": "#2F80ED",
    "ON_HOLD": "#F2994A",
    "COMPLETED": "#27AE60",
}
_LAYOUT = dict(margin=dict(l=10, r=10, t=50, b=10), legend_title_text="", height=360)


def _empty(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        title=title,
        annotations=[dict(text="No data for current filters", showarrow=False, font=dict(size=14))],
        xaxis=dict(visible=False), yaxis=dict(visible=False), **_LAYOUT,
    )
    return fig


def has(df: pd.DataFrame, *cols: str) -> bool:
    return all(c in df.columns for c in cols)


def overdue_mask(df: pd.DataFrame) -> pd.Series:
    if not has(df, "TARGET_DATE", "STATUS"):
        return pd.Series(False, index=df.index)
    today = pd.Timestamp.today().normalize()
    return (df["TARGET_DATE"] < today) & (df["STATUS"] != "COMPLETED")


def compute_kpis(df: pd.DataFrame) -> dict:
    """Each KPI is None when the columns it needs are hidden from this role."""
    k: dict = {"orders": len(df), "planned": None, "built": None, "completion": None,
               "defect_rate": None, "overdue": None}
    if has(df, "QTY_PLANNED", "QTY_BUILT"):
        planned, built = int(df["QTY_PLANNED"].sum()), int(df["QTY_BUILT"].sum())
        k.update(planned=planned, built=built, completion=(built / planned * 100) if planned else 0.0)
        if has(df, "DEFECT_COUNT"):
            k["defect_rate"] = (int(df["DEFECT_COUNT"].sum()) / built * 1000) if built else 0.0
    if has(df, "TARGET_DATE", "STATUS"):
        k["overdue"] = int(overdue_mask(df).sum()) if len(df) else 0
    return k


def plan_vs_built_by_plant(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty("Plan vs built by plant")
    g = df.groupby("PLANT", as_index=False)[["QTY_PLANNED", "QTY_BUILT"]].sum()
    fig = go.Figure()
    fig.add_bar(x=g["PLANT"], y=g["QTY_PLANNED"], name="Planned", marker_color=GREY)
    fig.add_bar(x=g["PLANT"], y=g["QTY_BUILT"], name="Built", marker_color=RED)
    fig.update_layout(title="Plan vs built by plant", barmode="group", **_LAYOUT)
    return fig


def status_donut(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty("Orders by status")
    g = df["STATUS"].value_counts().reset_index()
    g.columns = ["STATUS", "COUNT"]
    fig = px.pie(g, names="STATUS", values="COUNT", hole=0.55,
                 color="STATUS", color_discrete_map=STATUS_COLORS, title="Orders by status")
    fig.update_traces(textinfo="label+percent", sort=False)
    fig.update_layout(showlegend=False, **{k: v for k, v in _LAYOUT.items() if k != "legend_title_text"})
    return fig


def monthly_trend(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty("Monthly output trend")
    m = (df.assign(MONTH=df["TARGET_DATE"].dt.to_period("M").dt.to_timestamp())
           .groupby("MONTH", as_index=False)[["QTY_PLANNED", "QTY_BUILT"]].sum())
    m["COMPLETION_PCT"] = (m["QTY_BUILT"] / m["QTY_PLANNED"].where(m["QTY_PLANNED"] > 0) * 100).round(1)
    fig = go.Figure()
    fig.add_bar(x=m["MONTH"], y=m["QTY_PLANNED"], name="Planned", marker_color="#E4E7EB")
    fig.add_bar(x=m["MONTH"], y=m["QTY_BUILT"], name="Built", marker_color=RED)
    fig.add_scatter(x=m["MONTH"], y=m["COMPLETION_PCT"], name="Completion %", yaxis="y2",
                    mode="lines+markers", line=dict(color=DARK, width=2))
    fig.update_layout(
        title="Monthly output and completion %", barmode="overlay",
        yaxis2=dict(overlaying="y", side="right", range=[0, 110], showgrid=False, title="%"),
        **_LAYOUT,
    )
    return fig


def defect_heatmap(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty("Defects per 1,000 units built")
    g = df.groupby(["ENGINE_MODEL", "PLANT"])[["DEFECT_COUNT", "QTY_BUILT"]].sum().reset_index()
    g["RATE"] = (g["DEFECT_COUNT"] / g["QTY_BUILT"].where(g["QTY_BUILT"] > 0) * 1000).round(1)
    pivot = g.pivot(index="ENGINE_MODEL", columns="PLANT", values="RATE")
    fig = px.imshow(pivot, text_auto=True, aspect="auto",
                    color_continuous_scale=["#FFFFFF", "#F5B7BE", RED],
                    title="Defects per 1,000 units built")
    fig.update_layout(coloraxis_showscale=False, **{k: v for k, v in _LAYOUT.items() if k != "legend_title_text"})
    return fig


def completion_by_model(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return _empty("Completion by engine model")
    g = df.groupby("ENGINE_MODEL", as_index=False)[["QTY_PLANNED", "QTY_BUILT"]].sum()
    g["PCT"] = (g["QTY_BUILT"] / g["QTY_PLANNED"].where(g["QTY_PLANNED"] > 0) * 100).round(1)
    g = g.sort_values("PCT")
    fig = px.bar(g, x="PCT", y="ENGINE_MODEL", orientation="h", text="PCT",
                 title="Completion % by engine model", color_discrete_sequence=[RED])
    fig.update_xaxes(range=[0, 105], title="")
    fig.update_yaxes(title="")
    fig.update_layout(**{k: v for k, v in _LAYOUT.items() if k != "legend_title_text"})
    return fig


def backlog_bubble(df: pd.DataFrame) -> go.Figure:
    """Each bubble is an open order: size = units remaining, x = days to target date."""
    open_df = df[df["STATUS"] != "COMPLETED"].copy()
    if open_df.empty:
        return _empty("Open order risk map")
    open_df["DAYS_TO_TARGET"] = (open_df["TARGET_DATE"] - pd.Timestamp.today().normalize()).dt.days
    open_df["REMAINING"] = (open_df["QTY_PLANNED"] - open_df["QTY_BUILT"]).clip(lower=1)
    fig = px.scatter(
        open_df, x="DAYS_TO_TARGET", y="DEFECT_COUNT", size="REMAINING", color="STATUS",
        hover_name="ORDER_ID", hover_data=["PLANT", "ENGINE_MODEL", "REMAINING"],
        color_discrete_map=STATUS_COLORS, size_max=28,
        title="Open order risk map (left of 0 = overdue)",
    )
    fig.add_vline(x=0, line_dash="dash", line_color=RED)
    fig.update_layout(**_LAYOUT)
    return fig
