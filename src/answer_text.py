"""Plain-English summary of a query result.

Written by our own code from the result table. The AI model never sees the data."""
import calendar

import pandas as pd

WORDS = {"Sum": "total", "Average": "average", "Min": "minimum", "Max": "maximum", "Count": "number of"}


def _num(v) -> str:
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 100 or v == int(v) else f"{v:,.2f}"


def _label(m: dict) -> str:
    col = m.get("column")
    if not col:
        return "number of rows"
    return f"{WORDS.get(m.get('agg'), '')} {col.replace('_', ' ').lower()}".strip()


def _when(ts, bucket) -> str:
    fmt = {"Day": "%d %b %Y", "Year": "%Y"}.get(bucket, "%b %Y")
    return ts.strftime(fmt)


def _show(v, bucket) -> str:
    return _when(v, bucket) if hasattr(v, "strftime") else str(v)


def _who(s, value, bucket):
    names = [_show(i, bucket) for i in s.index[s == value]]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return f"{joined} ({_num(value)}{' each' if len(names) > 1 else ''})"


def _split_line(df, aliases, labels, additive, dims, focus):
    a = aliases[0]
    if not additive[a]:
        return None
    fcol = focus["column"]
    other = next(d for d in dims if d != fcol)
    g = df.groupby([other, fcol])[a].sum().unstack(fcol).fillna(0)
    hit = [c for c in g.columns if str(c).strip().upper() == focus["value"].strip().upper()]
    if not hit:
        return f"No rows for {focus['value']} in this result."
    f, tot = g[hit[0]], g.sum(axis=1)
    parts = ", ".join(f"{_show(i, None)} {f[i] / tot[i]:.1%} ({_num(f[i])} of {_num(tot[i])})"
                      for i in g.index if tot[i])
    return (f"**{hit[0]}** share of {labels[a]} for each {other.replace('_', ' ').lower()}: "
            f"{parts}. Overall: {f.sum() / tot.sum():.1%}.")


def _focus_line(res, df, aliases, labels, additive, dims):
    focus = res.get("focus")
    if not focus or focus["column"] not in dims:
        return None
    if len(dims) == 2:
        return _split_line(df, aliases, labels, additive, dims, focus)
    if len(dims) != 1:
        return None
    x, a = dims[0], aliases[0]
    s = (df.groupby(x)[a].sum() if additive[a] else df.set_index(x)[a]).dropna()
    hit = [i for i in s.index if str(i).strip().upper() == focus["value"].strip().upper()]
    if not hit:
        return f"No rows for {focus['value']} in this result."
    v = s.loc[hit[0]]
    line = f"**{hit[0]}**: {labels[a]} is {_num(v)}"
    if additive[a] and s.sum() and len(s) > 1:
        rank = int((s > v).sum()) + 1
        line += (f" of {_num(s.sum())} in total ({v / s.sum():.1%}), "
                 f"ranked {rank} of {len(s)} by {x.replace('_', ' ').lower()}")
    return line + "."


def _compare_line(spec, df, aliases, labels, dims):
    if len(dims) != 1:
        return None
    x = dims[0]
    if not any(f["column"] == x and len(f["values"]) >= 2 for f in spec.get("filters") or []):
        return None
    a = aliases[0]
    s = df.set_index(x)[a].dropna().sort_values(ascending=False)
    if len(s) < 2:
        return None
    line = f"{labels[a].capitalize()}: " + ", ".join(f"{i} {_num(v)}" for i, v in s.items())
    if s.iloc[-1]:
        line += f". {s.index[0]} is {(s.iloc[0] - s.iloc[-1]) / abs(s.iloc[-1]):.0%} higher than {s.index[-1]}"
    return line + "."


def _period(spec: dict) -> str:
    bits = []
    for f in spec.get("date_filters") or []:
        y, m = f.get("year"), f.get("month")
        if f.get("months"):
            bits.append(", ".join(calendar.month_abbr[int(v)] for v in f["months"]) + (f" {y}" if y else ""))
        if m and y:
            bits.append(f"{calendar.month_name[m]} {y}")
        elif m:
            bits.append(calendar.month_name[m])
        elif y:
            bits.append(str(y))
        if f.get("from") or f.get("to"):
            bits.append(f"{f.get('from') or 'the start'} to {f.get('to') or 'now'}")
    for f in spec.get("filters") or []:
        bits.append(", ".join(str(v) for v in f["values"]))
    return ", ".join(bits)


def summarize(res: dict) -> list:
    df, spec = res.get("df"), res.get("spec") or {}
    info = res.get("info") or {}
    aliases = list(info.get("measures") or [])
    if df is None or df.empty or not aliases:
        return []
    if spec.get("ratio") and len(info.get("raw") or []) == 2:
        num, den = info["raw"]
        rate = aliases[0]
        dcols = [c for c in df.columns if c not in (num, den, rate)]
        _m = spec.get("measures") or []
        nl, dl = _label(_m[0]), _label(_m[1])
        if not dcols:
            if not df[den].sum():
                return []
            return [f"{nl.capitalize()} as % of {dl}: {df[num].sum() / df[den].sum() * 100:.2f}%."]
        g = df.dropna(subset=[rate]).sort_values(rate)
        if g.empty:
            return []
        _b = spec.get("bucket")
        nm = lambda r: ", ".join(_show(r[c], _b) for c in dcols)
        lo, hi = g.iloc[0], g.iloc[-1]
        out = [f"Lowest: {nm(lo)} at {lo[rate]:.2f}% ({_num(lo[num])} of {_num(lo[den])}). "
               f"Highest: {nm(hi)} at {hi[rate]:.2f}%."]
        out.append(f"{nl.capitalize()} as % of {dl}: "
                   + ", ".join(f"{nm(r)} {r[rate]:.2f}%" for _, r in g.head(12).iterrows()) + ".")
        return out
    ms = spec.get("measures") or []
    labels = {a: (_label(ms[i]) if i < len(ms) else a.replace("_", " ").lower()) for i, a in enumerate(aliases)}
    additive = {a: (i < len(ms) and ms[i].get("agg") in ("Sum", "Count")) for i, a in enumerate(aliases)}
    dims = [c for c in df.columns if c not in aliases]
    scope = _period(spec)

    if not dims:
        tail = f" for {scope}" if scope else ""
        return [f"{labels[a].capitalize()}{tail}: {_num(df[a].iloc[0])}." for a in aliases if pd.notna(df[a].iloc[0])]

    bucket = spec.get("bucket")
    x = dims[0]
    is_date = x in (info.get("date_dims") or []) or pd.api.types.is_datetime64_any_dtype(df[x])
    out = [f"Showing results for {scope}."] if scope else []
    for a in aliases:
        if len(dims) > 1 and not additive[a]:
            continue
        s = df.groupby(x)[a].sum() if additive[a] else df.set_index(x)[a]
        if is_date:
            s.index = pd.to_datetime(s.index, errors="coerce")
            s = s[s.index.notna()].sort_index()
        s = s.dropna()
        if s.empty:
            continue
        name = labels[a].capitalize()
        partial = ""
        if is_date and len(s) > 2:
            _t, _lp = pd.Timestamp.today(), s.index[-1]
            if ((bucket == "Year" and _lp.year == _t.year) or
                    (bucket in (None, "Month") and (_lp.year, _lp.month) == (_t.year, _t.month))):
                partial = f" ({_when(_lp, bucket)} is still in progress and left out of this comparison)"
                s = s.iloc[:-1]
        if is_date and len(s) > 1:
            first, last = s.iloc[0], s.iloc[-1]
            text = f"{name} went from {_num(first)} in {_when(s.index[0], bucket)} to {_num(last)} in {_when(s.index[-1], bucket)}"
            if first:
                text += f" ({(last - first) / abs(first):+.0%})"
            text += f", peaking at {_num(s.max())} in {_when(s.idxmax(), bucket)}." + partial
        elif len(s) > 1 and s.max() == s.min():
            text = f"{name}: all {len(s)} are equal ({_num(s.max())})."
        elif len(s) > 1:
            text = f"{name}: highest for {_who(s, s.max(), bucket)}"
            if additive[a] and s.sum() and (s == s.max()).sum() == 1:
                text += f", {s.max() / s.sum():.0%} of the total"
            text += f"; lowest for {_who(s, s.min(), bucket)}."
        else:
            text = f"{name}: {_num(s.iloc[0])}."
        out.append(text)

    if len(dims) == 1 and not is_date and 2 <= len(df) <= 6:
        pos = 1 if scope else 0
        xname = x.replace("_", " ").lower()
        for a in aliases:
            if additive[a]:
                parts = ", ".join(f"{_show(r[x], bucket)} {_num(r[a])}" for _, r in df.iterrows())
                out.insert(pos, f"{labels[a].capitalize()} by {xname}: {parts}.")
                pos += 1

    if len(aliases) >= 2 and all(additive[a] for a in aliases[:2]):
        a, b = aliases[:2]
        g = df.groupby(x)[[a, b]].sum()
        if g[a].sum():
            out.append(f"Overall, {labels[b]} is {g[b].sum() / g[a].sum():.0%} of {labels[a]}.")
        if not is_date and len(g) > 1:
            gap = g[a] - g[b]
            out.append(f"Largest gap between the two: {_show(gap.idxmax(), bucket)} ({_num(gap.max())}).")

    if len(dims) > 1:
        a = next((m for m in aliases if additive[m]), None)
        if a and df[a].notna().any():
            top = df.loc[df[a].idxmax()]
            combo = ", ".join(f"{d.replace('_', ' ').lower()} {_show(top[d], bucket)}" for d in dims)
            out.append(f"Highest single row for {labels[a]}: {_num(top[a])} ({combo}).")
    line = _focus_line(res, df, aliases, labels, additive, dims)
    if line is None:
        line = _compare_line(spec, df, aliases, labels, dims)
    if line:
        out.insert(0, line)
    return out
