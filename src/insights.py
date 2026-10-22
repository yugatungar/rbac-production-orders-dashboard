import datetime as dt

import pandas as pd

MAX_DIM_VALUES = 15


def _kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "text"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date"
    first = s.dropna().iloc[0] if s.notna().any() else None
    return "date" if isinstance(first, (dt.date, dt.datetime)) else "text"


def _nice(col: str) -> str:
    return col.replace("_", " ").lower()


def _fmt(v: float, fmt: str) -> str:
    return f"{v:.1%}" if fmt == "PERCENT" else f"{v:,.0f}"


def _dimensions(df: pd.DataFrame) -> list[str]:
    """Text columns with a small number of distinct values (plants, statuses, models...)."""
    dims = []
    for c in df.columns:
        if _kind(df[c]) != "text":
            continue
        n = df[c].nunique(dropna=True)
        if 2 <= n <= MAX_DIM_VALUES and n < len(df) / 3:
            dims.append(c)
    return dims


def _measures(df: pd.DataFrame) -> list[str]:
    """Numeric columns that are real quantities (not row identifiers, not negative)."""
    out = []
    for c in df.columns:
        s = df[c]
        if _kind(s) != "number" or s.notna().sum() == 0:
            continue
        if s.nunique() == len(s):  # unique per row, so probably an id
            continue
        if (s.dropna() < 0).any() or s.sum() <= 0:
            continue
        out.append(c)
    return out


def _metric_items(df, metrics, dims):
    items = []
    for m in metrics:
        a, b, label, fmt = m["col_a"], m["col_b"], m["label"], m["format"]
        if a not in df.columns or b not in df.columns:
            continue
        ratio = m["kind"] == "RATIO"
        tot_a, tot_b = df[a].sum(), df[b].sum()
        overall = (tot_a / tot_b if tot_b else None) if ratio else (tot_a - tot_b)
        if overall in (None, 0):
            continue
        best = None
        for dim in dims:
            if dim in (a, b):
                continue
            g = df.groupby(dim)[[a, b]].sum()
            vals = (g[a] / g[b].where(g[b] != 0)).dropna() if ratio else (g[a] - g[b])
            if len(vals) < 2:
                continue
            if ratio:
                ok = g.loc[vals.index]  # compare against the same groups that have a valid ratio
                base = ok[a].sum() / ok[b].sum()
                if base == 0:
                    continue
                score = (vals.max() - vals.min()) / abs(base)
                if score < 0.10:
                    continue
                text = (f"{label} varies most by {_nice(dim)}: highest for {vals.idxmax()} "
                        f"({_fmt(vals.max(), fmt)}), lowest for {vals.idxmin()} "
                        f"({_fmt(vals.min(), fmt)}), against {_fmt(base, fmt)} overall.")
            else:
                if vals.sum() <= 0 or (vals < 0).any():
                    continue
                share = vals.max() / vals.sum()
                score = share * len(vals) - 1
                if score < 0.25:
                    continue
                text = (f"{vals.idxmax()} ({_nice(dim)}) holds {share:.0%} of the total "
                        f"{label.lower()} ({_fmt(vals.sum(), fmt)}).")
            if best is None or score > best[0]:
                best = (score, text)
        if best:
            items.append({"kind": "metric", "score": best[0] + 1.0, "text": best[1]})
    return items


def _share_items(df, dims, measures):
    items = []
    for c in measures:
        for dim in dims:
            if dim == c:
                continue
            g = df.groupby(dim)[c].sum()
            n = len(g)
            if n < 3 or g.sum() <= 0:
                continue
            share = g.max() / g.sum()
            score = share * n
            if share >= 0.35 and score >= 1.25:
                items.append({
                    "kind": "share", "score": score,
                    "text": f"{g.idxmax()} accounts for {share:.0%} of total {_nice(c)} across {_nice(dim)}.",
                })
    return items


def _outlier_items(df, measures):
    items = []
    for c in measures:
        s = df[c].dropna()
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        upper = q3 + 3 * iqr
        n = int((s > upper).sum())
        if 0 < n <= max(1, int(0.05 * len(s))):
            items.append({
                "kind": "outlier", "score": 1.0 + n / len(s),
                "text": (f"{n} rows have" if n != 1 else "1 row has") + f" unusually high {_nice(c)} (above {upper:,.0f}).",
            })
    return items


def _quality_items(df):
    items = []
    for c in df.columns:
        miss = df[c].isna().mean()
        if miss > 0.05:
            items.append({
                "kind": "quality", "score": 0.5 + miss,
                "text": f"{_nice(c)} is empty in {miss:.0%} of rows, so figures using it may be incomplete.",
            })
    return items


def generate_insights(df: pd.DataFrame, metrics: list[dict], limit: int = 6) -> list[str]:
    """Plain-English findings from the rows and columns this user can see.

    Works on any table: generic checks need no setup, metrics add business meaning.
    """
    if df is None or df.empty or len(df) < 5:
        return []
    dims = _dimensions(df)
    measures = _measures(df)

    pool = {
        "metric": _metric_items(df, metrics, dims),
        "share": _share_items(df, dims, measures),
        "outlier": _outlier_items(df, measures),
        "quality": _quality_items(df),
    }
    caps = {"metric": 3, "share": 2, "outlier": 1, "quality": 1}

    picked = []
    for kind, cap in caps.items():
        picked += sorted(pool[kind], key=lambda i: -i["score"])[:cap]
    picked.sort(key=lambda i: -i["score"])
    return [i["text"] for i in picked[:limit]]
