import src.agent.sql_guard as sg
from src.agent.sql_guard import guard, GuardError

cols = [("ORDER_ID", "text"), ("ENGINE_MODEL", "text"), ("PLANT", "text"), ("STATUS", "text"),
        ("QTY_PLANNED", "number"), ("QTY_BUILT", "number"), ("DEFECT_COUNT", "number"), ("TARGET_DATE", "date")]
schema = {"PRODUCTION_ORDERS": {"owner_column": "OWNER",
          "columns": {c: {"kind": k, "description": ""} for c, k in cols}}}   # REMARKS and OWNER are hidden
sg._actual_columns = lambda t: ["OWNER", "REMARKS"] + [c for c, _ in cols]
ALL = {"row_scope": "ALL", "username": "t"}
OWN = {"row_scope": "OWN", "username": "bob"}
real = {"STATUS": ["ON_HOLD", "DONE"], "PLANT": ["Pune", "Phaltan"]}
dist = lambda t, c: real.get(c, [])
T = "PRODUCTION_ORDERS"
fails = 0

def good(name, sql, user=ALL, check=None):
    global fails
    try:
        g = guard(sql, user, schema, dist)
        ok = check(g) if check else True
        print(("PASS " if ok else "FAIL ") + name, "" if ok else g["sql"])
        fails += (not ok)
    except Exception as e:
        print("FAIL", name, "->", e); fails += 1

def bad(name, sql, user=ALL):
    global fails
    try:
        guard(sql, user, schema, dist); print("FAIL (allowed!)", name); fails += 1
    except GuardError as e:
        print("PASS blocked:", name, "|", str(e)[:70])
    except Exception as e:
        print("FAIL (crash)", name, "->", type(e).__name__, e); fails += 1

good("group by", f"SELECT PLANT, SUM(QTY_BUILT) AS B FROM {T} GROUP BY PLANT ORDER BY B DESC")
good("rate", f"SELECT PLANT, ROUND(SUM(DEFECT_COUNT)*100.0/NULLIF(SUM(QTY_BUILT),0),2) AS DEFECT_RATE_PCT FROM {T} GROUP BY PLANT ORDER BY 2 LIMIT 1")
good("star expands, hides REMARKS", f"SELECT * FROM {T}", check=lambda g: "REMARKS" not in g["sql"] and "OWNER" not in g["sql"])
good("window", f"SELECT PLANT, RANK() OVER (ORDER BY SUM(QTY_BUILT) DESC) AS R FROM {T} GROUP BY PLANT")
good("cte", f"WITH x AS (SELECT PLANT, SUM(QTY_BUILT) AS B FROM {T} GROUP BY PLANT) SELECT * FROM x")
good("months", f"SELECT EXTRACT(MONTH FROM TARGET_DATE) AS M, SUM(QTY_BUILT) AS B FROM {T} WHERE EXTRACT(MONTH FROM TARGET_DATE) IN (1,2,3) GROUP BY 1")
good("value matched", f"SELECT COUNT(*) AS N FROM {T} WHERE STATUS = 'on hold'", check=lambda g: "ON_HOLD" in g["sql"])
good("limit forced", f"SELECT ORDER_ID FROM {T}", check=lambda g: "LIMIT 500" in g["sql"])
good("row scope", f"SELECT PLANT FROM {T}", OWN, check=lambda g: "%(owner)s" in g["sql"] and g["params"] == {"owner": "bob"})
g = guard(f"SELECT COUNT(*) AS N FROM {T} WHERE STATUS = 'banana'", ALL, schema, dist)
print("PASS unmatched value reported" if g["unmatched"] else "FAIL unmatched not reported")
fails += (not g["unmatched"])

bad("two statements", f"SELECT 1 FROM {T}; SELECT 2 FROM {T}")
bad("drop", f"DROP TABLE {T}")
bad("insert", f"INSERT INTO {T} (PLANT) VALUES ('x')")
bad("other table", "SELECT * FROM SALARIES")
bad("hidden column in WHERE", f"SELECT PLANT FROM {T} WHERE REMARKS = 'x'")
bad("hidden column selected", f"SELECT REMARKS FROM {T}")
bad("owner column", f"SELECT OWNER FROM {T}")
bad("system function", f"SELECT SYSTEM$WHOAMI() FROM {T}")
bad("unknown function", f"SELECT MY_UDF(PLANT) FROM {T}")
bad("schema qualified", f"SELECT PLANT FROM OTHER_DB.PUBLIC.{T}")
bad("table function", "SELECT * FROM TABLE(FLATTEN(INPUT => PARSE_JSON('[1]')))")
bad("cte hides table name", f"WITH {T} AS (SELECT 1 AS A) SELECT A FROM {T}")
print("\nFAILURES:", fails)
