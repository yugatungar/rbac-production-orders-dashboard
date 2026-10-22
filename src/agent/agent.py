"""The only entry point the app uses to answer a plain-English question.

question -> length and rate limits -> allowed schema -> planner (model + validator + retries)
         -> year check (local) -> compiler (SQL built by our code, row rule added)
         -> Snowflake -> result
Every question is written to AGENT_LOG: who, what was asked, the request, the outcome.
"""
import json

import pandas as pd
import streamlit as st

from src.agent.compiler import compile_spec, distinct_values, distinct_years
from src.agent.llm import MAX_QUESTION_CHARS, LLMError, check_rate
from src.agent.planner import plan
from src.agent.schema import build_schema
from src.db import run_query


def _log(user: dict, question: str, res: dict) -> None:
    try:
        run_query(
            "INSERT INTO AGENT_LOG (USERNAME, QUESTION,OUTCOME, ATTEMPTS, REQUEST, ROWS_RETURNED) "
            "VALUES (%(u)s, %(q)s, %(o)s, %(a)s, %(r)s, %(n)s)",
            {"u": user["username"], "q": question[:1000], "o": res["status"].upper(),
             "a": int(res.get("attempts", 0)), "r": json.dumps(res.get("spec") or {})[:2000],
             "n": int(len(res["df"])) if res.get("df") is not None else None},
        )
    except Exception as e:
        st.warning(f"Could not write the AI audit log: {e}")


def _fail(message: str, status: str = "error", detail: str = "") -> dict:
    return {"status": status, "message": message, "detail": detail, "attempts": 0}


def _year_question(user: dict, q: str, spec: dict, schema: dict):
    """A month with no year: use the only year in the data, or ask which one. Checked locally."""
    for f in spec.get("date_filters") or []:
        _ms = ([f["month"]] if f.get("month") else []) + list(f.get("months") or [])
        if _ms and not f.get("year") and not (f.get("from") or f.get("to")):
            years = sorted({y for m in _ms for y in distinct_years(user, spec["table"], f["column"], schema, m)})
            if len(years) == 1:
                f["year"] = years[0]
            elif len(years) > 1:
                return {"question": "Which year do you mean?",
                        "options": [f"{q} (year {y})" for y in years[-4:]]}
    return None


def answer(user: dict, question: str, provider, schema: dict | None = None) -> dict:
    q = " ".join((question or "").split())
    if not q:
        return _fail("Type a question first.")
    if len(q) > MAX_QUESTION_CHARS:
        res = _fail(f"Please keep the question under {MAX_QUESTION_CHARS} characters.")
        _log(user, q, res)
        return res
    try:
        check_rate(user["username"])
        schema = schema or build_schema(user)
        if not schema:
            res = _fail("No tables are available to your role.")
        else:
            distinct = lambda t, c: distinct_values(user, t, c, schema)
            res = plan(provider, q, schema, distinct)
            if res["status"] == "ok":
                ask = _year_question(user, q, res["spec"], schema)
                if ask:
                    res = {"status": "ask", "attempts": res["attempts"], **ask}
                else:
                    sql, params, info = compile_spec(user, res["spec"], schema)
                    df = run_query(sql, params)
                    for a in info["measures"]:
                        df[a] = pd.to_numeric(df[a], errors="coerce")
                    if res["spec"].get("ratio") and len(info["measures"]) == 2:
                        n, d = info["measures"]
                        df["RATE_PCT"] = df[n] / df[d].where(df[d] != 0) * 100
                        info = {**info, "raw": [n, d], "measures": ["RATE_PCT"]}
                    _t = res["spec"].get("top")
                    if _t and info["measures"]:
                        df = df.sort_values(info["measures"][0], ascending=(_t["order"] == "asc"),
                                            na_position="last").head(_t["n"]).reset_index(drop=True)
                    res.update(df=df, info=info, sql=sql)
    except LLMError as e:
        res = _fail(str(e), detail=str(e))
    except Exception as e:  # never show internals to the user
        res = _fail("Something went wrong while answering. Please try again or use the controls below.",
                    detail=f"{type(e).__name__}: {e}")
    _log(user, q, res)
    return res
