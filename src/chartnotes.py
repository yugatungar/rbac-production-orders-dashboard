import datetime as dt

import pandas as pd

_AGG = {"Sum": "sum", "Average": "mean", "Count": "count", "Min": "min", "Max": "max"}
_AGG_WORD = {"Sum": "total", "Average": "average", "Count": "count", "Min": "minimum", "Max": "maximum"}
COUNT_ROWS = "(count of rows)"


def _nice(c: str) -> str:
    return str(c).replace("_", " ").lower()


def _num(v: float, fmt: str | None = None) -> str:
    if fmt == "PERCENT":
        return f"{v:.1%}"
    a = abs(v)
    if a >= 100 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.1f}" if a >= 10 else f"{v:,.2f}"


def _is_date(s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
        return False
    first = s.dropna().iloc[0] if s.notna().any() else None
    return isinstance(first, (dt.date, dt.datetime))


def _bucketed(d: pd.DataFrame, x: str, bucket: str | None) -> pd.DataFrame:
    d = d.copy()
    if _is_date(d[x]):
        d[x] = pd.to_datetime(d[x])
        if bucket == "Day":
            d[x] = d[x].dt.normalize()
        elif bucket == "Month":
            d[x] = d[x].dt.to_period("M").dt.to_timestamp()
        elif bucket == "Year":
            d[x] = d[x].dt.to_period("Y").dt.to_timestamp()
    return d


def _label(v) -> str:
    if isinstance(v, pd.Timestamp):
        return v.strftime("%b %Y") if v.day == 1 else v.strftime("%d %b %Y")
    return str(v)


def _compare(vals: pd.Series, fmt, unit: str) -> str:
    """Sentence about the highest and lowest group of a series indexed by group."""
    vals = vals.dropna()
    if len(vals) < 2:
        return ""
    hi, lo = vals.idxmax(), vals.idxmin()
    if vals.max() == vals.min():
        return f"Every group has the same {unit} ({_num(vals.max(), fmt)})."
    out = f"Highest: {_label(hi)} ({_num(vals.max(), fmt)}); lowest: {_label(lo)} ({_num(vals.min(), fmt)})."
    if vals.min() > 0 and fmt != "PERCENT" and vals.max() / vals.min() >= 1.5:
        out += f" The top group is {vals.max() / vals.min():.1f} times the lowest."
    return out


def _trend(vals: pd.Series, fmt) -> str:
    vals = vals.dropna().sort_index()
    if len(vals) < 3:
        return ""
    first, last = vals.iloc[0], vals.iloc[-1]
    peak = vals.idxmax()
    out = f"From {_label(vals.index[0])} to {_label(vals.index[-1])} it moves from {_num(first, fmt)} to {_num(last, fmt)}"
    if first and fmt != "PERCENT":
        out += f" ({(last - first) / abs(first):+.0%})"
    return out + f", peaking in {_label(peak)} ({_num(vals.max(), fmt)})."


def describe_chart(df: pd.DataFrame, spec: dict) -> str:
    """One or two plain sentences saying what the chart shows. Never raises."""
    try:
        return _describe(df, spec)
    except Exception:
        return ""


def _describe(df: pd.DataFrame, spec: dict) -> str:
    kind, x, y = spec["chart_type"], spec["x"], spec["y"]
    agg, color, bucket = spec.get("agg"), spec.get("color"), spec.get("bucket")
    metric, extra = spec.get("metric"), [c for c in (spec.get("extra") or []) if c != y]
    if df is None or df.empty:
        return ""
    d = _bucketed(df, x, bucket)
    date_x = _is_date(df[x])
    split = f", split by {_nice(color)}" if color and color != x and kind not in ("Pie", "Scatter") else ""
    unit_x = f"{bucket.lower()} of {_nice(x)}" if (date_x and bucket) else _nice(x)

    if kind == "Scatter":
        s = d[[x, y]].dropna()
        if len(s) < 5 or not pd.api.types.is_numeric_dtype(s[x]) or not pd.api.types.is_numeric_dtype(s[y]):
            return f"Each dot is one row, plotted by {_nice(x)} and {_nice(y)}."
        r = s[x].corr(s[y])
        if pd.isna(r):
            return f"Each dot is one row, plotted by {_nice(x)} and {_nice(y)}."
        strength = "a strong" if abs(r) >= 0.7 else "a moderate" if abs(r) >= 0.4 else "little to no"
        way = "positive" if r > 0 else "negative"
        tail = "" if strength == "little to no" else f" {way}"
        return (f"Each dot is one row. Across {len(s):,} rows there is {strength}{tail} relationship "
                f"between {_nice(x)} and {_nice(y)} (correlation {r:.2f}).")

    if metric:
        a, b = metric["col_a"], metric["col_b"]
        g = d.groupby(x)[[a, b]].sum()
        if metric["kind"] == "RATIO":
            vals = g[a] / g[b].where(g[b] != 0)
            how = f"{metric['label']} is {_nice(a)} divided by {_nice(b)}, worked out from totals for each {unit_x}."
        else:
            vals = g[a] - g[b]
            how = f"{metric['label']} is {_nice(a)} minus {_nice(b)}, worked out from totals for each {unit_x}."
        fmt = metric["format"]
        body = _trend(vals, fmt) if date_x and kind in ("Line", "Area") else _compare(vals, fmt, metric["label"].lower())
        return f"{how} {body}".strip()

    if extra and y != COUNT_ROWS and kind in ("Bar", "Line", "Area"):
        cols = [y] + extra
        g = d.groupby(x)[cols].agg(_AGG[agg])
        word = _AGG_WORD[agg]
        totals = ", ".join(f"{_nice(c)} {_num(float(d[c].agg(_AGG[agg])))}" for c in cols)
        out = f"{word.capitalize()} of each measure by {_nice(x)}; overall: {totals}."
        if len(cols) == 2 and agg == "Sum" and d[cols[1]].sum() and d[cols[0]].sum():
            ratio = d[cols[1]].sum() / d[cols[0]].sum()
            out += f" {_nice(cols[1]).capitalize()} is {ratio:.0%} of {_nice(cols[0])}."
        if len(cols) == 2 and len(g) >= 2:
            gap = (g[cols[0]] - g[cols[1]])
            if gap.max() != gap.min():
                out += f" The widest gap between the two is for {_label(gap.abs().idxmax())} ({_num(float(gap[gap.abs().idxmax()]))})."
        return out

    if y == COUNT_ROWS:
        vals = d.groupby(x).size().astype(float)
        what = f"Number of rows for each {unit_x}{split}."
        fmt, unit = None, "count"
    else:
        vals = d.groupby(x)[y].agg(_AGG[agg]).astype(float)
        what = f"{_AGG_WORD[agg].capitalize()} of {_nice(y)} for each {unit_x}{split}."
        fmt, unit = None, _AGG_WORD[agg]

    if kind == "Pie":
        share = (vals / vals.sum()).sort_values(ascending=False)
        if vals.sum() <= 0 or len(share) < 2:
            return what
        top = share.iloc[0]
        txt = f"{_label(share.index[0])} is the largest slice at {top:.0%}"
        if len(share) > 1:
            txt += f", then {_label(share.index[1])} at {share.iloc[1]:.0%}"
        return f"{what} {txt}."

    body = _trend(vals, fmt) if date_x and kind in ("Line", "Area") else _compare(vals, fmt, unit)
    if not date_x and (agg == "Sum" or y == COUNT_ROWS) and len(vals) >= 3 and vals.sum() > 0 and (vals >= 0).all():
        body += f" {_label(vals.idxmax())} makes up {vals.max() / vals.sum():.0%} of the total."
    return f"{what} {body}".strip()


def _series_for(d: pd.DataFrame, spec: dict):
    """Plotted value per X group, or (None, None) when the chart has no single series."""
    x, y, agg, metric = spec["x"], spec["y"], spec.get("agg"), spec.get("metric")
    if spec["chart_type"] == "Scatter":
        return None, None
    if metric:
        a, b = metric["col_a"], metric["col_b"]
        g = d.groupby(x)[[a, b]].sum()
        vals = g[a] / g[b].where(g[b] != 0) if metric["kind"] == "RATIO" else g[a] - g[b]
        return vals.dropna(), metric["format"]
    if spec.get("extra"):
        return None, None
    if y == COUNT_ROWS:
        return d.groupby(x).size().astype(float), None
    return d.groupby(x)[y].agg(_AGG[agg]).astype(float), None


def explain_chart(df: pd.DataFrame, spec: dict, row_scope: str = "ALL") -> dict:
    """Beginner-friendly help: how to read the chart, key takeaways, things to keep in mind."""
    try:
        return _explain(df, spec, row_scope)
    except Exception:
        return {"read": "", "takeaways": [], "cautions": []}


def _explain(df: pd.DataFrame, spec: dict, row_scope: str) -> dict:
    kind, x, y = spec["chart_type"], spec["x"], spec["y"]
    agg, color, bucket = spec.get("agg"), spec.get("color"), spec.get("bucket")
    metric, extra = spec.get("metric"), [c for c in (spec.get("extra") or []) if c != y]
    if df is None or df.empty:
        return {"read": "", "takeaways": [], "cautions": []}
    d = _bucketed(df, x, bucket)
    date_x = _is_date(df[x])
    unit_x = f"{bucket.lower()} of {_nice(x)}" if (date_x and bucket) else _nice(x)
    plain = not metric and y != COUNT_ROWS
    if metric:
        what = metric["label"].lower()
    elif y == COUNT_ROWS:
        what = "number of rows"
    else:
        what = f"{_AGG_WORD.get(agg, '')} {_nice(y)}".strip()
    split = (f" Colours show the different {_nice(color)} values."
             if color and color != x and kind not in ("Pie", "Scatter") and not extra else "")

    # --- how to read it
    if kind == "Scatter":
        read = (f"Each dot is one row. A dot's position across shows its {_nice(x)} and its height shows its "
                f"{_nice(y)}. If the dots rise from left to right, the two grow together; if they form a cloud "
                f"with no direction, there is little link between them.")
    elif kind == "Pie":
        read = (f"The whole circle is 100% of the {what}. Each slice is one {unit_x}; the bigger the slice, "
                f"the bigger its share.")
    elif extra:
        read = (f"Each {unit_x} has one mark per measure, shown in different colours. Compare the colours "
                f"inside one {unit_x} to see how the measures differ.")
    elif kind == "Bar":
        read = (f"Each bar is one {unit_x}. The taller the bar, the higher the {what}. "
                f"Compare bar heights to see which {unit_x} is bigger or smaller.{split}")
    elif date_x:
        read = (f"The {'line' if kind == 'Line' else 'shaded area'} follows the {what} over time. Time runs from "
                f"left (earliest) to right (latest). Going up means it is increasing and going down means it is falling.{split}")
    else:
        read = (f"Each point is one {unit_x}, and the line only joins them. Read it like a bar chart: the height "
                f"shows the {what}. The line does not mean a trend over time.{split}")
    if metric:
        a, b = _nice(metric["col_a"]), _nice(metric["col_b"])
        read += (f" {metric['label']} is {a} divided by {b}." if metric["kind"] == "RATIO"
                 else f" {metric['label']} is {a} minus {b}.")

    # --- takeaways
    take = []
    note = describe_chart(df, spec)
    if note:
        take.append(note)
    vals, fmt = _series_for(d, spec)
    if vals is not None and len(vals) >= 4 and not date_x and vals.max() != vals.min():
        top3 = vals.sort_values(ascending=False).head(3)
        take.append("Top 3: " + ", ".join(f"{_label(k)} ({_num(v, fmt)})" for k, v in top3.items()) + ".")
        if fmt is None and (vals >= 0).all() and vals.sum() > 0 and len(vals) >= 5 and (agg in ("Sum", None)):
            take.append(f"The top 3 together make up {top3.sum() / vals.sum():.0%} of the total.")
    used = [c for c in ([x] + ([y] if plain else []) + extra
                        + ([metric["col_a"], metric["col_b"]] if metric else [])) if c in df.columns]
    for c in used:
        miss = int(df[c].isna().sum())
        if miss:
            take.append(f"{miss:,} of {len(df):,} rows have no value for {_nice(c)}, so they are left out of its figures.")
    take.append(f"This chart is based on {len(df):,} rows" + (" (only your own rows)." if row_scope == "OWN" else "."))

    # --- cautions
    care = []
    if plain and agg == "Average":
        care.append("An average hides differences inside a group: a group can contain a few very high or very low values.")
    if plain and agg in ("Min", "Max"):
        care.append("Minimum and maximum each come from a single row, so they say little about the typical case.")
    if plain and agg == "Count":
        care.append("Count only counts rows that have a value in the chosen column.")
    if plain and agg == "Sum" and kind in ("Bar", "Pie", "Line", "Area") and not date_x:
        sizes = d.groupby(x).size()
        if len(sizes) >= 2 and sizes.min() > 0 and sizes.max() / sizes.min() >= 1.5:
            care.append("Totals favour groups that simply have more rows. To compare groups fairly, try Average or a metric.")
    if metric and metric["kind"] == "RATIO":
        care.append("The ratio is worked out from each group's totals, not by averaging every row's own ratio.")
    if date_x and pd.to_datetime(df[x]).max() > pd.Timestamp.today():
        care.append("Some dates are in the future, so the latest periods may be plans or only partly filled.")
    if kind == "Pie" and vals is not None and len(vals) > 6:
        care.append("Pie charts are hard to read with many slices. A bar chart makes the comparison easier.")
    if kind == "Scatter":
        care.append("Two columns moving together does not prove that one causes the other.")
    if row_scope == "OWN":
        care.append("You only see your own rows, so these figures are not company-wide.")
    return {"read": read, "takeaways": take, "cautions": care}

