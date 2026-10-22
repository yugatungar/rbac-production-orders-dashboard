"""Checks a chart request (a small JSON object) against the schema the role is allowed to use.

Nothing from the AI is trusted. Every table, column, chart type and aggregation is looked up
in a fixed list. Problems found here go back to the AI as short error messages (names only,
never data values). Filter values that do not match real data are returned as 'clarify'
questions for the USER, not the AI.
"""
import re
from datetime import date

CHARTS = ("Bar", "Line", "Area", "Pie", "Table")
AGGS = ("Sum", "Average", "Count", "Min", "Max")
BUCKETS = ("Day", "Month", "Year")
MAX_MEASURES = 3
MAX_FILTERS = 5
MAX_VALUES = 20
MAX_GROUP_BY = 4
MAX_DATE_FILTERS = 2
DISTINCT_CAP = 50
ALLOWED_KEYS = {"table", "chart", "x", "group_by", "measures", "color", "bucket", "filters", "date_filters", "focus", "ratio", "top"}
DATE_KEYS = {"column", "year", "month", "months", "from", "to"}
_AGG_WORDS = {"sum": "Sum", "total": "Sum", "average": "Average", "avg": "Average", "mean": "Average",
              "count": "Count", "min": "Min", "minimum": "Min", "max": "Max", "maximum": "Max"}
_COUNT_ROWS = {None, "", "*", "(count of rows)"}


def _match(name, options):
    if not isinstance(name, str):
        return None
    for o in options:
        if o.upper() == name.strip().upper():
            return o
    return None


def _norm(s):
    """Compare values ignoring case, underscores, hyphens and extra spaces."""
    return " ".join(re.sub(r"[_\-]+", " ", str(s)).split()).upper()


def _int_in(v, lo, hi):
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def validate(spec, schema: dict, distinct_fn) -> dict:
    """Returns {'ok', 'spec', 'errors', 'clarify', 'notes'}.

    errors  -> messages for the AI (retry)
    clarify -> questions for the user, e.g. [{'column','asked','choices'}]
    distinct_fn(table, column) -> list of real values (at most DISTINCT_CAP + 1), scoped to the user's rows
    """
    errors, notes, clarify = [], [], []

    def fail():
        return {"ok": False, "spec": None, "errors": errors, "clarify": [], "notes": notes}

    if not isinstance(spec, dict):
        errors.append("The request must be a JSON object.")
        return fail()
    extra = sorted(set(spec) - ALLOWED_KEYS)
    if extra:
        errors.append("Unexpected keys: " + ", ".join(map(str, extra)) + ". Allowed keys: " + ", ".join(sorted(ALLOWED_KEYS)) + ".")

    table = _match(spec.get("table"), schema)
    if table is None:
        errors.append("Unknown table. Use exactly one of: " + (", ".join(schema) or "(none available)") + ".")
        return fail()
    cols = schema[table]["columns"]
    names = list(cols)

    def col_error(label, value):
        errors.append(f"{label} '{value}' is not an available column of {table}. Available columns: " + ", ".join(names) + ".")

    chart = _match(spec.get("chart"), CHARTS)
    if chart is None:
        errors.append("chart must be one of: " + ", ".join(CHARTS) + ".")

    # ---- what to group by: x for charts, group_by for Table
    x = _match(spec.get("x"), names)
    group_by = []
    if chart == "Table":
        raw_gb = spec.get("group_by")
        raw_gb = [] if raw_gb in (None, "") else raw_gb
        if not isinstance(raw_gb, list) or len(raw_gb) > MAX_GROUP_BY:
            errors.append(f"group_by must be a list of at most {MAX_GROUP_BY} column names.")
            raw_gb = []
        for g in ([x] if x else []) + list(raw_gb):
            c = _match(g, names)
            if c is None:
                col_error("group_by", g)
            elif c not in group_by:
                group_by.append(c)
        x = None
    else:
        if x is None:
            col_error("x", spec.get("x"))
        if spec.get("group_by"):
            notes.append("group_by is only used with the Table type and was ignored.")
    if chart == "Table" and len(group_by) == 1 and cols[group_by[0]]["kind"] != "number":
        x = group_by[0]
        chart = "Line" if cols[x]["kind"] == "date" else "Bar"
        group_by = []
        notes.append("A single grouping is drawn as a chart.")
    dims = group_by if chart == "Table" else ([x] if x else [])

    # ---- measures
    raw_measures = spec.get("measures")
    measures, seen = [], set()
    if not isinstance(raw_measures, list) or not (1 <= len(raw_measures) <= MAX_MEASURES):
        errors.append(f"measures must be a list of 1 to {MAX_MEASURES} items like {{\"column\": \"COL\", \"agg\": \"Sum\"}}.")
    else:
        for m in raw_measures:
            if not isinstance(m, dict) or set(m) - {"column", "agg"}:
                errors.append("Each measure must be an object with only 'column' and 'agg'.")
                continue
            agg = _AGG_WORDS.get(str(m.get("agg", "")).strip().lower())
            if agg is None:
                errors.append("agg must be one of: " + ", ".join(AGGS) + ".")
                continue
            raw_col = m.get("column")
            if raw_col in _COUNT_ROWS:
                if agg != "Count":
                    errors.append("A measure with no column can only use agg 'Count' (count of rows).")
                    continue
                col = None
            else:
                col = _match(raw_col, names)
                if col is None:
                    col_error("measure column", raw_col)
                    continue
                if agg != "Count" and cols[col]["kind"] != "number":
                    errors.append(f"{agg} needs a number column, but {col} is {cols[col]['kind']}. Use Count, or pick a number column.")
                    continue
            if (col, agg) in seen:
                errors.append("The same measure is listed twice.")
                continue
            seen.add((col, agg))
            measures.append({"column": col, "agg": agg})
        if chart == "Pie" and len(raw_measures) != 1:
            errors.append("A Pie chart needs exactly one measure.")

    # ---- date bucket
    bucket = spec.get("bucket")
    if any(cols[c]["kind"] == "date" for c in dims):
        if bucket in (None, ""):
            bucket = "Month"
        else:
            bucket = _match(bucket, BUCKETS)
            if bucket is None:
                errors.append("bucket must be one of: " + ", ".join(BUCKETS) + ".")
    else:
        if bucket not in (None, ""):
            notes.append("Date grouping was ignored because no grouped column is a date.")
        bucket = None

    # ---- colour (split by)
    color = spec.get("color")
    if color not in (None, ""):
        c = _match(color, names)
        if c is None:
            col_error("color", color)
            color = None
        elif cols[c]["kind"] != "text" or c == x:
            notes.append("The split-by column was ignored: it must be a text column other than X.")
            color = None
        elif chart in ("Pie", "Table") or len(measures) != 1:
            notes.append("The split-by column was ignored: it works only with one measure and not with Pie or Table.")
            color = None
        else:
            color = c
    else:
        color = None

    # ---- filters on text / number columns
    filters = []
    raw_filters = spec.get("filters") or []
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_FILTERS:
        errors.append(f"filters must be a list of at most {MAX_FILTERS} items like {{\"column\": \"COL\", \"values\": [\"A\"]}}.")
        raw_filters = []
    for f in raw_filters:
        if not isinstance(f, dict) or set(f) - {"column", "values"}:
            errors.append("Each filter must be an object with only 'column' and 'values'.")
            continue
        col = _match(f.get("column"), names)
        vals = f.get("values")
        if col is None:
            col_error("filter column", f.get("column"))
            continue
        if not isinstance(vals, list) or not (1 <= len(vals) <= MAX_VALUES):
            errors.append(f"Filter values for {col} must be a list of 1 to {MAX_VALUES} items.")
            continue
        kind = cols[col]["kind"]
        if kind == "date":
            errors.append(f"{col} is a date column. Use date_filters for dates, not filters.")
        elif kind == "number":
            nums = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if len(nums) != len(vals):
                errors.append(f"Filter values for {col} must be numbers.")
            else:
                filters.append({"column": col, "values": nums})
        else:
            if not all(isinstance(v, str) for v in vals):
                errors.append(f"Filter values for {col} must be text.")
                continue
            real = list(distinct_fn(table, col))
            if len(real) > DISTINCT_CAP:
                filters.append({"column": col, "values": [v.strip() for v in vals]})
                notes.append(f"{col} has many distinct values, so the filter values were used as typed.")
                continue
            lookup = {_norm(r): r for r in real}
            good, bad = [], []
            for v in vals:
                hit = lookup.get(_norm(v))
                (good if hit is not None else bad).append(hit if hit is not None else v)
            for v in bad:
                clarify.append({"column": col, "asked": v, "choices": sorted(map(str, real))})
            if good:
                filters.append({"column": col, "values": good})

    # ---- date filters (month / year / from-to)
    date_filters = []
    raw_dates = spec.get("date_filters") or []
    if not isinstance(raw_dates, list) or len(raw_dates) > MAX_DATE_FILTERS:
        errors.append(f"date_filters must be a list of at most {MAX_DATE_FILTERS} items.")
        raw_dates = []
    for f in raw_dates:
        if not isinstance(f, dict) or set(f) - DATE_KEYS:
            errors.append("Each date filter must be an object with only 'column', 'year', 'month', 'months', 'from' and 'to'.")
            continue
        col = _match(f.get("column"), names)
        if col is None:
            col_error("date filter column", f.get("column"))
            continue
        if cols[col]["kind"] != "date":
            errors.append(f"{col} is not a date column, so it cannot be used in date_filters.")
            continue
        year, month = f.get("year"), f.get("month")
        if year is not None and not _int_in(year, 1900, 2100):
            errors.append("year must be a whole number like 2026, or null.")
            continue
        if month is not None and not _int_in(month, 1, 12):
            errors.append("month must be a whole number from 1 to 12, or null.")
            continue
        months = f.get("months")
        if months in (None, "", []):
            months = None
        elif (not isinstance(months, list) or len(months) > 12
              or not all(_int_in(v, 1, 12) for v in months)):
            errors.append("months must be a list of whole numbers from 1 to 12, or null.")
            continue
        else:
            months = sorted(set(months) | ({month} if month else set()))
            month = None
        bounds, bad_date = {}, False
        for k in ("from", "to"):
            v = f.get(k)
            if v in (None, ""):
                bounds[k] = None
                continue
            try:
                bounds[k] = date.fromisoformat(str(v)).isoformat()
            except ValueError:
                errors.append(f"'{k}' must be a date written like 2026-10-31, or null.")
                bad_date = True
        if bad_date:
            continue
        if year is None and month is None and not months and not (bounds["from"] or bounds["to"]):
            errors.append("A date filter needs a year, a month, or a from/to date.")
            continue
        date_filters.append({"column": col, "year": year, "month": month, "months": months,
                             "from": bounds["from"], "to": bounds["to"]})

    if errors:
        return fail()
    # ---- focus: the one value the user asked about (matched locally, never sent to the AI)
    focus = None
    raw_focus = spec.get("focus")
    if isinstance(raw_focus, dict) and set(raw_focus) <= {"column", "value"}:
        fcol = _match(raw_focus.get("column"), names)
        fval = raw_focus.get("value")
        if fcol and (fcol in dims or fcol == color) and cols[fcol]["kind"] == "text" and isinstance(fval, str) and fval.strip():
            real = list(distinct_fn(table, fcol))
            if len(real) > DISTINCT_CAP:
                focus = {"column": fcol, "value": fval.strip()}
            else:
                hit = {_norm(r): r for r in real}.get(_norm(fval))
                if hit is not None:
                    focus = {"column": fcol, "value": str(hit)}
    if raw_focus not in (None, "") and focus is None:
        notes.append("The specific value asked about could not be matched, so no single-value answer is shown.")

    clean = {"table": table, "chart": chart, "x": x, "group_by": group_by, "bucket": bucket,
             "measures": measures, "color": color, "filters": filters, "date_filters": date_filters,
             "ratio": spec.get("ratio") is True and len(measures) == 2 and chart != "Pie"
                      and all(m["agg"] in ("Sum", "Count") for m in measures),
             "top": ({"n": spec["top"]["n"], "order": "asc" if spec["top"].get("order") == "asc" else "desc"}
                     if isinstance(spec.get("top"), dict) and _int_in(spec["top"].get("n"), 1, 50) else None)}
    return {"ok": True, "spec": clean, "errors": [], "clarify": clarify, "notes": notes, "focus": focus}
