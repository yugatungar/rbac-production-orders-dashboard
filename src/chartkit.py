import datetime as dt

import altair as alt
import pandas as pd

CHART_TYPES = ["Bar", "Line", "Area", "Scatter", "Pie"]
AGGS = {"Sum": "sum", "Average": "mean", "Count": "count", "Min": "min", "Max": "max"}
COUNT_ROWS = "(count of rows)"
ROW_COUNT = "Row count"
MAX_CATEGORIES = 50
_VEGA = {"date": "temporal", "number": "quantitative", "text": "nominal"}


def column_kinds(df: pd.DataFrame) -> dict:
    kinds = {}
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_bool_dtype(s):
            kinds[c] = "text"
        elif pd.api.types.is_numeric_dtype(s):
            kinds[c] = "number"
        elif pd.api.types.is_datetime64_any_dtype(s):
            kinds[c] = "date"
        else:
            first = s.dropna().iloc[0] if s.notna().any() else None
            kinds[c] = "date" if isinstance(first, (dt.date, dt.datetime)) else "text"
    return kinds


def _yaxis(out, ycol, fmt=None):
    axis = alt.Axis(format=".0%") if fmt == "PERCENT" else alt.Axis()
    lo, hi = float(out[ycol].min()), float(out[ycol].max())
    if lo == hi:  # flat data: give the axis a real range
        lo_d, hi_d = min(0.0, lo), max(0.0, hi)
        if lo_d == hi_d:
            hi_d = 1.0
        return alt.Y(ycol, type="quantitative", axis=axis, scale=alt.Scale(domain=[lo_d, hi_d]))
    return alt.Y(ycol, type="quantitative", axis=axis)


def _metric_table(d, keys, metric):
    a, b, label = metric["col_a"], metric["col_b"], metric["label"]
    g = d.groupby(keys, dropna=False)[[a, b]].sum().reset_index()
    if metric["kind"] == "RATIO":
        g[label] = g[a] / g[b].where(g[b] != 0)  # no divide-by-zero
    else:
        g[label] = g[a] - g[b]
    return g[keys + [label]], label


def build_chart(df: pd.DataFrame, spec: dict):
    kind, x, y = spec["chart_type"], spec["x"], spec["y"]
    agg, color, bucket = spec.get("agg"), spec.get("color"), spec.get("bucket")
    metric = spec.get("metric")
    if color == x:
        color = None

    d = df.copy()
    if column_kinds(d[[x]])[x] == "date":
        d[x] = pd.to_datetime(d[x])
        if bucket == "Day":
            d[x] = d[x].dt.normalize()
        elif bucket == "Month":
            d[x] = d[x].dt.to_period("M").dt.to_timestamp()
        elif bucket == "Year":
            d[x] = d[x].dt.to_period("Y").dt.to_timestamp()

    # Several plain measures side by side (e.g. planned vs built)
    extra = [c for c in (spec.get("extra") or []) if c != y]
    if extra and not metric and y != COUNT_ROWS and kind in ("Bar", "Line", "Area"):
        g = d.groupby(x, dropna=False)[[y] + extra].agg(AGGS[agg]).reset_index()
        xk = column_kinds(g[[x]])[x]
        out = g.melt(id_vars=x, var_name="Measure", value_name="Value")
        base = alt.Chart(out)
        xenc = alt.X(x, type=_VEGA[xk])
        yenc = alt.Y("Value", type="quantitative")
        cenc = alt.Color("Measure", type="nominal")
        if kind == "Bar":
            return base.mark_bar().encode(
                x=xenc, y=yenc, color=cenc, xOffset=alt.XOffset("Measure:N")
            ).properties(height=350)
        mark = base.mark_line(point=True) if kind == "Line" else base.mark_area(opacity=0.6)
        return mark.encode(x=xenc, y=yenc, color=cenc).properties(height=350)

    if kind == "Scatter":
        if metric or y == COUNT_ROWS:
            raise ValueError("A scatter chart needs a numeric Y column.")
        kinds = column_kinds(d)
        enc = {"x": alt.X(x, type=_VEGA[kinds[x]]), "y": alt.Y(y, type="quantitative")}
        if color:
            enc["color"] = alt.Color(color, type="nominal")
        return alt.Chart(d).mark_circle(size=60, opacity=0.7).encode(**enc).properties(height=350)

    keys = [x] + ([color] if color else [])
    fmt = None
    if metric:
        if kind == "Pie":
            raise ValueError("Metrics work with Bar, Line and Area charts.")
        if {metric["col_a"], metric["col_b"]} & set(keys):
            raise ValueError("Pick an X axis and split column that this metric does not use.")
        out, ycol = _metric_table(d, keys, metric)
        fmt = metric["format"]
    elif y == COUNT_ROWS:
        out = d.groupby(keys, dropna=False).size().reset_index(name=ROW_COUNT)
        ycol = ROW_COUNT
    else:
        out = d.groupby(keys, dropna=False)[y].agg(AGGS[agg]).reset_index()
        ycol = y

    kinds = column_kinds(out)
    if kinds[x] != "date" and out[x].nunique() > MAX_CATEGORIES:
        top = out.groupby(x)[ycol].sum().nlargest(MAX_CATEGORIES).index
        out = out[out[x].isin(top)]

    if kind == "Pie":
        return (
            alt.Chart(out)
            .mark_arc()
            .encode(theta=alt.Theta(ycol, type="quantitative"), color=alt.Color(x, type="nominal"))
            .properties(height=350)
        )

    chart = alt.Chart(out)
    chart = {
        "Bar": chart.mark_bar(),
        "Line": chart.mark_line(point=True),
        "Area": chart.mark_area(opacity=0.7),
    }[kind]
    xenc = alt.X(x, type=_VEGA[kinds[x]], sort="-y") if (kind == "Bar" and kinds[x] != "date") \
        else alt.X(x, type=_VEGA[kinds[x]])
    enc = {"x": xenc, "y": _yaxis(out, ycol, fmt)}
    if color:
        enc["color"] = alt.Color(color, type="nominal")
    return chart.encode(**enc).properties(height=350)
