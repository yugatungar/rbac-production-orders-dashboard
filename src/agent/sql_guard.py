"""Checks model-written SQL before it may run. We execute the SQL this module regenerates, never the original text."""
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify

from src.agent.schema import SAFE_NAME
from src.agent.validator import _norm
from src.datasets import _actual_columns

MAX_ROWS = 500
MAX_CHARS = 4000
DISTINCT_CAP = 50
OWNER_TOKEN = "__OWNER__"
_KIND = {"number": "DOUBLE", "date": "DATE", "text": "VARCHAR"}

# Functions the parser does not know by name must be listed here. Add a name = one line.
ALLOWED_FUNCS = {
    "SUM", "AVG", "MIN", "MAX", "COUNT", "COUNT_IF", "MEDIAN", "STDDEV", "STDDEV_POP", "STDDEV_SAMP",
    "VARIANCE", "VAR_POP", "VAR_SAMP", "MODE", "CORR", "PERCENTILE_CONT", "PERCENTILE_DISC",
    "APPROX_COUNT_DISTINCT", "ANY_VALUE", "RANK", "DENSE_RANK", "PERCENT_RANK", "CUME_DIST", "NTILE",
    "ROW_NUMBER", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE", "NTH_VALUE", "DIV0", "DIV0NULL",
    "ZEROIFNULL", "NULLIFZERO", "IFF", "NVL", "NVL2", "IFNULL", "GREATEST", "LEAST", "ROUND", "TRUNC",
    "TRUNCATE", "CEIL", "FLOOR", "ABS", "SIGN", "MOD", "POWER", "SQRT", "LN", "LOG", "EXP", "UPPER",
    "LOWER", "INITCAP", "TRIM", "LTRIM", "RTRIM", "LENGTH", "LEN", "SUBSTR", "SUBSTRING", "LEFT", "RIGHT",
    "REPLACE", "CONCAT", "CONTAINS", "STARTSWITH", "ENDSWITH", "POSITION", "DATE_TRUNC", "DATEADD",
    "DATEDIFF", "TIMEDIFF", "TIMESTAMPDIFF", "TIMESTAMPADD", "LAST_DAY", "DAYNAME", "MONTHNAME",
    "DAYOFWEEK", "DAYOFMONTH", "DAYOFYEAR", "WEEKOFYEAR", "WEEK", "YEAR", "MONTH", "DAY", "QUARTER",
    "HOUR", "MINUTE", "SECOND", "CURRENT_DATE", "CURRENT_TIMESTAMP", "TO_DATE", "TO_CHAR", "TO_VARCHAR",
    "TO_NUMBER", "TO_DECIMAL", "TRY_TO_NUMBER", "TRY_TO_DATE",
}
_BLOCKED_NAMES = ("Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy",
                  "Into", "Use", "Set", "Transaction", "Commit", "Rollback", "Grant", "TruncateTable",
                  "Describe", "Lateral", "Unnest", "Pivot", "Unpivot", "Dot", "Parameter", "Placeholder",
                  "SessionParameter")
_BLOCKED = tuple(c for c in (getattr(exp, n, None) for n in _BLOCKED_NAMES) if isinstance(c, type))
_QUERY_TYPES = (exp.Select, getattr(exp, "SetOperation", exp.Union))


class GuardError(ValueError):
    """Message is safe to send back to the AI: names only, never data."""


def _short(e) -> str:
    return " ".join(str(e).split())[:160]


def _fix_values(q, schema, alias_map, distinct_fn):
    notes, unmatched, cache = [], [], {}

    def real_values(table, col):
        if (table, col) not in cache:
            try:
                cache[(table, col)] = list(distinct_fn(table, col))
            except Exception:
                cache[(table, col)] = []
        return cache[(table, col)]

    def handle(col, lits):
        table = alias_map.get(col.table.upper()) if col.table else None
        if not table:
            return
        cols = {c.upper(): c for c in schema[table]["columns"]}
        real_name = cols.get(col.name.upper())
        if not real_name or schema[table]["columns"][real_name]["kind"] != "text":
            return
        vals = real_values(table, real_name)
        if not vals or len(vals) > DISTINCT_CAP:
            return
        lookup = {_norm(v): str(v) for v in vals}
        for lit in lits:
            asked = lit.this
            hit = lookup.get(_norm(asked))
            if hit is None:
                unmatched.append({"column": real_name, "asked": asked, "choices": sorted(map(str, vals))})
            elif hit != asked:
                lit.set("this", hit)
                notes.append(f"Matched '{asked}' to {hit} in {real_name.replace('_', ' ').lower()}.")

    for node in list(q.find_all(exp.EQ, exp.NEQ)):
        a, b = node.this, node.expression
        for col, lit in ((a, b), (b, a)):
            if isinstance(col, exp.Column) and isinstance(lit, exp.Literal) and lit.is_string:
                handle(col, [lit])
    for node in list(q.find_all(exp.In)):
        if isinstance(node.this, exp.Column):
            lits = [e for e in node.expressions if isinstance(e, exp.Literal) and e.is_string]
            if lits:
                handle(node.this, lits)
    return notes, unmatched


def guard(sql: str, user: dict, schema: dict, distinct_fn=None) -> dict:
    """Returns {'sql', 'params', 'notes', 'unmatched'} or raises GuardError."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise GuardError("The query is empty.")
    if len(sql) > MAX_CHARS:
        raise GuardError("The query is too long.")
    if "@" in sql or "$" in sql or OWNER_TOKEN in sql:
        raise GuardError("The characters @ and $ are not allowed.")
    try:
        stmts = [s for s in sqlglot.parse(sql, read="snowflake") if s is not None]
    except SqlglotError as e:
        raise GuardError("The query could not be parsed: " + _short(e))
    if len(stmts) != 1:
        raise GuardError("Exactly one statement is allowed.")
    tree = stmts[0]
    if not isinstance(tree, _QUERY_TYPES):
        raise GuardError("Only a SELECT query is allowed.")

    for node in tree.find_all(exp.Expression):
        if _BLOCKED and isinstance(node, _BLOCKED):
            raise GuardError(f"{type(node).__name__} is not allowed in a read-only query.")
        if isinstance(node, exp.Anonymous):
            name = str(node.name).upper()
            if name not in ALLOWED_FUNCS:
                raise GuardError(f"Function {name} is not allowed. Use standard functions such as SUM, COUNT, ROUND, DATE_TRUNC.")
        elif isinstance(node, exp.Table) and not isinstance(node.this, exp.Identifier):
            raise GuardError("Table functions are not allowed.")

    allowed = {t.upper(): t for t in schema}
    cte_names = {c.alias.upper() for c in tree.find_all(exp.CTE) if c.alias}
    if cte_names & set(allowed):
        raise GuardError("A WITH name may not reuse a table name.")
    used = []
    for t in tree.find_all(exp.Table):
        if t.args.get("db") or t.args.get("catalog"):
            raise GuardError("Use plain table names, not schema-qualified ones.")
        n = t.name.upper()
        if n in cte_names:
            continue
        if n not in allowed:
            raise GuardError(f"Table {t.name} is not available. Available tables: " + ", ".join(schema) + ".")
        if allowed[n] not in used:
            used.append(allowed[n])
    if not used:
        raise GuardError("The query must read from one of the available tables.")

    sch = {t: {c: _KIND.get(i["kind"], "VARCHAR") for c, i in schema[t]["columns"].items()} for t in used}
    try:
        q = qualify(tree.copy(), schema=sch, dialect="snowflake", validate_qualify_columns=True)
    except Exception as e:
        raise GuardError("A column could not be matched to your allowed columns: " + _short(e))

    ok = {c.upper() for t in used for c in schema[t]["columns"]}
    aliases = {a.alias.upper() for a in q.find_all(exp.Alias) if a.alias}
    for ta in q.find_all(exp.TableAlias):
        aliases.update(i.name.upper() for i in ta.columns)
    for col in q.find_all(exp.Column):
        n = col.name.upper()
        if n in ("", "*"):
            continue
        if n not in ok and n not in aliases:
            raise GuardError(f"Column {col.name} is not available. Available columns: " +
                             ", ".join(sorted({c for t in used for c in schema[t]['columns']})) + ".")

    cols_used = sorted({c.name.upper() for c in q.find_all(exp.Column) if c.name.upper() in ok})
    alias_map = {}
    for t in q.find_all(exp.Table):
        if t.name.upper() in allowed:
            alias_map[(t.alias or t.name).upper()] = allowed[t.name.upper()]
    notes, unmatched = ([], [])
    if distinct_fn is not None:
        notes, unmatched = _fix_values(q, schema, alias_map, distinct_fn)

    params = {}
    if user.get("row_scope") != "ALL":
        for t in list(q.find_all(exp.Table)):
            n = t.name.upper()
            if n in cte_names:
                continue
            real = allowed[n]
            owner = schema[real].get("owner_column")
            if not owner or not SAFE_NAME.match(owner) or owner not in _actual_columns(real):
                raise GuardError("Your role can only see its own rows, and this table has no owner column.")
            cols = ", ".join(f'"{c}"' for c in schema[real]["columns"])
            inner = sqlglot.parse_one(f"SELECT {cols} FROM \"{real}\" WHERE \"{owner}\" = '{OWNER_TOKEN}'", read="snowflake")
            t.replace(exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(t.alias or t.name, quoted=True))))
        params["owner"] = user["username"]

    limit_added = False
    cur = None
    lim = q.args.get("limit")
    if lim is not None:
        try:
            cur = int(lim.expression.name)
        except Exception:
            cur = None
    if cur is None or cur > MAX_ROWS:
        try:
            q = q.limit(MAX_ROWS)
            limit_added = True
        except Exception:
            raise GuardError("A row limit could not be applied.")

    out = q.sql(dialect="snowflake")
    if params:
        out = out.replace("%", "%%").replace(f"'{OWNER_TOKEN}'", "%(owner)s")
    receipt = {"tables": list(used), "columns_used": cols_used, "columns_allowed": len(ok),
               "row_filter": bool(params), "limit_added": limit_added, "fixes": list(notes)}
    return {"sql": out, "params": params, "notes": notes, "unmatched": unmatched, "receipt": receipt}
