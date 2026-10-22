from src.agent.validator import validate
from src.agent.compiler import compile_spec
schema = {"ORDERS": {"owner_column": None, "columns": {
    "ORDER_DATE": {"kind": "date", "description": ""},
    "REVENUE": {"kind": "number", "description": ""}}}}
base = {"table": "ORDERS", "chart": "Bar", "x": "ORDER_DATE", "bucket": "Month",
        "measures": [{"column": "REVENUE", "agg": "Sum"}]}
ok = validate({**base, "date_filters": [{"column": "ORDER_DATE", "months": [1, 2, 3], "year": 2026}]},
              schema, lambda t, c: [])
print("good:", ok["ok"], ok["errors"])
bad = validate({**base, "date_filters": [{"column": "ORDER_DATE", "months": [1, 13]}]},
               schema, lambda t, c: [])
print("bad rejected:", not bad["ok"], bad["errors"])
sql, params, _ = compile_spec({"row_scope": "ALL", "username": "t"}, ok["spec"], schema)
print(sql); print(params)
