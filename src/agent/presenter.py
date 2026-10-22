"""Turns any query result into one headline, an optional chart and context. Our code only; the AI never sees data."""
import datetime as dt
import re
from decimal import Decimal

import altair as alt
import pandas as pd

_DIMLIKE = re.compile(r"(^|_)(YEAR|MONTH|QUARTER|WEEK|DAY|RANK|RN|ROW_NUM|ROWNUM)(_|$)", re.I)
_PCT = re.compile(r"(PCT|PERCENT|RATE)", re.I)
_RANKQ = re.compile(r"\b(top|bottom|highest|lowest|most|least|best|worst|largest|smallest)\b", re.I)


def is_ranking(q: str) -> bool:
    return bool(_RANKQ.search(q or ""))


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        s = df[c]
        if s.dtype == object:
            vals = s.dropna()
            if len(vals) and all(isinstance(v, (Decimal, int, float)) and not isinstance(v, bool) for v in vals):
                df[c] = pd.to_numeric(s, errors="coerce")
            elif len(vals) and all(isinstance(v, (dt.date, dt.datetime)) for v in vals):
                df[c] = pd.to_datetime(s, errors="coerce")
    return df


def shape(df: pd.DataFrame):
    meas = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])
            and not pd.api.types.is_bool_dtype(df[c]) and not _DIMLIKE.search(str(c))]
    return [c for c in df.columns if c not in meas], meas


def _nice(c) -> str:
    return re.sub(r"_?(PCT|PERCENT)$", "", str(c), flags=re.I).replace("_", " ").lower().strip()


def _fmt(col, v) -> str:
    if v is None or pd.isna(v):
        return "n/a"
    v = float(v)
    s = f"{v:,.0f}" if abs(v) >= 100 or v == int(v) else f"{v:,.2f}"
    return s + "%" if _PCT.search(str(col)) else s


def _val(v) -> str:
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "(blank)"
    if isinstance(v, (pd.Timestamp, dt.datetime, dt.date)):
        t = pd.Timestamp(v)
        return t.strftime("%b %Y") if t.day == 1 else t.strftime("%d %b %Y")
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def _label(r, dims) -> str:
    return ", ".join(_val(r[d]) for d in dims) or "row"


def headline(df, dims, meas, question: str = "") -> str:
    n = len(df)
    if n == 0:
        return "No rows matched your question."
    if not meas:
        return f"{n} row{'s' if n != 1 else ''} found" + (" (limit reached, there may be more)." if n >= 500 else ".")
    p = meas[0]
    if n == 1:
        r = df.iloc[0]
        if dims:
            return f"{_label(r, dims)}: " + "; ".join(f"{_nice(m)} {_fmt(m, r[m])}" for m in meas) + "."
        return "; ".join(f"{_nice(m).capitalize()}: {_fmt(m, r[m])}" for m in meas) + "."
    date_dim = next((d for d in dims if pd.api.types.is_datetime64_any_dtype(df[d])), None)
    if date_dim and len(dims) == 1 and n >= 3:
        s = df.sort_values(date_dim)[[date_dim, p]].dropna()
        partial, today = "", pd.Timestamp.today()
        last = s.iloc[-1][date_dim]
        if len(s) > 2 and (last.year, last.month) == (today.year, today.month):
            partial = f" ({_val(last)} is still in progress and left out of this comparison)"
            s = s.iloc[:-1]
        if len(s) >= 2:
            f, l = s.iloc[0], s.iloc[-1]
            t = f"{_nice(p).capitalize()} went from {_fmt(p, f[p])} in {_val(f[date_dim])} to {_fmt(p, l[p])} in {_val(l[date_dim])}"
            if f[p]:
                t += f" ({(l[p] - f[p]) / abs(f[p]):+.0%})"
            pk = s.loc[s[p].idxmax()]
            return t + f", peaking at {_fmt(p, pk[p])} in {_val(pk[date_dim])}." + partial
    if n <= 5:
        parts = ", ".join(f"{_label(r, dims)} {_fmt(p, r[p])}" for _, r in df.iterrows())
        return f"{_nice(p).capitalize()} by {', '.join(_nice(d) for d in dims) or 'row'}: {parts}."
    s = df.dropna(subset=[p])
    hi, lo = s.loc[s[p].idxmax()], s.loc[s[p].idxmin()]
    return f"Highest {_nice(p)}: {_label(hi, dims)} ({_fmt(p, hi[p])}). Lowest: {_label(lo, dims)} ({_fmt(p, lo[p])})."


def make_chart(df, dims, meas, highlight: bool = False):
    if not dims or not meas or len(dims) > 2 or not 2 <= len(df) <= 60:
        return None
    clean = lambda c: re.sub(r"\W", "_", str(c))
    d = df.copy()
    d.columns = [clean(c) for c in d.columns]
    dims, p, title = [clean(c) for c in dims], clean(meas[0]), _nice(meas[0])
    x, tip = dims[0], list(d.columns)
    if len(dims) == 2 and d[dims[1]].nunique() > 12:
        return None
    is_date = pd.api.types.is_datetime64_any_dtype(d[x])
    if is_date:
        fmt = "%b %Y" if (d[x].dt.day == 1).all() else "%d %b %Y"
        if len(d) >= 3:
            enc = dict(x=alt.X(f"{x}:T", axis=alt.Axis(format=fmt, title=None)), y=alt.Y(f"{p}:Q", title=title), tooltip=tip)
            if len(dims) == 2:
                enc["color"] = alt.Color(f"{dims[1]}:N")
            return alt.Chart(d).mark_line(point=True).encode(**enc)
        d[x] = d[x].dt.strftime(fmt)
    xenc = alt.X(f"{x}:N", sort=None, axis=alt.Axis(labelAngle=-45, title=None))
    yenc = alt.Y(f"{p}:Q", title=title)
    if len(dims) == 2:
        return alt.Chart(d).mark_bar().encode(x=xenc, y=yenc, color=alt.Color(f"{dims[1]}:N"), tooltip=tip)
    color = alt.value("#4c78a8")
    if highlight:
        color = alt.condition(alt.datum[x] == d[x].iloc[0], alt.value("#e45756"), alt.value("#b8c2cc"))
    chart = alt.Chart(d).mark_bar().encode(x=xenc, y=yenc, color=color, tooltip=tip)
    if len(d) <= 15:
        chart = chart + alt.Chart(d).mark_text(dy=-8).encode(x=xenc, y=yenc, text=alt.Text(f"{p}:Q", format=",.2~f"))
    return chart
