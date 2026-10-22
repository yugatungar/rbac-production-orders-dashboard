import re

import pandas as pd

from src.insights import _kind

COUNT_ROWS = "(count of rows)"
AGG_NAMES = {"Sum": "total", "Average": "average", "Min": "minimum", "Max": "maximum"}
MAX_FILTER_VALUES = 30
_STOP = {"count", "date", "number", "name", "type", "code", "value", "total", "id", "data"}
_SYN = {"qty": "quantity", "quantity": "qty"}
_WORDS = set("""
show me give draw make plot chart graph a an the of for by per each every across in on at to from with and or vs versus
against between is are was were what which how many much number count counts total sum average avg mean typical max
maximum min minimum peak pie donut share shares proportion proportions portion portions percent percentage scatter
correlation correlate relationship line bar area column columns trend over time timeline history monthly month yearly
year annual annually daily day i want see like can you please display compare comparison all only my our orders order
rows row records record items item data table results split group grouped broken down segmented no
that this it get need tell about where when also then plus its their
""".split())
_DIM_MARK = re.compile(
    r"(?:\bby|\bper|\beach|\bevery|\bacross|\bgrouped by|\bgroup by|\bbroken down by|\bsplit by|"
    r"\bsegmented by|\bfor each|\bagainst each)(?:\s+(?:the|each|every|a|an))*\s*$"
)
_JOIN = re.compile(r"(?:\band|,|\bvs|\bversus|\bagainst|\bwith|\bplus|\bthen)\s*$")


def _norm(text: str) -> str:
    q = text.lower()
    q = re.sub(r"[_\-]", " ", q)
    q = re.sub(r"[^\w\s%.]", " ", q)
    q = re.sub(r"\.(?!\d)", " ", q)  # keep decimals like 6.7, drop sentence dots
    return re.sub(r"\s+", " ", q).strip()


def _nice(c: str) -> str:
    return str(c).replace("_", " ").lower()


def _pat(phrase: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?:s|es)?(?!\w)")


def _name_variants(tokens: list[str]) -> set[str]:
    out = {" ".join(tokens)}
    if any(t in _SYN for t in tokens):
        out.add(" ".join(_SYN.get(t, t) for t in tokens))
    if len(tokens) == 2:
        rev = tokens[::-1]
        out.add(" ".join(rev))
        if any(t in _SYN for t in rev):
            out.add(" ".join(_SYN.get(t, t) for t in rev))
    return out


def _entities(q: str, df: pd.DataFrame, metrics: list[dict]) -> list[dict]:
    """Columns and metrics mentioned in the question, longest phrases first, no overlaps."""
    names = {c: _nice(c).split() for c in df.columns}
    mnames = {m["id"]: re.sub(r"[^\w\s]", " ", m["label"].lower()).split() for m in metrics}
    highcard = {c for c in df.columns if _kind(df[c]) == "text" and df[c].nunique(dropna=True) > MAX_FILTER_VALUES}
    counts: dict[str, int] = {}  # how many columns use each word
    for toks in names.values():
        for t in set(toks):
            counts[t] = counts.get(t, 0) + 1
    mcounts: dict[str, int] = {}
    for toks in mnames.values():
        for t in set(toks):
            mcounts[t] = mcounts.get(t, 0) + 1

    cands = []
    for c, toks in names.items():
        for v in _name_variants(toks):
            cands.append((v, "col", c))
        if len(toks) > 1 and c not in highcard:
            for t in toks:
                if len(t) >= 4 and t not in _STOP and counts[t] == 1:
                    cands.append((t, "col", c))
    by_id = {m["id"]: m for m in metrics}
    for mid, toks in mnames.items():
        cands.append((" ".join(toks), "metric", mid))
        if len(toks) > 1 and len(toks[0]) >= 4 and toks[0] not in counts and mcounts[toks[0]] == 1 and toks[0] not in _STOP:
            cands.append((toks[0], "metric", mid))

    hits = []
    for phrase, kind, ref in cands:
        for m in _pat(phrase).finditer(q):
            hits.append((m.end() - m.start(), m.start(), m.end(), kind, ref))
    hits.sort(key=lambda h: (-h[0], h[1]))
    taken, chosen = [False] * len(q), []
    for ln, s, e, kind, ref in hits:
        if any(taken[s:e]):
            continue
        for i in range(s, e):
            taken[i] = True
        chosen.append({"start": s, "end": e, "kind": kind, "ref": by_id[ref] if kind == "metric" else ref})
    chosen.sort(key=lambda h: h["start"])
    return chosen


def _mask(q: str, ents: list[dict]) -> str:
    chars = list(q)
    for e in ents:
        for i in range(e["start"], e["end"]):
            chars[i] = " "
    return "".join(chars)


def _filter_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns
            if _kind(df[c]) == "text" and 2 <= df[c].nunique(dropna=True) <= MAX_FILTER_VALUES]


def _find_filters(masked: str, df: pd.DataFrame) -> dict[str, list]:
    found: dict[str, list] = {}
    for c in _filter_columns(df):
        for v in df[c].dropna().unique():
            norm = str(v).lower().replace("_", " ")
            if len(norm) < 2:
                continue
            if re.search(r"(?<!\w)" + re.escape(norm) + r"(?!\w)", masked):
                found.setdefault(c, []).append(v)
    return found


def _unknown_words(masked: str, filters: dict) -> list[str]:
    text = masked
    for vals in filters.values():
        for v in vals:
            norm = str(v).lower().replace("_", " ")
            text = re.sub(r"(?<!\w)" + re.escape(norm) + r"(?!\w)", " ", text)
    out = []
    for w in re.findall(r"[a-z][a-z0-9.%]*", text):
        w = w.strip(".")
        base = w[:-1] if w.endswith("s") else w
        if len(w) >= 3 and w not in _WORDS and base not in _WORDS and w not in out:
            out.append(w)
    return out


def _fail(msg: str) -> dict:
    return {"ok": False, "message": msg}


def parse_question(question: str, df: pd.DataFrame, metrics: list[dict]) -> dict:
    """Turn a plain-English request into a chart spec. Uses only columns/values in df.

    df is what the signed-in role may see, so hidden columns can never be requested.
    """
    if not question or not question.strip():
        return _fail("Type what you would like to see, for example: total qty planned by plant.")
    q = _norm(question)
    ents = _entities(q, df, metrics)
    masked = _mask(q, ents)
    kinds = {c: _kind(df[c]) for c in df.columns}
    notes = []

    # roles: dimension (group by) or measure (number to chart)
    last_role = None
    marked_dims, measures, loose_dims, metric_ents = [], [], [], []
    for e in ents:
        before = q[: e["start"]].rstrip()
        if e["kind"] == "metric":
            role = "measure"
            metric_ents.append(e["ref"])
        elif _DIM_MARK.search(before):
            role = "dim"
        elif _JOIN.search(before) and last_role:
            role = last_role
        else:
            role = "measure" if kinds[e["ref"]] == "number" else "loose"
            if role == "loose" and kinds[e["ref"]] == "text" and e["ref"] not in set(_filter_columns(df)):
                role = "ignore"
        if e["kind"] == "col" and role != "ignore":
            {"dim": marked_dims, "measure": measures, "loose": loose_dims}[role].append(e["ref"])
        last_role = role if role not in ("loose", "ignore") else last_role

    # words
    scatter = re.search(r"\b(scatter|correlat\w*|relationship)\b", masked)
    pie = re.search(r"\b(pie|donut|shares?|proportions?|portions?|percent(?:age)? of)\b", masked)
    area = re.search(r"\barea\b", masked)
    line = re.search(r"\bline\b", masked)
    trend = re.search(r"\b(trend|over time|timeline|time series|history)\b", masked)
    bucket = None
    if re.search(r"\b(monthly|per month|by month|each month|month wise|month)\b", masked):
        bucket = "Month"
    elif re.search(r"\b(yearly|per year|by year|each year|annual|annually|year)\b", masked):
        bucket = "Year"
    elif re.search(r"\b(daily|per day|by day|each day|day)\b", masked):
        bucket = "Day"
    agg = "Sum"
    if re.search(r"\b(average|avg|mean|typical)\b", masked):
        agg = "Average"
    elif re.search(r"\b(maximum|max|peak)\b", masked):
        agg = "Max"
    elif re.search(r"\b(minimum|min)\b", masked):
        agg = "Min"
    count_words = re.search(r"\b(how many|number of|count of|counts of|no of)\b|^count\b", masked)

    date_cols = [c for c in df.columns if kinds[c] == "date"]
    dims = marked_dims + [c for c in loose_dims if c not in marked_dims]
    if (bucket or trend) and date_cols:
        date_pick = next((c for c in dims if kinds[c] == "date"), date_cols[0])
        dims = [date_pick] + [c for c in dims if c != date_pick]
    elif (bucket or trend) and not date_cols:
        notes.append("There is no date column you can see, so I ignored the time words.")
        bucket = None

    metric = metric_ents[0] if metric_ents else None
    if len(metric_ents) > 1:
        notes.append(f"I used {metric['label']} only; metrics are drawn one at a time.")

    chart_type = "Bar"
    if scatter:
        chart_type = "Scatter"
    elif pie:
        chart_type = "Pie"
    elif area:
        chart_type = "Area"
    elif line:
        chart_type = "Line"

    extra: list[str] = []
    color = None

    # ---- scatter
    if chart_type == "Scatter":
        if len(measures) < 2:
            return _fail("A scatter chart needs two number columns, for example: scatter of qty planned vs qty built.")
        x, y = measures[0], measures[1]
        color = next((c for c in dims if kinds[c] == "text"), None)
        spec = {"chart_type": "Scatter", "x": x, "y": y, "agg": None, "color": color,
                "bucket": None, "extra": [], "metric": None}
    else:
        x = dims[0] if dims else None
        if x is None:
            unknown = _unknown_words(masked, _find_filters(masked, df))
            if unknown and not metric and not measures:
                return _fail(_not_found(unknown, df, metrics, kinds))
            return _fail("What should I group by? Try adding 'by' and a column, for example: by plant.")
        color = next((c for c in dims[1:] if kinds[c] == "text"), None) if chart_type != "Pie" else None
        if kinds[x] == "date" and chart_type == "Bar" and not scatter:
            chart_type = "Line"
        if kinds[x] != "date":
            bucket = None
        elif not bucket:
            bucket = "Month"

        if metric:
            if chart_type == "Pie":
                chart_type = "Bar"
                notes.append("Metrics work with bar, line and area charts, so I used a bar chart.")
            if x in (metric["col_a"], metric["col_b"]):
                return _fail(f"{metric['label']} is built from {_nice(metric['col_a'])} and "
                             f"{_nice(metric['col_b'])}, so it cannot also be grouped by {_nice(x)}.")
            if color in (metric["col_a"], metric["col_b"]):
                color = None
            y, agg_used = metric["label"], None
            if measures:
                notes.append(f"I used {metric['label']} and ignored the other number columns.")
        elif measures:
            y, agg_used = measures[0], agg
            if chart_type in ("Bar", "Line", "Area") and len(measures) > 1:
                extra = measures[1:]
                color = None
        else:
            y, agg_used = COUNT_ROWS, None
            if not count_words:
                notes.append("You did not name a number column, so I counted rows.")
        spec = {"chart_type": chart_type, "x": x, "y": y, "agg": agg_used, "color": color,
                "bucket": bucket, "extra": extra, "metric": metric}

    filters = _find_filters(masked, df)
    unknown = _unknown_words(masked, filters)
    if unknown and not metric and not measures and not count_words and chart_type != "Scatter":
        return _fail(_not_found(unknown, df, metrics, kinds))
    if unknown:
        notes.append("I did not recognise: " + ", ".join(unknown) + ".")
    return {"ok": True, "spec": spec, "filters": filters, "notes": notes,
            "summary": describe_request(spec, filters)}


def _not_found(unknown: list[str], df: pd.DataFrame, metrics: list[dict], kinds: dict) -> str:
    can = [_nice(c) for c in df.columns if kinds[c] == "number" and df[c].nunique() < len(df)]
    can += [m["label"].lower() for m in metrics]
    msg = f"I could not find '{' '.join(unknown)}' among the columns you can see."
    if can:
        msg += " You can chart: " + ", ".join(can) + "."
    return msg


def describe_request(spec: dict, filters: dict) -> str:
    x, y, kind = spec["x"], spec["y"], spec["chart_type"]
    if kind == "Scatter":
        text = f"Scatter chart of {_nice(y)} against {_nice(x)}"
        if spec.get("color"):
            text += f", coloured by {_nice(spec['color'])}"
    else:
        if spec.get("metric"):
            what = spec["metric"]["label"].lower()
        elif y == COUNT_ROWS:
            what = "number of rows"
        else:
            what = f"{AGG_NAMES.get(spec['agg'], '')} {_nice(y)}".strip()
            if spec.get("extra"):
                what += " compared with " + " and ".join(_nice(c) for c in spec["extra"])
        by = _nice(x) if not spec.get("bucket") else f"{spec['bucket'].lower()} ({_nice(x)})"
        text = f"{kind} chart of {what} by {by}"
        if spec.get("color"):
            text += f", split by {_nice(spec['color'])}"
    if filters:
        text += ", only for " + "; ".join(
            f"{_nice(c)} = {', '.join(str(v) for v in vals)}" for c, vals in filters.items())
    return text


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    out = df
    for c, vals in (filters or {}).items():
        if c in out.columns:
            out = out[out[c].isin(vals)]
    return out


def example_questions(df: pd.DataFrame, metrics: list[dict]) -> list[str]:
    """Example questions built from the columns this role can actually see."""
    kinds = {c: _kind(df[c]) for c in df.columns}
    dims = [c for c in _filter_columns(df)]
    nums = [c for c in df.columns if kinds[c] == "number" and df[c].nunique() < len(df)]
    dates = [c for c in df.columns if kinds[c] == "date"]
    out = []
    if nums and dims:
        out.append(f"total {_nice(nums[0])} by {_nice(dims[0])}")
    if metrics and dims:
        m = metrics[0]
        d = next((c for c in dims if c not in (m["col_a"], m["col_b"])), None)
        if d:
            out.append(f"{m['label'].lower()} by {_nice(d)}")
    if dates and nums:
        out.append(f"{_nice(nums[-1])} per month")
    if dims and len(out) < 3:
        out.append(f"share of rows by {_nice(dims[-1])}")
    return out[:3]
